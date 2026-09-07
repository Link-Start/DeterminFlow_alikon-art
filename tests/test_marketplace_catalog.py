from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.skill_marketplace.portal import MarketplaceRequestError, ResourceMarketplaceClient
from src.skill_marketplace.routes import router
from src.skill_marketplace.service import LocalSkillError, SkillMarketplaceService
from marketplace_fixtures import (
    FakeAccount,
    FakeMarketplace,
    SKILL_TEXT,
    _empty_manager,
    _service,
)
from test_marketplace_installation import _pin


def _desktop_client(tmp_path: Path, service: SkillMarketplaceService, monkeypatch) -> TestClient:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    app = FastAPI()
    app.state.resource_marketplace_service = service
    app.include_router(router)
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_catalog_route_validates_query_without_reserving_a_skill_name(tmp_path: Path, monkeypatch) -> None:
    marketplace = FakeMarketplace()
    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=marketplace)
    with _desktop_client(tmp_path, service, monkeypatch) as client:
        ok = client.get("/api/resource-marketplace/catalog/skills?page=2&page_size=10")
        assert ok.status_code == 200
        body = ok.json()
        assert body["page"] == 2
        assert body["page_size"] == 10
        assert body["total"] == 1
        assert body["items"][0]["installation"]["status"] == "available"
        assert marketplace.page_calls[0]["access_token"] is None
        assert marketplace.page_calls[0]["favorites"] is False

        # The local route still treats "page" as an ordinary Skill slug.
        named_page = client.get("/api/resource-marketplace/skills/page")
        assert named_page.status_code == 200
        assert "total" not in named_page.json()

        assert client.get("/api/resource-marketplace/catalog/skills?page=0").status_code == 400
        assert client.get("/api/resource-marketplace/catalog/skills?page=100001").status_code == 400
        assert client.get("/api/resource-marketplace/catalog/skills?page_size=0").status_code == 400
        assert client.get("/api/resource-marketplace/catalog/skills?page_size=101").status_code == 400
        invalid = client.get("/api/resource-marketplace/catalog/skills?favorites=yes")
        assert invalid.status_code == 400
        assert invalid.json()["detail"]["code"] == "invalid_favorites"


def test_favorites_page_requires_current_account_and_stays_private(
    tmp_path: Path,
    monkeypatch,
) -> None:
    marketplace = FakeMarketplace()
    service = _service(
        tmp_path,
        manager=_empty_manager(tmp_path),
        marketplace=marketplace,
        account=FakeAccount("expired"),
    )
    signed_out = _service(
        tmp_path / "anon",
        manager=_empty_manager(tmp_path / "anon"),
        account=FakeAccount(),
    )
    with _desktop_client(tmp_path, signed_out, monkeypatch) as anon:
        denied = anon.get("/api/resource-marketplace/catalog/skills?favorites=true")
        assert denied.status_code == 401
        assert denied.json()["detail"]["code"] == "login_required"

    with _desktop_client(tmp_path, service, monkeypatch) as client:
        refreshed = client.get("/api/resource-marketplace/catalog/skills?favorites=true")
        assert refreshed.status_code == 200
        assert marketplace.page_calls[-1]["favorites"] is True
        assert marketplace.page_calls[-1]["access_token"] == "renewed"
        assert service.account_session.refresh_count == 1  # type: ignore[union-attr]

        public = client.get("/api/resource-marketplace/catalog/skills?favorites=false")
        assert public.status_code == 200
        assert marketplace.page_calls[-1]["favorites"] is False
        assert marketplace.page_calls[-1]["access_token"] is None


def test_catalog_page_annotates_local_installation(tmp_path: Path) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    before = asyncio.run(service.list_skill_page())
    assert before["items"][0]["installation"] == {
        "status": "available",
        "version": None,
        "enabled": None,
    }
    asyncio.run(service.install("shared-skill", **_pin(service)))
    page = asyncio.run(service.list_skill_page(page=1, page_size=24, favorites=False))
    assert page["items"][0]["installation"] == {
        "status": "installed",
        "version": "1.2.3",
        "enabled": True,
        "update_available": False,
    }


def test_preview_uses_pins_and_never_downloads(tmp_path: Path, monkeypatch) -> None:
    marketplace = FakeMarketplace()
    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=marketplace)
    pin = _pin(service)
    preview = asyncio.run(service.preview_skill("shared-skill", **pin))
    assert preview["content"] == SKILL_TEXT
    assert preview["version_id"] == pin["expected_version_id"]
    assert preview["sha256"] == pin["expected_sha256"]
    assert marketplace.download_calls == []
    assert marketplace.preview_calls == [
        {"slug": "shared-skill", **pin},
    ]

    with _desktop_client(tmp_path, service, monkeypatch) as client:
        response = client.get(
            "/api/resource-marketplace/skills/shared-skill/preview",
            params=pin,
        )
        assert response.status_code == 200
        assert response.json()["content"] == SKILL_TEXT
        assert "path" not in response.json()
        assert marketplace.download_calls == []


def test_preview_version_change_and_hash_mismatch_fail_closed(tmp_path: Path) -> None:
    marketplace = FakeMarketplace()
    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=marketplace)
    pin = _pin(service)
    with pytest.raises(MarketplaceRequestError) as changed:
        asyncio.run(
            service.preview_skill(
                "shared-skill",
                expected_version_id="outdated-version",
                expected_sha256=pin["expected_sha256"],
            )
        )
    assert changed.value.code == "version_changed"
    assert changed.value.status_code == 409
    assert marketplace.download_calls == []

    class StaleBody(FakeMarketplace):
        async def preview_skill(self, slug, **kwargs):
            self.preview_calls.append({"slug": slug, **kwargs})
            return {
                "content": self.content.decode("utf-8"),
                "version_id": "other-version",
                "sha256": kwargs["expected_sha256"],
            }

    stale = StaleBody()
    stale_service = _service(
        tmp_path / "stale",
        manager=_empty_manager(tmp_path / "stale"),
        marketplace=stale,
    )
    with pytest.raises(LocalSkillError) as stale_error:
        asyncio.run(stale_service.preview_skill("shared-skill", **_pin(stale_service)))
    assert stale_error.value.code == "version_changed"
    assert stale.download_calls == []

    class Tampered(FakeMarketplace):
        async def preview_skill(self, slug, **kwargs):
            self.preview_calls.append({"slug": slug, **kwargs})
            return {
                "content": SKILL_TEXT.replace("useful", "tampered"),
                "version_id": kwargs["expected_version_id"],
                "sha256": kwargs["expected_sha256"],
            }

    tampered = Tampered()
    broken = _service(tmp_path / "tamper", manager=_empty_manager(tmp_path / "tamper"), marketplace=tampered)
    with pytest.raises(LocalSkillError) as mismatch:
        asyncio.run(broken.preview_skill("shared-skill", **_pin(broken)))
    assert mismatch.value.code == "integrity_mismatch"
    assert tampered.download_calls == []


def test_preview_client_preserves_version_changed_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/resource-marketplace/skills/shared-skill/preview"
        assert request.url.params["expected_version_id"] == "version-1"
        assert request.headers.get("authorization") is None
        return httpx.Response(
            409,
            json={"detail": "资源版本已变化", "code": "version_changed"},
        )

    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="1.0.0",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(MarketplaceRequestError) as error:
        asyncio.run(
            marketplace.preview_skill(
                "shared-skill",
                expected_version_id="version-1",
                expected_sha256="a" * 64,
            )
        )
    assert error.value.code == "version_changed"
    assert error.value.status_code == 409


def test_page_client_sends_query_fields_and_omits_private_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"items": [], "total": 0, "page": 3, "page_size": 12},
        )

    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="1.0.0",
        transport=httpx.MockTransport(handler),
    )

    async def exercise() -> None:
        public = await marketplace.list_skill_page(
            query="writing",
            category="novel",
            sort="popular",
            page=3,
            page_size=12,
            favorites=False,
            access_token="secret",
        )
        private = await marketplace.list_skill_page(
            page=1,
            page_size=24,
            favorites=True,
            access_token="access",
        )
        assert public["total"] == 0
        assert private["page"] == 3

    asyncio.run(exercise())
    assert requests[0].url.path == "/api/resource-marketplace/catalog/skills"
    assert requests[0].url.params["q"] == "writing"
    assert requests[0].url.params["category"] == "novel"
    assert requests[0].url.params["sort"] == "popular"
    assert requests[0].url.params["favorites"] == "false"
    assert "authorization" not in requests[0].headers
    assert requests[1].url.params["favorites"] == "true"
    assert requests[1].headers["authorization"] == "Bearer access"


def test_open_installed_uses_local_ownership(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, manager=_empty_manager(tmp_path))
    with pytest.raises(LocalSkillError) as missing:
        asyncio.run(service.open_installed_skill("shared-skill"))
    assert missing.value.code == "not_found"

    local_conflict = _service(tmp_path / "local")
    with pytest.raises(LocalSkillError) as conflicted:
        asyncio.run(local_conflict.open_installed_skill("shared-skill"))
    assert conflicted.value.code == "conflict"

    installed = _service(tmp_path / "installed", manager=_empty_manager(tmp_path / "installed"))
    asyncio.run(installed.install("shared-skill", **_pin(installed)))
    opened = asyncio.run(installed.open_installed_skill("shared-skill"))
    assert opened == {"opened": True, "skill_id": "shared-skill"}
    skill = installed.skill_manager.get_skill("shared-skill")
    assert skill is not None
    assert skill.enabled is True

    builtin_root = tmp_path / "builtin"
    directory = builtin_root / "skills" / "builtin" / "shared-skill"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
    builtin = _service(builtin_root, manager=_empty_manager(builtin_root))
    assert asyncio.run(builtin.open_installed_skill("shared-skill")) == {
        "opened": True,
        "skill_id": "shared-skill",
    }

    with _desktop_client(tmp_path / "route", installed, monkeypatch) as client:
        response = client.post("/api/resource-marketplace/skills/shared-skill/open-installed")
        assert response.status_code == 200
        assert response.json() == {"opened": True, "skill_id": "shared-skill"}
        assert "path" not in response.json()
        missing_route = client.post("/api/resource-marketplace/skills/missing-skill/open-installed")
        assert missing_route.status_code == 404
        assert missing_route.json()["detail"]["code"] == "not_found"
