"""Skill storage layout and legacy flat-directory migration."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


BUILTIN_SKILL_OWNER = "__determinflow_builtin__"
MARKETPLACE_SKILL_OWNER = "__determinflow_marketplace__"
CORE_RESOURCE_MARKER = ".core-resources.json"
_SOURCE_DIRECTORIES = frozenset({"builtin", "local", "marketplace"})
_IGNORED_TREE_PARTS = frozenset({"__pycache__"})
_IGNORED_TREE_FILES = frozenset({".DS_Store", CORE_RESOURCE_MARKER})


@dataclass(frozen=True)
class SkillStorageLayout:
    """Physical roots for Skills with different trust and lifecycle owners."""

    root: Path
    builtin: Path
    local: Path
    marketplace: Path
    provenance: Path
    backup_parent: Path

    @classmethod
    def from_root(cls, root: Path) -> "SkillStorageLayout":
        root = root.resolve()
        return cls(
            root=root,
            builtin=root / "builtin",
            local=root / "local",
            marketplace=root / "marketplace",
            provenance=root.parent / "resource-provenance.json",
            backup_parent=root.parent / "skill-migration-backups",
        )

    def ensure_directories(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.builtin.mkdir(parents=True, exist_ok=True)
        self.local.mkdir(parents=True, exist_ok=True)
        self.marketplace.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SkillStorageMigration:
    moved_builtin: tuple[str, ...]
    moved_local: tuple[str, ...]
    moved_marketplace: tuple[str, ...]
    backed_up: tuple[str, ...]
    backup_directory: Path | None


def _tree_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    if not root.is_dir():
        return manifest
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in _IGNORED_TREE_PARTS for part in relative.parts):
            continue
        if path.name in _IGNORED_TREE_FILES or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_file():
            manifest[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _marketplace_skill_ids(provenance_path: Path) -> set[str]:
    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()
    resources = payload.get("resources") if isinstance(payload, dict) else None
    if not isinstance(resources, dict):
        return set()
    result: set[str] = set()
    for entry in resources.values():
        if not isinstance(entry, dict) or entry.get("resource_type") != "skill":
            continue
        source = entry.get("source")
        local_id = entry.get("local_id")
        if (
            isinstance(source, dict)
            and source.get("kind") == "marketplace"
            and isinstance(local_id, str)
            and local_id
        ):
            result.add(local_id)
    return result


def migrate_legacy_skill_layout(
    layout: SkillStorageLayout,
    *,
    bundled_skills: Path,
) -> SkillStorageMigration:
    """Move legacy ``skills/<id>`` entries into source-owned roots.

    A legacy Core directory is only moved into ``builtin`` when its complete
    meaningful file tree matches the currently bundled copy. Divergent Core
    content is moved to a recovery directory before current bundled content is
    provisioned, so no user data is silently overwritten or mislabeled.
    """

    layout.ensure_directories()
    bundled_skills = bundled_skills.resolve()
    core_ids = {
        path.name
        for path in bundled_skills.iterdir()
        if path.is_dir()
    } if bundled_skills.is_dir() else set()
    marketplace_ids = _marketplace_skill_ids(layout.provenance)
    legacy_directories = [
        path
        for path in sorted(layout.root.iterdir())
        if path.is_dir()
        and path.name not in _SOURCE_DIRECTORIES
        and not path.name.startswith(".")
    ]

    moved_builtin: list[str] = []
    moved_local: list[str] = []
    moved_marketplace: list[str] = []
    backed_up: list[str] = []
    backup_directory: Path | None = None

    def recovery_directory() -> Path:
        nonlocal backup_directory
        if backup_directory is None:
            layout.backup_parent.mkdir(parents=True, exist_ok=True)
            backup_directory = Path(
                tempfile.mkdtemp(prefix="legacy-flat-", dir=layout.backup_parent)
            )
        return backup_directory

    def move(source: Path, destination: Path) -> None:
        if destination.exists():
            raise FileExistsError(
                f"Skill 迁移目标已存在，已停止以避免覆盖: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    for legacy in legacy_directories:
        skill_id = legacy.name
        if skill_id in marketplace_ids:
            move(legacy, layout.marketplace / skill_id)
            moved_marketplace.append(skill_id)
            continue
        if skill_id not in core_ids:
            move(legacy, layout.local / skill_id)
            moved_local.append(skill_id)
            continue

        bundled = bundled_skills / skill_id
        if _tree_manifest(legacy) == _tree_manifest(bundled):
            move(legacy, layout.builtin / skill_id)
            moved_builtin.append(skill_id)
        else:
            move(legacy, recovery_directory() / skill_id)
            backed_up.append(skill_id)

    legacy_marker = layout.root / CORE_RESOURCE_MARKER
    if legacy_marker.exists():
        move(legacy_marker, recovery_directory() / CORE_RESOURCE_MARKER)

    return SkillStorageMigration(
        moved_builtin=tuple(moved_builtin),
        moved_local=tuple(moved_local),
        moved_marketplace=tuple(moved_marketplace),
        backed_up=tuple(backed_up),
        backup_directory=backup_directory,
    )
