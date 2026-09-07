from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from src.resources import ResourceProvenanceStore
from src.skills.config_manager import SkillConfigManager
from src.skills.loader import SkillLoader, SkillResourceConflictError
from src.skills.manager import SkillManager


def _write_skill(root: Path, skill_id: str, frontmatter: dict, body: str = "# Body") -> Path:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True)
    content = f"---\n{yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)}---\n\n{body}\n"
    path = skill_dir / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_local_manifest_accepts_optional_and_custom_metadata(tmp_path: Path) -> None:
    _write_skill(
        tmp_path,
        "local-helper",
        {
            "name": "local-helper",
            "description": "A local helper",
            "x-vendor": "kept",
            "metadata": {
                "category": "novel-writing",
                "custom": {"level": 2},
                "determinflow.scope": "workflow",
            },
        },
    )

    skill = SkillLoader(tmp_path).load_all()[0]

    assert skill.version == ""
    assert skill.author == ""
    assert skill.category == "novel-writing"
    assert skill.scope == "workflow"
    assert skill.frontmatter_extra == {"x-vendor": "kept"}
    assert skill.manifest_metadata["custom"] == {"level": 2}
    assert skill.validation_warnings == []


def test_save_keeps_content_metadata_and_removes_runtime_settings(tmp_path: Path) -> None:
    skill_path = _write_skill(
        tmp_path,
        "portable-helper",
        {
            "name": "portable-helper",
            "description": "Portable metadata",
            "x-vendor": "kept",
            "metadata": {
                "version": "1.2.3",
                "author": "Author",
                "priority": 80,
                "workflow_only": True,
                "agent_types": ["coder"],
                "custom": "kept",
                "category": "coding",
                "marketplace": {"release_notes": "legacy"},
                "determinflow.requires_core": ">=1.0",
                "determinflow.requires_tools": "search,files",
                "determinflow.requires_plugins": ["writer"],
                "determinflow.requires_apps": ["browser"],
            },
        },
    )
    loader = SkillLoader(tmp_path)
    skill = loader.load_all()[0]

    assert loader.save_skill(skill) is True
    frontmatter, _body = loader._parse_skill_md(skill_path.read_text(encoding="utf-8"))

    assert frontmatter["x-vendor"] == "kept"
    assert frontmatter["metadata"]["custom"] == "kept"
    assert frontmatter["metadata"]["determinflow.scope"] == "workflow"
    assert frontmatter["allowed-tools"] == "search files"
    assert frontmatter["compatibility"] == ">=1.0"
    assert frontmatter["metadata"]["determinflow.requires_plugins"] == ["writer"]
    assert frontmatter["metadata"]["determinflow.requires_apps"] == ["browser"]
    assert "priority" not in frontmatter["metadata"]
    assert "workflow_only" not in frontmatter["metadata"]
    assert "agent_types" not in frontmatter["metadata"]
    assert "category" not in frontmatter["metadata"]
    assert "marketplace" not in frontmatter["metadata"]
    assert "determinflow.requires_core" not in frontmatter["metadata"]
    assert "determinflow.requires_tools" not in frontmatter["metadata"]


def test_runtime_config_migrates_legacy_manifest_independent_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "skills.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "groups": [],
                "skills": {
                    "local-helper": {
                        "group_ids": ["default"],
                        "auto_inject": True,
                        "priority": 72,
                        "agent_types": ["coder"],
                    }
                },
                "skill_configs": {
                    "local-helper": {
                        "enabled": False,
                        "workflow_only": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    manager = SkillConfigManager(config_path)

    assert manager.sync_with_directory(["local-helper"]) is True
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    assert saved["skills"]["local-helper"] == {"group_ids": ["default"]}
    assert saved["skill_configs"]["local-helper"] == {
        "enabled": False,
        "auto_inject": True,
        "priority": 72,
        "agent_types": ["coder"],
        "scope_override": "workflow",
    }


def test_marketplace_provenance_detects_local_drift(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skills_dir = skills_root / "marketplace"
    skill_path = _write_skill(
        skills_dir,
        "installed-helper",
        {
            "name": "installed-helper",
            "description": "Installed helper",
            "metadata": {"version": "1.0.0"},
        },
    )
    digest = hashlib.sha256(skill_path.read_bytes()).hexdigest()
    store = ResourceProvenanceStore(tmp_path / "resource-provenance.json")
    store.record(
        "skill",
        "installed-helper",
        source={
            "kind": "marketplace",
            "registry": "https://determinflow.com",
            "resource_id": "22222222-2222-4222-8222-222222222222",
            "version_id": "33333333-3333-4333-8333-333333333333",
            "publisher_id": "pub_0123456789abcdef01234567",
        },
        package={"version": "1.0.0", "sha256": digest, "license": "MIT"},
    )
    manager = SkillManager(
        skills_root / "local",
        marketplace_skills_dir=skills_dir,
        provenance_path=tmp_path / "resource-provenance.json",
    )

    assert manager.get_skill("installed-helper").metadata["local_modified"] is False

    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nChanged\n", encoding="utf-8")
    manager.reload()

    installed = manager.get_skill("installed-helper")
    assert installed is not None
    assert installed.metadata["local_modified"] is True
    assert installed.metadata["provenance"]["source"]["publisher_id"].startswith("pub_")


def test_manager_loads_source_owned_roots_and_protects_managed_content(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    local_path = _write_skill(
        skills_root / "local",
        "local-helper",
        {"name": "local-helper", "description": "Local helper"},
    )
    core_path = _write_skill(
        skills_root / "builtin",
        "core-helper",
        {"name": "core-helper", "description": "Core helper"},
    )
    market_path = _write_skill(
        skills_root / "marketplace",
        "market-helper",
        {
            "name": "market-helper",
            "description": "Marketplace helper",
            "metadata": {"version": "1.0.0"},
        },
    )
    provenance_path = tmp_path / "resource-provenance.json"
    store = ResourceProvenanceStore(provenance_path)
    store.record(
        "skill",
        "market-helper",
        source={"kind": "marketplace", "registry": "https://determinflow.com"},
        package={
            "version": "1.0.0",
            "sha256": hashlib.sha256(market_path.read_bytes()).hexdigest(),
        },
    )
    store.record(
        "skill",
        "local-helper",
        source={"kind": "marketplace", "registry": "https://stale.example"},
        package={"version": "0.9.0", "sha256": "0" * 64},
    )

    manager = SkillManager(
        skills_root / "local",
        builtin_skills_dir=skills_root / "builtin",
        marketplace_skills_dir=skills_root / "marketplace",
        provenance_path=provenance_path,
    )

    assert manager.get_skill("local-helper").metadata["provenance"]["source"] == {
        "kind": "local"
    }
    assert manager.get_skill("core-helper").metadata["provenance"]["source"] == {
        "kind": "core"
    }
    assert manager.get_skill("market-helper").metadata["provenance"]["source"] == {
        "kind": "marketplace",
        "registry": "https://determinflow.com",
    }
    assert manager.get_skill("local-helper").metadata["resource_read_only"] is False
    assert manager.get_skill("core-helper").metadata["resource_read_only"] is True
    assert manager.get_skill("market-helper").metadata["resource_read_only"] is True

    with pytest.raises(PermissionError, match="只读"):
        manager.update_skill("core-helper", {"content": "changed"})
    with pytest.raises(PermissionError, match="只读"):
        manager.update_skill("market-helper", {"content": "changed"})

    assert manager.delete_skill("market-helper") is True
    assert local_path.is_file()
    assert core_path.is_file()
    assert not market_path.parent.exists()
    assert ResourceProvenanceStore(provenance_path).get(
        "skill", "market-helper"
    ) is None


def test_marketplace_uninstall_clears_source_and_config_without_touching_others(
    tmp_path: Path,
) -> None:
    skills_root = tmp_path / "skills"
    config_path = tmp_path / "skills.json"
    market_dir = skills_root / "marketplace"
    local_path = _write_skill(
        skills_root / "local",
        "local-helper",
        {"name": "local-helper", "description": "Local helper"},
    )
    keep_path = _write_skill(
        market_dir,
        "keep-helper",
        {"name": "keep-helper", "description": "Keep me", "metadata": {"version": "1.0.0"}},
    )
    remove_path = _write_skill(
        market_dir,
        "remove-helper",
        {"name": "remove-helper", "description": "Remove me", "metadata": {"version": "2.0.0"}},
    )
    keep_bytes = keep_path.read_bytes()
    local_bytes = local_path.read_bytes()
    provenance_path = tmp_path / "resource-provenance.json"
    store = ResourceProvenanceStore(provenance_path)
    store.record(
        "skill",
        "keep-helper",
        source={"kind": "marketplace", "registry": "https://determinflow.com"},
        package={
            "version": "1.0.0",
            "sha256": hashlib.sha256(keep_bytes).hexdigest(),
            "license": "MIT",
        },
    )
    store.record(
        "skill",
        "remove-helper",
        source={"kind": "marketplace", "registry": "https://determinflow.com"},
        package={
            "version": "2.0.0",
            "sha256": hashlib.sha256(remove_path.read_bytes()).hexdigest(),
            "license": "Apache-2.0",
        },
    )
    config = SkillConfigManager(config_path)
    config.set_enabled("keep-helper", False)
    config.set_auto_inject("keep-helper", False)
    config.set_enabled("remove-helper", True)
    config.set_auto_inject("remove-helper", True)
    config.set_skill_group_ids("remove-helper", ["default"])
    manager = SkillManager(
        skills_root / "local",
        config_manager=config,
        marketplace_skills_dir=market_dir,
        provenance_path=provenance_path,
    )

    assert manager.delete_skill("remove-helper") is True

    assert manager.get_skill("remove-helper") is None
    assert not remove_path.parent.exists()
    assert ResourceProvenanceStore(provenance_path).get("skill", "remove-helper") is None
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "remove-helper" not in saved.get("skills", {})
    assert "remove-helper" not in saved.get("skill_configs", {})

    kept = manager.get_skill("keep-helper")
    assert kept is not None
    assert kept.license == ""
    assert kept.metadata["provenance"]["package"]["license"] == "MIT"
    assert keep_path.read_bytes() == keep_bytes
    assert local_path.read_bytes() == local_bytes
    assert ResourceProvenanceStore(provenance_path).get("skill", "keep-helper") is not None
    assert saved["skill_configs"]["keep-helper"]["enabled"] is False
    assert manager.get_skill("local-helper") is not None


def test_source_owned_roots_reject_duplicate_skill_ids(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    metadata = {"name": "duplicate-helper", "description": "Duplicate"}
    _write_skill(skills_root / "local", "duplicate-helper", metadata)
    _write_skill(skills_root / "builtin", "duplicate-helper", metadata)

    with pytest.raises(SkillResourceConflictError, match="duplicate-helper"):
        SkillManager(
            skills_root / "local",
            builtin_skills_dir=skills_root / "builtin",
            marketplace_skills_dir=skills_root / "marketplace",
            provenance_path=tmp_path / "resource-provenance.json",
        )
