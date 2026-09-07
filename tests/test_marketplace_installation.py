from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.skill_marketplace.routes import router
from src.skill_marketplace.service import LocalSkillError, SkillMarketplaceService
from marketplace_fixtures import FakeMarketplace, SKILL_TEXT, _empty_manager, _service


def _pin(service: SkillMarketplaceService) -> dict[str, str]:
    detail = asyncio.run(service.marketplace.get_skill("shared-skill"))
    return {
        "expected_version_id": detail.get("resource", {}).get("version_id") or detail["version_id"],
        "expected_sha256": detail.get("payload", {}).get("sha256") or detail["sha256"],
    }


@pytest.mark.parametrize("changed", ["version_id", "sha256"])
def test_install_rejects_a_changed_confirmation_without_downloading(tmp_path: Path, changed: str) -> None:
    class ChangedMarketplace(FakeMarketplace):
        downloaded = False

        async def download_skill(self, slug: str):
            self.downloaded = True
            return await super().download_skill(slug)

    marketplace = ChangedMarketplace()
    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=marketplace)
    pin = _pin(service)
    pin[f"expected_{changed}"] = "new-version" if changed == "version_id" else "f" * 64
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.install("shared-skill", **pin))
    assert error.value.code == "version_changed"
    assert error.value.status_code == 409
    assert marketplace.downloaded is False
    assert service.skill_manager.get_skill("shared-skill") is None


def test_download_race_never_installs_unconfirmed_bytes(tmp_path: Path) -> None:
    class ChangedDownload(FakeMarketplace):
        async def download_skill(self, slug: str):
            self.content = SKILL_TEXT.replace("1.2.3", "1.2.4").encode()
            return await super().download_skill(slug)

    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=ChangedDownload())
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.install("shared-skill", **_pin(service)))
    assert error.value.code == "integrity_mismatch"
    assert not (tmp_path / "skills/marketplace/shared-skill").exists()


def test_local_install_route_requires_and_checks_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    app = FastAPI()
    app.state.resource_marketplace_service = service
    app.include_router(router)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        endpoint = "/api/resource-marketplace/skills/shared-skill/install"
        assert client.post(endpoint).status_code == 422
        assert client.post(endpoint, json={"expected_version_id": "v"}).status_code == 422
        stale = {**_pin(service), "expected_version_id": "outdated-version"}
        response = client.post(endpoint, json=stale)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "version_changed"
        response = client.post(endpoint, json=_pin(service))
        assert response.status_code == 200
        assert response.json()["installation"] == {
            "status": "installed",
            "version": "1.2.3",
            "enabled": True,
            "update_available": False,
        }


def test_catalog_and_detail_report_local_installation_without_trusting_remote_state(tmp_path: Path) -> None:
    class ListedMarketplace(FakeMarketplace):
        async def get_skill(self, slug: str):
            detail = await super().get_skill(slug)
            detail["installation"] = {"status": "builtin", "version": "fake", "enabled": True}
            return detail

        async def list_skills(self, **kwargs):
            return {"items": [await self.get_skill("shared-skill")], "query": kwargs["query"]}

    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=ListedMarketplace())
    before = asyncio.run(service.get_skill("shared-skill"))
    assert before["installation"] == {"status": "available", "version": None, "enabled": None}
    asyncio.run(service.install("shared-skill", **_pin(service)))
    detail = asyncio.run(service.get_skill("shared-skill"))
    catalog = asyncio.run(service.list_skills())
    assert catalog["items"][0]["installation"] == detail["installation"]
    assert detail["installation"] == {
        "status": "installed",
        "version": "1.2.3",
        "enabled": True,
        "update_available": False,
    }
    assert "registry" not in detail["installation"]


@pytest.mark.parametrize("source, expected", [("builtin", "builtin"), ("local", "conflict"), ("marketplace", "conflict")])
def test_same_named_local_resources_are_classified_from_ownership(tmp_path: Path, source: str, expected: str) -> None:
    directory = tmp_path / "skills" / source / "shared-skill"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(SKILL_TEXT)
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    detail = asyncio.run(service.get_skill("shared-skill"))
    assert detail["installation"]["status"] == expected
    assert detail["installation"]["version"] == "1.2.3"


def test_matching_slug_from_another_registry_is_a_conflict(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    asyncio.run(service.install("shared-skill", **_pin(service)))
    other = FakeMarketplace()
    other.base_url = "https://another-marketplace.example"
    service.marketplace = other
    assert asyncio.run(service.get_skill("shared-skill"))["installation"]["status"] == "conflict"


def test_concurrent_installations_have_one_winner(tmp_path: Path) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    pin = _pin(service)

    async def install_twice():
        return await asyncio.gather(
            service.install("shared-skill", **pin),
            service.install("shared-skill", **pin),
            return_exceptions=True,
        )

    results = asyncio.run(install_twice())
    assert sum(isinstance(result, dict) for result in results) == 1
    errors = [result for result in results if isinstance(result, LocalSkillError)]
    assert len(errors) == 1 and errors[0].code == "already_exists"


def test_install_is_atomic_enabled_and_ready_for_auto_injection(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    result = asyncio.run(service.install("shared-skill", **_pin(service)))

    assert result["installed"] is True
    assert result["enabled"] is True
    assert (tmp_path / "skills" / "marketplace" / "shared-skill" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == SKILL_TEXT
    installed = manager.get_skill("shared-skill")
    assert installed is not None
    assert installed.enabled is True
    assert manager.config_manager is not None
    assert manager.config_manager.should_auto_inject("shared-skill") is True
    assert result["provenance"] == {
        "resource_type": "skill",
        "local_id": "shared-skill",
        "source": {
            "kind": "marketplace",
            "registry": "https://marketplace.example",
            "resource_id": "22222222-2222-4222-8222-222222222222",
            "version_id": "33333333-3333-4333-8333-333333333333",
            "publisher_id": "pub_0123456789abcdef01234567",
            "resource_type": "skill",
            "functional_category": "general",
        },
        "package": {
            "version": "1.2.3",
            "sha256": hashlib.sha256(SKILL_TEXT.encode()).hexdigest(),
            "license": "MIT",
        },
        "installed_at": result["provenance"]["installed_at"],
    }
    assert installed.metadata["local_modified"] is False
    with pytest.raises(LocalSkillError, match="不能作为作者原稿"):
        service._read_shareable_skill("shared-skill")
    assert not list((tmp_path / "skills" / "marketplace").glob(".marketplace-*"))


def test_install_accepts_opaque_marketplace_resource_ids(tmp_path: Path) -> None:
    class OpaqueIdMarketplace(FakeMarketplace):
        async def get_skill(self, slug: str) -> dict:
            detail = await super().get_skill(slug)
            detail["resource_id"] = "local-resource-shared-skill"
            detail["version_id"] = "local-version-shared-skill-1-2-3"
            return detail

    manager = _empty_manager(tmp_path)
    service = _service(
        tmp_path,
        manager=manager,
        marketplace=OpaqueIdMarketplace(),
    )

    result = asyncio.run(service.install("shared-skill", **_pin(service)))

    assert result["provenance"]["source"]["resource_id"] == (
        "local-resource-shared-skill"
    )
    assert result["provenance"]["source"]["version_id"] == (
        "local-version-shared-skill-1-2-3"
    )


def test_install_accepts_canonical_resource_envelope(tmp_path: Path) -> None:
    class EnvelopeMarketplace(FakeMarketplace):
        async def get_skill(self, slug: str) -> dict:
            digest = hashlib.sha256(self.content).hexdigest()
            return {
                "resource": {
                    "id": "resource-envelope",
                    "version_id": "version-envelope",
                    "resource_type": "skill",
                    "functional_category": "novel",
                    "author": {
                        "id": "pub_0123456789abcdef01234567",
                        "name": "北辰",
                    },
                    "release": {"version": "1.2.3", "license": "MIT"},
                },
                "payload": {
                    "type": "skill",
                    "name": slug,
                    "sha256": digest,
                },
            }

    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager, marketplace=EnvelopeMarketplace())

    result = asyncio.run(service.install("shared-skill", **_pin(service)))

    assert result["version"] == "1.2.3"
    assert result["provenance"]["source"]["functional_category"] == "novel"
    assert result["provenance"]["source"]["resource_id"] == "resource-envelope"


def test_install_rejects_missing_marketplace_provenance(tmp_path: Path) -> None:
    class MissingProvenanceMarketplace(FakeMarketplace):
        async def get_skill(self, slug: str) -> dict:
            detail = await super().get_skill(slug)
            detail.pop("publisher_id")
            return detail

    manager = _empty_manager(tmp_path)
    service = _service(
        tmp_path,
        manager=manager,
        marketplace=MissingProvenanceMarketplace(),
    )

    with pytest.raises(LocalSkillError, match="发布者标识"):
        asyncio.run(service.install("shared-skill", **_pin(service)))
    assert not (tmp_path / "skills" / "marketplace" / "shared-skill").exists()
    assert manager.get_skill("shared-skill") is None


def test_install_rejects_hash_or_local_name_conflicts(tmp_path: Path) -> None:
    class BadHashMarketplace(FakeMarketplace):
        async def get_skill(self, slug: str) -> dict:
            detail = await super().get_skill(slug)
            detail["sha256"] = "0" * 64
            return detail

    empty_manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=empty_manager, marketplace=BadHashMarketplace())
    with pytest.raises(LocalSkillError, match="完整性"):
        asyncio.run(service.install("shared-skill", **_pin(service)))
    assert not (tmp_path / "skills" / "marketplace" / "shared-skill").exists()

    existing_root = tmp_path / "existing"
    existing_service = _service(existing_root)
    with pytest.raises(LocalSkillError, match="同名"):
        asyncio.run(existing_service.install("shared-skill", **_pin(existing_service)))


def test_install_persists_enabled_state_before_reload_and_receipt_matches(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    config = manager.config_manager
    assert config is not None
    calls: list[str] = []
    original_set_enabled = config.set_enabled
    original_set_auto_inject = config.set_auto_inject
    original_reload = manager.reload

    def persist_enabled(skill_id: str, enabled: bool) -> bool:
        calls.append(f"enabled:{enabled}")
        return original_set_enabled(skill_id, enabled)

    def persist_auto_inject(skill_id: str, value: bool) -> bool:
        calls.append(f"auto_inject:{value}")
        return original_set_auto_inject(skill_id, value)

    def reload() -> None:
        calls.append("reload")
        original_reload()

    config.set_enabled = persist_enabled  # type: ignore[method-assign]
    config.set_auto_inject = persist_auto_inject  # type: ignore[method-assign]
    manager.reload = reload  # type: ignore[method-assign]

    result = asyncio.run(service.install("shared-skill", **_pin(service)))
    assert calls[:3] == ["enabled:True", "auto_inject:True", "reload"]
    assert result["enabled"] is True
    assert result["installation"]["enabled"] is True
    assert manager.get_skill("shared-skill") is not None
    assert manager.get_skill("shared-skill").enabled is True
    assert config.should_auto_inject("shared-skill") is True


def test_install_cleans_up_when_enabled_persist_fails(tmp_path: Path) -> None:
    manager = _empty_manager(tmp_path)
    service = _service(tmp_path, manager=manager)
    config = manager.config_manager
    assert config is not None
    config.set_enabled = lambda skill_id, enabled: False  # type: ignore[method-assign]

    with pytest.raises(OSError, match="enabled"):
        asyncio.run(service.install("shared-skill", **_pin(service)))
    assert not (tmp_path / "skills" / "marketplace" / "shared-skill").exists()
    assert manager.get_skill("shared-skill") is None
    assert "shared-skill" not in json.loads(
        (tmp_path / "config" / "skills.json").read_text(encoding="utf-8")
    ).get("skill_configs", {})
