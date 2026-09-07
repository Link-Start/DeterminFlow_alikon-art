from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from marketplace_fixtures import FakeMarketplace, SKILL_TEXT, _empty_manager, _manager, _service
from src.skill_marketplace.ownership import compare_semver, is_newer_semver
from src.skill_marketplace.routes import router
from src.skill_marketplace.service import LocalSkillError
from test_marketplace_installation import _pin

NEWER_TEXT = SKILL_TEXT.replace("1.2.3", "1.2.4")
NEWER_VERSION_ID = "44444444-4444-4444-8444-444444444444"
OLDER_TEXT = SKILL_TEXT.replace("1.2.3", "1.2.2")
OTHER_PUBLISHER = "pub_aaaaaaaaaaaaaaaaaaaaaaaa"


def _publish_remote(
    marketplace: FakeMarketplace,
    *,
    version: str = "1.2.4",
    version_id: str = NEWER_VERSION_ID,
    publisher_id: str | None = None,
    resource_id: str | None = None,
    text: str | None = None,
) -> dict[str, str]:
    marketplace.content = (
        text if text is not None else SKILL_TEXT.replace("1.2.3", version)
    ).encode()

    async def get_skill(slug: str) -> dict:
        detail = await FakeMarketplace.get_skill(marketplace, slug)
        detail["version"] = version
        detail["version_id"] = version_id
        if publisher_id is not None:
            detail["publisher_id"] = publisher_id
        if resource_id is not None:
            detail["resource_id"] = resource_id
        return detail

    marketplace.get_skill = get_skill  # type: ignore[method-assign]
    return {
        "expected_version_id": version_id,
        "expected_sha256": hashlib.sha256(marketplace.content).hexdigest(),
    }


def test_semver_comparison_is_fail_closed_and_ignores_build_metadata() -> None:
    assert is_newer_semver("1.2.4", "1.2.3") is True
    assert is_newer_semver("1.2.3", "1.2.3") is False
    assert is_newer_semver("1.2.2", "1.2.3") is False
    assert is_newer_semver("1.2.3", "1.2.3-alpha") is True
    assert is_newer_semver("1.2.3-alpha", "1.2.3") is False
    assert is_newer_semver("1.0.0-alpha.2", "1.0.0-alpha.1") is True
    assert is_newer_semver("1.2.3+build.2", "1.2.3+build.1") is False
    assert compare_semver("not-a-version", "1.0.0") is None
    assert is_newer_semver("latest", "1.0.0") is False


def test_installed_state_reports_update_available_for_newer_remote(tmp_path: Path) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    asyncio.run(service.install("shared-skill", **_pin(service)))
    before = asyncio.run(service.get_skill("shared-skill"))
    assert before["installation"] == {
        "status": "installed",
        "version": "1.2.3",
        "enabled": True,
        "update_available": False,
    }
    _publish_remote(service.marketplace)
    detail = asyncio.run(service.get_skill("shared-skill"))
    catalog = asyncio.run(service.list_skill_page())
    assert detail["installation"] == {
        "status": "installed",
        "version": "1.2.3",
        "enabled": True,
        "update_available": True,
    }
    assert catalog["items"][0]["installation"] == detail["installation"]
    available = asyncio.run(
        _service(tmp_path / "other", manager=_empty_manager(tmp_path / "other")).get_skill(
            "shared-skill"
        )
    )["installation"]
    assert available["status"] == "available"
    assert "update_available" not in available


def test_update_replaces_skill_and_preserves_settings_and_provenance(
    tmp_path: Path,
) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    asyncio.run(service.install("shared-skill", **_pin(service)))
    config = manager.config_manager
    assert config is not None
    config.set_enabled("shared-skill", False)
    config.set_auto_inject("shared-skill", False)
    config.set_scope_override("shared-skill", "workflow")
    config.set_priority("shared-skill", 80)
    config.create_group({"id": "writing", "name": "写作"})
    config.set_skill_group_ids("shared-skill", ["writing"])
    previous = manager.provenance_store.get("skill", "shared-skill")
    assert previous is not None
    pin = _publish_remote(service.marketplace)

    result = asyncio.run(service.update("shared-skill", **pin))

    assert result["installed"] is True
    assert result["updated"] is True
    assert result["skill_id"] == "shared-skill"
    assert result["version"] == "1.2.4"
    assert result["sha256"] == pin["expected_sha256"]
    assert result["enabled"] is False
    assert result["installation"] == {
        "status": "installed",
        "version": "1.2.4",
        "enabled": False,
        "update_available": False,
    }
    assert (
        tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    ).read_text(encoding="utf-8") == NEWER_TEXT
    provenance = result["provenance"]
    assert provenance["installed_at"] == previous["installed_at"]
    assert provenance["source"]["registry"] == previous["source"]["registry"]
    assert provenance["source"]["resource_id"] == previous["source"]["resource_id"]
    assert provenance["source"]["publisher_id"] == previous["source"]["publisher_id"]
    assert provenance["source"]["version_id"] == NEWER_VERSION_ID
    assert provenance["package"] == {
        "version": "1.2.4",
        "sha256": pin["expected_sha256"],
        "license": "MIT",
    }
    assert config.get_enabled("shared-skill") is False
    assert config.should_auto_inject("shared-skill") is False
    assert config.get_scope_override("shared-skill") == "workflow"
    assert config.get_priority("shared-skill") == 80
    assert config.get_skill_group_ids("shared-skill") == ["writing"]
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.install("shared-skill", **pin))
    assert error.value.code == "already_exists"


def test_update_refuses_same_or_older_version_without_downloading(tmp_path: Path) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    asyncio.run(service.install("shared-skill", **_pin(service)))
    marketplace = service.marketplace
    assert marketplace is not None
    original_bytes = (
        tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    ).read_bytes()

    with pytest.raises(LocalSkillError) as same:
        asyncio.run(service.update("shared-skill", **_pin(service)))
    assert same.value.code == "no_update"
    assert same.value.status_code == 409

    pin = _publish_remote(marketplace, version="1.2.2", text=OLDER_TEXT)
    with pytest.raises(LocalSkillError) as older:
        asyncio.run(service.update("shared-skill", **pin))
    assert older.value.code == "no_update"
    assert marketplace.download_calls == ["shared-skill"]
    assert (
        tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    ).read_bytes() == original_bytes


def test_update_refuses_identity_and_digest_changes(tmp_path: Path) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    asyncio.run(service.install("shared-skill", **_pin(service)))
    marketplace = service.marketplace
    assert marketplace is not None
    original = (
        tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    ).read_text(encoding="utf-8")
    stale = _pin(service)

    resource_pin = _publish_remote(marketplace, resource_id="other-resource")
    with pytest.raises(LocalSkillError) as resource_error:
        asyncio.run(service.update("shared-skill", **resource_pin))
    assert resource_error.value.code == "conflict"

    original_url = marketplace.base_url
    marketplace.base_url = "https://another-marketplace.example"
    registry_pin = _publish_remote(marketplace)
    with pytest.raises(LocalSkillError) as registry_error:
        asyncio.run(service.update("shared-skill", **registry_pin))
    assert registry_error.value.code == "conflict"
    marketplace.base_url = original_url

    publisher_pin = _publish_remote(marketplace, publisher_id=OTHER_PUBLISHER)
    with pytest.raises(LocalSkillError) as publisher_error:
        asyncio.run(service.update("shared-skill", **publisher_pin))
    assert publisher_error.value.code == "identity_mismatch"

    _publish_remote(marketplace)
    with pytest.raises(LocalSkillError) as digest_error:
        asyncio.run(service.update("shared-skill", **stale))
    assert digest_error.value.code == "version_changed"
    assert digest_error.value.status_code == 409
    assert marketplace.download_calls == ["shared-skill"]
    assert (
        tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    ).read_text(encoding="utf-8") == original


def test_update_refuses_locally_modified_original_bytes(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    asyncio.run(service.install("shared-skill", **_pin(service)))
    skill_path = tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    manager.reload()
    pin = _publish_remote(service.marketplace)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.update("shared-skill", **pin))
    assert error.value.code == "local_modified"
    assert service.marketplace.download_calls == ["shared-skill"]
    assert "changed" in skill_path.read_text(encoding="utf-8")

    skill_path.write_text(SKILL_TEXT, encoding="utf-8")
    (skill_path.parent / "notes.txt").write_text("extra", encoding="utf-8")
    manager.reload()
    with pytest.raises(LocalSkillError) as extra:
        asyncio.run(service.update("shared-skill", **pin))
    assert extra.value.code == "local_modified"


def test_update_rolls_back_file_and_provenance_on_failure(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    asyncio.run(service.install("shared-skill", **_pin(service)))
    skill_path = tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    previous_bytes = skill_path.read_bytes()
    previous_provenance = manager.provenance_store.get("skill", "shared-skill")
    pin = _publish_remote(service.marketplace)

    def fail_reload() -> None:
        raise OSError("reload exploded")

    manager.reload = fail_reload  # type: ignore[method-assign]
    with pytest.raises(OSError, match="reload exploded"):
        asyncio.run(service.update("shared-skill", **pin))
    assert skill_path.read_bytes() == previous_bytes
    assert manager.provenance_store.get("skill", "shared-skill") == previous_provenance


def test_update_rolls_back_file_when_provenance_write_fails(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    asyncio.run(service.install("shared-skill", **_pin(service)))
    skill_path = tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    previous_bytes = skill_path.read_bytes()
    previous_provenance = manager.provenance_store.get("skill", "shared-skill")
    pin = _publish_remote(service.marketplace)

    def fail_record(*_args, **_kwargs):
        raise OSError("provenance failed")

    manager.provenance_store.record = fail_record  # type: ignore[method-assign]
    with pytest.raises(OSError, match="provenance failed"):
        asyncio.run(service.update("shared-skill", **pin))
    assert skill_path.read_bytes() == previous_bytes
    assert manager.provenance_store.get("skill", "shared-skill") == previous_provenance


def test_update_refuses_builtin_local_and_missing_installs(tmp_path: Path) -> None:
    builtin_root = tmp_path / "builtin"
    builtin_dir = builtin_root / "skills" / "builtin" / "shared-skill"
    builtin_dir.mkdir(parents=True)
    (builtin_dir / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
    builtin_service = _service(builtin_root, manager=_empty_manager(builtin_root))
    with pytest.raises(LocalSkillError) as builtin_error:
        asyncio.run(builtin_service.update("shared-skill", **_pin(builtin_service)))
    assert builtin_error.value.code == "conflict"

    local_service = _service(tmp_path / "local", manager=_manager(tmp_path / "local"))
    with pytest.raises(LocalSkillError) as local_error:
        asyncio.run(local_service.update("shared-skill", **_pin(local_service)))
    assert local_error.value.code == "conflict"

    missing = _service(tmp_path / "missing", manager=_empty_manager(tmp_path / "missing"))
    with pytest.raises(LocalSkillError) as missing_error:
        asyncio.run(missing.update("shared-skill", **_pin(missing)))
    assert missing_error.value.code == "not_found"
    assert missing_error.value.status_code == 404


def test_update_validates_downloaded_version_and_refuses_symlinks(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    asyncio.run(service.install("shared-skill", **_pin(service)))
    mismatched = _publish_remote(service.marketplace, text=SKILL_TEXT)
    with pytest.raises(LocalSkillError) as version_error:
        asyncio.run(service.update("shared-skill", **mismatched))
    assert version_error.value.code == "identity_mismatch"

    skill_path = tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(skill_path.read_bytes())
    skill_path.unlink()
    skill_path.symlink_to(outside)
    pin = _publish_remote(service.marketplace)
    with pytest.raises(LocalSkillError) as symlink_error:
        asyncio.run(service.update("shared-skill", **pin))
    assert symlink_error.value.code == "conflict"


def test_update_route_reuses_install_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    asyncio.run(service.install("shared-skill", **_pin(service)))
    pin = _publish_remote(service.marketplace)
    app = FastAPI()
    app.state.resource_marketplace_service = service
    app.include_router(router)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        endpoint = "/api/resource-marketplace/skills/shared-skill/update"
        assert client.post(endpoint).status_code == 422
        stale = {**pin, "expected_version_id": "outdated-version"}
        changed = client.post(endpoint, json=stale)
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "version_changed"
        response = client.post(endpoint, json=pin)
        assert response.status_code == 200
        body = response.json()
        assert body["installed"] is True
        assert body["updated"] is True
        assert body["version"] == "1.2.4"
        assert body["installation"]["update_available"] is False


@pytest.mark.parametrize("mutation", ["content", "provenance", "symlink"])
def test_update_rechecks_local_state_after_download(tmp_path: Path, mutation: str) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    asyncio.run(service.install("shared-skill", **_pin(service)))
    manager = service.skill_manager
    path = manager.marketplace_skills_dir / "shared-skill" / "SKILL.md"
    before = path.read_bytes()
    provenance = manager.provenance_store.get("skill", "shared-skill")
    pin = _publish_remote(service.marketplace)
    download = service.marketplace.download_skill
    outside = tmp_path / "outside.md"
    outside.write_bytes(before)

    async def changed_during_download(slug: str):
        result = await download(slug)
        if mutation == "content":
            path.write_bytes(before + b"\nlocal edit during download\n")
        elif mutation == "symlink":
            path.unlink()
            path.symlink_to(outside)
        else:
            manager.provenance_store.record("skill", slug, source={**provenance["source"], "resource_id": "changed"}, package=provenance["package"])
        return result

    service.marketplace.download_skill = changed_during_download
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.update("shared-skill", **pin))
    assert error.value.code in {"local_modified", "conflict"}
    assert outside.read_bytes() == before
    assert path.read_bytes() == (before + b"\nlocal edit during download\n" if mutation == "content" else before)


def test_update_does_not_remove_unknown_temporary_files(tmp_path: Path) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    asyncio.run(service.install("shared-skill", **_pin(service)))
    root = service.skill_manager.marketplace_skills_dir / "shared-skill"
    outside = tmp_path / "unrelated.txt"
    outside.write_text("keep this")
    temporary = root / ".marketplace-SKILL.md.tmp"
    temporary.symlink_to(outside)
    pin = _publish_remote(service.marketplace)
    with pytest.raises(LocalSkillError):
        asyncio.run(service.update("shared-skill", **pin))
    assert temporary.is_symlink()
    assert outside.read_text() == "keep this"


def test_update_restores_runtime_after_reload_partially_succeeds(tmp_path: Path) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    manager = service.skill_manager
    asyncio.run(service.install("shared-skill", **_pin(service)))
    pin = _publish_remote(service.marketplace)
    reload = manager.reload
    attempts = 0

    def fail_once_after_reload():
        nonlocal attempts
        attempts += 1
        reload()
        if attempts == 1:
            raise OSError("post-load failure")

    manager.reload = fail_once_after_reload
    with pytest.raises(OSError, match="post-load failure"):
        asyncio.run(service.update("shared-skill", **pin))
    assert manager.get_skill("shared-skill").version == "1.2.3"
    assert manager.provenance_store.get("skill", "shared-skill")["package"]["version"] == "1.2.3"


def test_semver_rejects_numeric_prerelease_leading_zero() -> None:
    assert compare_semver("1.0.0-01", "1.0.0-alpha") is None
