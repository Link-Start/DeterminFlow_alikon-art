from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core import default_resources
from src.core.default_resources import provision_core_skills
from src.skills.storage import (
    CORE_RESOURCE_MARKER,
    SkillStorageLayout,
    migrate_legacy_skill_layout,
)


def _write_skill(root: Path, skill_id: str, content: str) -> Path:
    skill_file = root / skill_id / "SKILL.md"
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def test_migration_separates_flat_skills_by_lifecycle(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    skills_root = tmp_path / "data" / "skills"
    core_content = "---\nname: core-guide\ndescription: Core\n---\n"
    _write_skill(bundled, "core-guide", core_content)
    _write_skill(skills_root, "core-guide", core_content)
    _write_skill(skills_root, "local-guide", "local")
    _write_skill(skills_root, "market-guide", "market")
    (skills_root / CORE_RESOURCE_MARKER).write_text("{}", encoding="utf-8")
    provenance = skills_root.parent / "resource-provenance.json"
    provenance.write_text(
        json.dumps({
            "schema_version": 1,
            "resources": {
                "skill:market-guide": {
                    "resource_type": "skill",
                    "local_id": "market-guide",
                    "source": {"kind": "marketplace"},
                    "package": {},
                    "installed_at": None,
                }
            },
        }),
        encoding="utf-8",
    )

    layout = SkillStorageLayout.from_root(skills_root)
    report = migrate_legacy_skill_layout(layout, bundled_skills=bundled)

    assert report.moved_builtin == ("core-guide",)
    assert report.moved_local == ("local-guide",)
    assert report.moved_marketplace == ("market-guide",)
    assert report.backed_up == ()
    assert (layout.builtin / "core-guide" / "SKILL.md").is_file()
    assert (layout.local / "local-guide" / "SKILL.md").is_file()
    assert (layout.marketplace / "market-guide" / "SKILL.md").is_file()
    assert report.backup_directory is not None
    assert (report.backup_directory / CORE_RESOURCE_MARKER).is_file()


def test_migration_backs_up_divergent_core_before_provisioning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = tmp_path / "defaults"
    bundled = defaults / "skills"
    skills_root = tmp_path / "data" / "skills"
    _write_skill(bundled, "workflow-guide", "current bundled content")
    _write_skill(skills_root, "workflow-guide", "legacy customized content")
    monkeypatch.setattr(default_resources, "DEFAULT_RESOURCES_DIR", defaults)

    layout = SkillStorageLayout.from_root(skills_root)
    report = migrate_legacy_skill_layout(layout, bundled_skills=bundled)
    provision_core_skills(layout.builtin)

    assert report.backed_up == ("workflow-guide",)
    assert report.backup_directory is not None
    assert (
        report.backup_directory / "workflow-guide" / "SKILL.md"
    ).read_text(encoding="utf-8") == "legacy customized content"
    assert (layout.builtin / "workflow-guide" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "current bundled content"


def test_migration_fails_closed_when_target_already_exists(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    skills_root = tmp_path / "data" / "skills"
    _write_skill(skills_root, "local-guide", "legacy")
    layout = SkillStorageLayout.from_root(skills_root)
    _write_skill(layout.local, "local-guide", "existing")

    with pytest.raises(FileExistsError, match="避免覆盖"):
        migrate_legacy_skill_layout(layout, bundled_skills=bundled)

    assert (skills_root / "local-guide" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "legacy"
    assert (layout.local / "local-guide" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == "existing"
