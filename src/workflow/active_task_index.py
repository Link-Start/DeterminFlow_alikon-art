"""Persistent hot-Task markers for bounded Workflow recovery scans."""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ACTIVE_TASK_STATUSES = frozenset({
    "pending",
    "pre_running",
    "running",
    "retry_waiting",
    "resume_pending",
})
RECOVERY_TASK_STATUSES = frozenset({
    "running",
    "retry_waiting",
    "resume_pending",
})
INDEX_SCHEMA_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class ActiveTaskIndexError(RuntimeError):
    """Raised when the recovery index cannot be proven complete and safe."""


@dataclass(frozen=True)
class ActiveTaskRef:
    workflow_id: str
    task_id: str


def _atomic_write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ActiveTaskIndex:
    """Maintain one small marker per non-terminal Workflow Task.

    Entering an active state writes the marker before the authoritative Task
    snapshot. Leaving an active state removes it only after the Task snapshot
    is durable. A crash can therefore leave a harmless stale marker, but cannot
    omit a recoverable Task.
    """

    def __init__(self, workflows_dir: Path):
        self.workflows_dir = Path(workflows_dir)
        self.root = (
            self.workflows_dir.parent / "system" / "active-workflow-tasks"
        )
        self.manifest_path = self.root / "manifest.json"

    @staticmethod
    def _validate_id(value: Any, field: str) -> str:
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise ActiveTaskIndexError(f"invalid {field} in active Task index")
        return value

    def _marker_path(self, workflow_id: str, task_id: str) -> Path:
        safe_workflow = self._validate_id(workflow_id, "workflow_id")
        safe_task = self._validate_id(task_id, "task_id")
        return self.root / safe_workflow / f"{safe_task}.json"

    @staticmethod
    def _marker_document(workflow_id: str, task_id: str) -> dict[str, Any]:
        return {
            "schema_version": INDEX_SCHEMA_VERSION,
            "workflow_id": workflow_id,
            "task_id": task_id,
        }

    def track_before_save(self, task: Any) -> None:
        if task.status not in ACTIVE_TASK_STATUSES:
            return
        marker = self._marker_path(task.workflow_id, task.task_id)
        if marker.is_file() and not marker.is_symlink():
            return
        if marker.exists() or marker.is_symlink():
            raise ActiveTaskIndexError("unsafe active Task marker path")
        _atomic_write_json(
            marker,
            self._marker_document(task.workflow_id, task.task_id),
        )

    def track_after_save(self, task: Any) -> None:
        if task.status in ACTIVE_TASK_STATUSES:
            return
        self.remove(task.workflow_id, task.task_id)

    def remove(self, workflow_id: str, task_id: str) -> None:
        marker = self._marker_path(workflow_id, task_id)
        if marker.is_symlink():
            raise ActiveTaskIndexError("refusing symlink active Task marker")
        marker.unlink(missing_ok=True)
        try:
            marker.parent.rmdir()
        except OSError:
            pass

    def _manifest_is_ready(self) -> bool:
        if self.manifest_path.is_symlink() or not self.manifest_path.is_file():
            return False
        try:
            document = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return document == {
            "schema_version": INDEX_SCHEMA_VERSION,
            "ready": True,
        }

    def ensure_ready(self) -> None:
        if self._manifest_is_ready():
            return
        if self.manifest_path.exists() or self.manifest_path.is_symlink():
            raise ActiveTaskIndexError("active Task index manifest is invalid")
        self.rebuild()

    def rebuild(self) -> None:
        parent = self.root.parent
        parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f".{self.root.name}.rebuild-{uuid.uuid4().hex[:8]}"
        stale = parent / f".{self.root.name}.stale-{uuid.uuid4().hex[:8]}"
        temporary.mkdir(mode=0o700)
        try:
            for task_path in sorted(self.workflows_dir.glob("*/tasks/*.json")):
                if task_path.is_symlink() or not task_path.is_file():
                    raise ActiveTaskIndexError(
                        f"unsafe Workflow Task path during index rebuild: {task_path}"
                    )
                try:
                    document = json.loads(task_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise ActiveTaskIndexError(
                        f"unreadable Workflow Task during index rebuild: {task_path}"
                    ) from exc
                if not isinstance(document, dict):
                    raise ActiveTaskIndexError(
                        f"invalid Workflow Task during index rebuild: {task_path}"
                    )
                status = document.get("status")
                if not isinstance(status, str):
                    raise ActiveTaskIndexError(
                        f"Workflow Task has no status during index rebuild: {task_path}"
                    )
                if status not in ACTIVE_TASK_STATUSES:
                    continue
                workflow_id = self._validate_id(
                    document.get("workflow_id"), "workflow_id"
                )
                task_id = self._validate_id(document.get("task_id"), "task_id")
                if (
                    workflow_id != task_path.parent.parent.name
                    or task_id != task_path.stem
                ):
                    raise ActiveTaskIndexError(
                        f"Workflow Task identity mismatch during index rebuild: {task_path}"
                    )
                marker = temporary / workflow_id / f"{task_id}.json"
                _atomic_write_json(
                    marker,
                    self._marker_document(workflow_id, task_id),
                )
            _atomic_write_json(
                temporary / "manifest.json",
                {"schema_version": INDEX_SCHEMA_VERSION, "ready": True},
            )
            if self.root.exists() or self.root.is_symlink():
                if self.root.is_symlink() or not self.root.is_dir():
                    raise ActiveTaskIndexError("unsafe active Task index root")
                os.replace(self.root, stale)
            os.replace(temporary, self.root)
            if stale.exists():
                shutil.rmtree(stale)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
            if stale.exists() and not self.root.exists():
                os.replace(stale, self.root)

    def refs(self) -> list[ActiveTaskRef]:
        self.ensure_ready()
        refs: list[ActiveTaskRef] = []
        for marker in sorted(self.root.glob("*/*.json")):
            if marker.is_symlink() or not marker.is_file():
                raise ActiveTaskIndexError("unsafe active Task marker")
            try:
                document = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ActiveTaskIndexError("unreadable active Task marker") from exc
            if not isinstance(document, dict) or document.get(
                "schema_version"
            ) != INDEX_SCHEMA_VERSION:
                raise ActiveTaskIndexError("invalid active Task marker")
            workflow_id = self._validate_id(
                document.get("workflow_id"), "workflow_id"
            )
            task_id = self._validate_id(document.get("task_id"), "task_id")
            if workflow_id != marker.parent.name or task_id != marker.stem:
                raise ActiveTaskIndexError("active Task marker identity mismatch")
            refs.append(ActiveTaskRef(workflow_id, task_id))
        return refs

    def recovery_refs(self) -> list[ActiveTaskRef]:
        return self.refs()
