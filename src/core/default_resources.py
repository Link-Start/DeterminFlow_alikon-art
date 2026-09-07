"""Provision versioned Core resources into an instance data directory."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil

from src.skills.storage import CORE_RESOURCE_MARKER


DEFAULT_RESOURCES_DIR = Path(__file__).parent / "defaults"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provision_core_skills(skills_dir: Path) -> list[Path]:
    """Mirror bundled Core Skills into their immutable runtime root."""
    source_dir = DEFAULT_RESOURCES_DIR / "skills"
    if not source_dir.is_dir():
        return []

    skills_dir.mkdir(parents=True, exist_ok=True)
    marker_path = skills_dir / CORE_RESOURCE_MARKER
    installed_files: dict[str, dict[str, str]] = {}
    synchronized: list[Path] = []
    expected_files: set[str] = set()
    for source in sorted(
        path
        for path in source_dir.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ):
        relative = source.relative_to(source_dir).as_posix()
        expected_files.add(relative)
        target = skills_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source_hash = _file_hash(source)
        target_hash = _file_hash(target) if target.is_file() else ""
        if target_hash != source_hash:
            temporary = target.with_name(target.name + ".tmp")
            try:
                shutil.copy2(source, temporary)
                with temporary.open("r+b") as target_file:
                    os.fsync(target_file.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            synchronized.append(target)
        installed_files[relative] = {"installed_hash": source_hash}

    for installed_path in sorted(skills_dir.rglob("*"), reverse=True):
        relative = installed_path.relative_to(skills_dir).as_posix()
        if installed_path == marker_path:
            continue
        if installed_path.is_symlink() or installed_path.is_file():
            if relative not in expected_files:
                installed_path.unlink()
            continue
        if installed_path.is_dir():
            try:
                installed_path.rmdir()
            except OSError:
                pass

    marker_data = {"files": installed_files}
    temp_marker = marker_path.with_suffix(".json.tmp")
    temp_marker.write_text(
        json.dumps(marker_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp_marker, marker_path)
    return synchronized
