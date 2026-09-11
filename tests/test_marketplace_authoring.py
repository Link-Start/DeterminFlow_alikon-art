from __future__ import annotations

import asyncio
import hashlib
import json
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
    SAMPLE_SUBMISSION,
    SKILL_TEXT,
    _empty_manager,
    _manager,
    _service,
)

DIGEST = hashlib.sha256(SKILL_TEXT.encode()).hexdigest()
DRAFT_FIELDS = {
    "license": "MIT",
    "display_name": "共享技能",
    "author_name": "北辰",
    "summary": "",
    "functional_category": "novel",
    "primary_locale": "zh-CN",
    "tags_csv": "writing",
    "release_notes": "",
}


def _signed_in(tmp_path: Path, **kwargs) -> SkillMarketplaceService:
    return _service(
        tmp_path,
        account=kwargs.pop("account", FakeAccount("access")),
        **kwargs,
    )


def _desktop(tmp_path: Path, service: SkillMarketplaceService, monkeypatch) -> TestClient:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    app = FastAPI()
    app.state.resource_marketplace_service = service
    app.include_router(router)
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def test_publish_drafts_use_cas_and_keep_account_partitions(tmp_path: Path) -> None:
    alice = _signed_in(tmp_path, account=FakeAccount("access", subject="acct_alice"))
    bob = SkillMarketplaceService(
        data_dir=alice.data_dir,
        skill_manager=alice.skill_manager,
        marketplace=alice.marketplace,
        account_session=FakeAccount("access", subject="acct_bob"),  # type: ignore[arg-type]
    )
    missing = asyncio.run(alice.get_publish_draft("shared-skill"))
    assert missing["draft"] is None

    created = asyncio.run(
        alice.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields=DRAFT_FIELDS,
        )
    )["draft"]
    assert created["schema_version"] == 1
    assert created["revision"] == 1
    assert created["fields"]["display_name"] == "共享技能"
    draft_path = next((alice.data_dir / "resource-marketplace" / "drafts").rglob("shared-skill.json"))
    assert oct(draft_path.stat().st_mode & 0o777) == "0o600"

    with pytest.raises(LocalSkillError) as conflict:
        asyncio.run(
            alice.save_publish_draft(
                "shared-skill",
                expected_revision=None,
                base_version="1.2.3",
                base_sha256=DIGEST,
                fields=DRAFT_FIELDS,
            )
        )
    assert conflict.value.code == "draft_conflict"
    assert conflict.value.status_code == 409

    updated = asyncio.run(
        alice.save_publish_draft(
            "shared-skill",
            expected_revision=1,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields={**DRAFT_FIELDS, "summary": "简介"},
        )
    )["draft"]
    assert updated["revision"] == 2
    assert asyncio.run(bob.get_publish_draft("shared-skill"))["draft"] is None
    assert asyncio.run(alice.get_publish_draft("shared-skill"))["draft"]["revision"] == 2

    with pytest.raises(LocalSkillError) as stale_delete:
        asyncio.run(alice.delete_publish_draft("shared-skill", expected_revision=1))
    assert stale_delete.value.code == "draft_conflict"
    assert asyncio.run(alice.delete_publish_draft("shared-skill", expected_revision=2)) == {
        "deleted": True,
    }
    assert asyncio.run(alice.delete_publish_draft("shared-skill", expected_revision=9)) == {
        "deleted": True,
    }


def test_publish_drafts_isolate_marketplace_origins_and_reject_traversal(tmp_path: Path) -> None:
    first = FakeMarketplace()
    second = FakeMarketplace()
    second.base_url = "https://other-marketplace.example"
    alice = _signed_in(tmp_path, marketplace=first)
    other = SkillMarketplaceService(
        data_dir=alice.data_dir,
        skill_manager=alice.skill_manager,
        marketplace=second,  # type: ignore[arg-type]
        account_session=alice.account_session,
    )
    asyncio.run(
        alice.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields=DRAFT_FIELDS,
        )
    )
    assert asyncio.run(other.get_publish_draft("shared-skill"))["draft"] is None
    with pytest.raises(LocalSkillError) as traversal:
        asyncio.run(alice.get_publish_draft("../secret"))
    assert traversal.value.code == "invalid_slug"


def test_saving_a_draft_requires_a_shareable_skill_and_stable_identity(tmp_path: Path) -> None:
    unsigned = _service(tmp_path, account=FakeAccount())
    with pytest.raises(LocalSkillError) as login:
        asyncio.run(unsigned.get_publish_draft("shared-skill"))
    assert login.value.code == "login_required"

    nameless = FakeAccount("access")
    nameless.local_identity_claims = lambda: None  # type: ignore[method-assign]
    broken = _signed_in(tmp_path / "broken", account=nameless)
    with pytest.raises(LocalSkillError) as identity:
        asyncio.run(broken.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields=DRAFT_FIELDS,
        ))
    assert identity.value.code == "identity_unavailable"

    attached = _signed_in(
        tmp_path / "attached",
        manager=_manager(tmp_path / "attached", with_attachment=True),
    )
    with pytest.raises(LocalSkillError) as blocked:
        asyncio.run(
            attached.save_publish_draft(
                "shared-skill",
                expected_revision=None,
                base_version="1.2.3",
                base_sha256=DIGEST,
                fields=DRAFT_FIELDS,
            )
        )
    assert blocked.value.code == "file_type_not_allowed"


def test_local_preview_reads_shareable_bytes_and_refuses_foreign_skills(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _signed_in(tmp_path)
    preview = asyncio.run(service.preview_local_skill("shared-skill"))
    assert preview["skill_id"] == "shared-skill"
    assert preview["content"] == SKILL_TEXT
    assert preview["sha256"] == DIGEST
    assert preview["version"] == "1.2.3"

    with _desktop(tmp_path, service, monkeypatch) as client:
        response = client.get("/api/resource-marketplace/local-skills/shared-skill/preview")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["sha256"] == DIGEST
        assert "path" not in response.json()

    attached = _signed_in(
        tmp_path / "attached",
        manager=_manager(tmp_path / "attached", with_attachment=True),
    )
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(attached.preview_local_skill("shared-skill"))
    assert error.value.code == "file_type_not_allowed"


def test_pinned_publish_compares_the_same_bytes_and_keeps_unpinned_compat(
    tmp_path: Path,
) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in(tmp_path, marketplace=marketplace)
    result = asyncio.run(
        service.publish(
            skill_id="shared-skill",
            resource_type="skill",
            license_id="MIT",
            rights_confirmed=True,
            terms_confirmed=True,
            terms_version="2026-09-06",
            metadata={},
            expected_sha256=DIGEST,
        )
    )
    assert result["status"] == "pending_review"
    assert marketplace.published[-1]["content"] == SKILL_TEXT.encode()

    with pytest.raises(LocalSkillError) as changed:
        asyncio.run(
            service.publish(
                skill_id="shared-skill",
                resource_type="skill",
                license_id="MIT",
                rights_confirmed=True,
                terms_confirmed=True,
                terms_version="2026-09-06",
                metadata={},
                expected_sha256="b" * 64,
            )
        )
    assert changed.value.code == "local_skill_changed"
    assert changed.value.status_code == 409
    assert len(marketplace.published) == 1

    unpinned = asyncio.run(
        service.publish(
            skill_id="shared-skill",
            resource_type="skill",
            license_id="MIT",
            rights_confirmed=True,
            terms_confirmed=True,
            terms_version="2026-09-06",
            metadata={},
        )
    )
    assert unpinned["status"] == "pending_review"


def test_author_and_feedback_proxy_authenticated_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in(tmp_path, marketplace=marketplace)
    with _desktop(tmp_path, service, monkeypatch) as client:
        resources = client.get(
            "/api/resource-marketplace/author/resources",
            params={"q": "shared", "status": "pending", "page": 1, "page_size": 20},
        )
        assert resources.status_code == 200
        assert resources.headers["cache-control"] == "no-store"
        assert resources.json()["items"][0]["slug"] == "shared-skill"
        assert marketplace.author_resource_calls[-1]["query"] == "shared"
        assert marketplace.author_resource_calls[-1]["status"] == "pending"

        versions = client.get("/api/resource-marketplace/author/resources/shared-skill/versions")
        assert versions.status_code == 200
        assert versions.json()["items"][0]["id"] == SAMPLE_SUBMISSION["id"]
        missing = client.get("/api/resource-marketplace/author/resources/other-skill/versions")
        assert missing.status_code == 404

        assert client.get(
            "/api/resource-marketplace/author/resources?status=needs-changes"
        ).status_code == 400
        assert client.get("/api/resource-marketplace/author/resources?page=0").status_code == 400
        assert client.get("/api/resource-marketplace/feedback?unread_only=maybe").status_code == 400

        feedback = client.get("/api/resource-marketplace/feedback?unread_only=true")
        assert feedback.status_code == 200
        assert feedback.json()["unread_total"] == 1
        read = client.post(
            "/api/resource-marketplace/feedback/read",
            json={
                "id": "submission:11111111-1111-4111-8111-111111111111",
                "expected_updated_at": "2026-08-31T01:00:00Z",
            },
        )
        assert read.json() == {
            "id": "submission:11111111-1111-4111-8111-111111111111",
            "updated_at": "2026-08-31T01:00:00Z",
            "unread": False,
        }

        marketplace.feedback_changed = True
        stale = client.post(
            "/api/resource-marketplace/feedback/read",
            json={
                "id": "submission:11111111-1111-4111-8111-111111111111",
                "expected_updated_at": "2026-08-31T01:00:00Z",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "feedback_changed"

        listed = client.get("/api/resource-marketplace/submissions")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == SAMPLE_SUBMISSION["id"]

        drafts = client.get("/api/resource-marketplace/publish-drafts/shared-skill")
        assert drafts.status_code == 200
        assert drafts.headers["cache-control"] == "no-store"
        saved = client.put(
            "/api/resource-marketplace/publish-drafts/shared-skill",
            json={
                "expected_revision": None,
                "base_version": "1.2.3",
                "base_sha256": DIGEST,
                "fields": DRAFT_FIELDS,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["draft"]["revision"] == 1
        pinned = client.post(
            "/api/resource-marketplace/publish",
            json={
                "skill_id": "shared-skill",
                "resource_type": "skill",
                "license": "MIT",
                "rights_confirmed": True,
                "terms_confirmed": True,
                "terms_version": "2026-09-06",
                "expected_sha256": DIGEST,
            },
        )
        assert pinned.status_code == 200


def test_author_page_client_forwards_query_and_preserves_conflict_codes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/feedback/read"):
            return httpx.Response(
                409,
                json={"detail": "changed", "code": "feedback_changed"},
            )
        if request.url.path.endswith("/feedback"):
            return httpx.Response(
                200,
                json={
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "page_size": 20,
                    "unread_total": 2,
                },
            )
        return httpx.Response(
            200,
            json={"items": [], "total": 0, "page": 2, "page_size": 20},
        )

    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="1.0.0",
        transport=httpx.MockTransport(handler),
    )

    async def exercise() -> None:
        page = await marketplace.list_author_resources(
            query="writing",
            status="changes",
            page=2,
            page_size=20,
            access_token="access",
        )
        assert page["page"] == 2
        feedback = await marketplace.list_feedback(
            page=1,
            page_size=20,
            unread_only=True,
            access_token="access",
        )
        assert feedback["unread_total"] == 2
        with pytest.raises(MarketplaceRequestError) as error:
            await marketplace.mark_feedback_read(
                feedback_id="report:11111111-1111-4111-8111-111111111111",
                expected_updated_at="2026-09-05T00:00:00Z",
                access_token="access",
            )
        assert error.value.code == "feedback_changed"

    asyncio.run(exercise())
    assert requests[0].url.params["q"] == "writing"
    assert requests[0].url.params["status"] == "changes"
    assert requests[1].url.params["unread_only"] == "true"
    assert json.loads(requests[2].content)["id"].startswith("report:")


def test_logout_keeps_partitioned_drafts_for_the_same_account(tmp_path: Path) -> None:
    account = FakeAccount("access", subject="acct_alice")
    service = _signed_in(tmp_path, account=account)
    asyncio.run(
        service.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields=DRAFT_FIELDS,
        )
    )
    account._access_token = None
    with pytest.raises(LocalSkillError) as logged_out:
        asyncio.run(service.get_publish_draft("shared-skill"))
    assert logged_out.value.code == "login_required"
    account._access_token = "access"
    restored = asyncio.run(service.get_publish_draft("shared-skill"))
    assert restored["draft"]["revision"] == 1


def test_empty_manager_preview_is_not_found(tmp_path: Path) -> None:
    service = _signed_in(tmp_path, manager=_empty_manager(tmp_path))
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(service.preview_local_skill("shared-skill"))
    assert error.value.code == "not_found"


def test_publish_drafts_store_optional_usage_guide(tmp_path: Path) -> None:
    alice = _signed_in(tmp_path)
    created = asyncio.run(
        alice.save_publish_draft(
            "shared-skill",
            expected_revision=None,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields=DRAFT_FIELDS,
        )
    )["draft"]
    assert created["fields"]["usage_guide"] == ""

    updated = asyncio.run(
        alice.save_publish_draft(
            "shared-skill",
            expected_revision=1,
            base_version="1.2.3",
            base_sha256=DIGEST,
            fields={**DRAFT_FIELDS, "usage_guide": "作者使用说明"},
        )
    )["draft"]
    assert updated["fields"]["usage_guide"] == "作者使用说明"
    loaded = asyncio.run(alice.get_publish_draft("shared-skill"))["draft"]
    assert loaded["fields"]["usage_guide"] == "作者使用说明"

    with pytest.raises(LocalSkillError) as too_long:
        asyncio.run(
            alice.save_publish_draft(
                "shared-skill",
                expected_revision=2,
                base_version="1.2.3",
                base_sha256=DIGEST,
                fields={**DRAFT_FIELDS, "usage_guide": "x" * 8001},
            )
        )
    assert too_long.value.code == "invalid_draft"
