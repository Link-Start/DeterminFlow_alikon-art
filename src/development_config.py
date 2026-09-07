"""Local development configuration bootstrap helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _configured_directory() -> str | None:
    return os.getenv("DETERMINFLOW_CONFIG_DIR") or os.getenv(
        "AI_COMPANY_CONFIG_DIR"
    )


def _sync_model_provider_catalog(project_root: Path, target: Path) -> None:
    source_provider = os.getenv(
        "DETERMINFLOW_DEVELOPMENT_MODEL_PROVIDER_SOURCE", ""
    ).strip()
    if not source_provider:
        return

    config = target / "models_config.json"
    snapshot = target / "production-model-providers.json"
    generator = (
        project_root
        / "scripts"
        / "production"
        / "production_model_providers.py"
    )
    subprocess.run(
        [
            sys.executable,
            str(generator),
            "sync-development",
            "--config",
            str(config),
            "--output",
            str(config),
            "--snapshot-output",
            str(snapshot),
            "--source-provider",
            source_provider,
        ],
        check=True,
    )


def prepare_development_config(project_root: Path) -> list[Path]:
    """Seed a configured development directory without overwriting local state."""
    configured = _configured_directory()
    if not configured:
        return []

    project_root = Path(project_root).resolve()
    defaults = project_root / "config"
    target = Path(configured).expanduser()
    if not target.is_absolute():
        target = project_root / target
    target = target.resolve()
    os.environ["DETERMINFLOW_CONFIG_DIR"] = str(target)

    if target == defaults or not defaults.is_dir():
        return []

    created: list[Path] = []
    for source in sorted(defaults.rglob("*")):
        if not source.is_file():
            continue
        destination = target / source.relative_to(defaults)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        created.append(destination)
    _sync_model_provider_catalog(project_root, target)
    return created
