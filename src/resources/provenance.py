"""Persistent provenance records for locally installed resources."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ResourceProvenanceStore:
    """Keep server-owned source facts outside editable resource manifests."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = path
        self._data = self._load()

    @staticmethod
    def key(resource_type: str, local_id: str) -> str:
        return f"{resource_type}:{local_id}"

    def get(self, resource_type: str, local_id: str) -> dict[str, Any] | None:
        value = self._data["resources"].get(self.key(resource_type, local_id))
        return dict(value) if isinstance(value, dict) else None

    def record(
        self,
        resource_type: str,
        local_id: str,
        *,
        source: dict[str, Any],
        package: dict[str, Any],
        installed_at: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "resource_type": resource_type,
            "local_id": local_id,
            "source": dict(source),
            "package": dict(package),
            "installed_at": installed_at
            or datetime.now(timezone.utc).isoformat(),
        }
        self._data["resources"][self.key(resource_type, local_id)] = entry
        self._save()
        return dict(entry)

    def remove(self, resource_type: str, local_id: str) -> bool:
        removed = self._data["resources"].pop(
            self.key(resource_type, local_id), None
        )
        if removed is None:
            return False
        self._save()
        return True

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            value = {}
        if not isinstance(value, dict) or value.get("schema_version") != self.SCHEMA_VERSION:
            return {"schema_version": self.SCHEMA_VERSION, "resources": {}}
        resources = value.get("resources")
        if not isinstance(resources, dict):
            value["resources"] = {}
        return value

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
