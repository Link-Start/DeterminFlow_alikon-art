from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.skill_marketplace.portal import (
    DEFAULT_MARKETPLACE_URL,
    MarketplaceRequestError,
    ResourceMarketplaceClient,
    is_allowed_marketplace_url,
    resolve_marketplace_embed_url,
)
from src.skill_marketplace.routes import router
from src.skill_marketplace.service import LocalSkillError, SkillMarketplaceService
from src.skills.config_manager import SkillConfigManager
from src.skills.manager import SkillManager

from marketplace_fixtures import (
    FakeAccount, FakeMarketplace, SAMPLE_SUBMISSION, SKILL_TEXT,
    _empty_manager, _manager, _service,
)


def test_marketplace_url_allows_https_and_explicit_loopback_only() -> None:
    assert DEFAULT_MARKETPLACE_URL == "https://determinflow.com"
    assert is_allowed_marketplace_url("https://determinflow.example")
    assert not is_allowed_marketplace_url("http://determinflow.example")
    assert not is_allowed_marketplace_url("http://127.0.0.1:8000")
    assert is_allowed_marketplace_url(
        "http://127.0.0.1:8000",
        allow_loopback_http=True,
    )
    assert not is_allowed_marketplace_url("https://user:pass@example.com")
    assert not is_allowed_marketplace_url("https://determinflow.com/embed/marketplace#x")
    assert not is_allowed_marketplace_url("https://determinflow.com/embed/marketplace?next=/admin")


def test_marketplace_embed_url_defaults_and_independent_override() -> None:
    assert resolve_marketplace_embed_url("https://determinflow.com") == (
        "https://determinflow.com/embed/marketplace"
    )
    assert resolve_marketplace_embed_url(
        "https://determinflow.com/",
        override="https://preview.example/embed/marketplace",
    ) == "https://preview.example/embed/marketplace"
    assert resolve_marketplace_embed_url(
        "https://determinflow.com",
        override="http://127.0.0.1:8787/embed/marketplace",
        allow_loopback_http=True,
    ) == "http://127.0.0.1:8787/embed/marketplace"
    with pytest.raises(ValueError, match="嵌入地址"):
        resolve_marketplace_embed_url(None)
    with pytest.raises(ValueError, match="嵌入地址"):
        resolve_marketplace_embed_url(
            "https://determinflow.com",
            override="http://127.0.0.1:8787/embed/marketplace",
        )
    with pytest.raises(ValueError, match="嵌入地址"):
        resolve_marketplace_embed_url(
            "https://determinflow.com",
            override="https://user:pass@example.com/embed/marketplace",
        )
    with pytest.raises(ValueError, match="嵌入地址"):
        resolve_marketplace_embed_url(
            "https://determinflow.com",
            override="https://example.com/embed/marketplace#token",
        )
    with pytest.raises(ValueError, match="嵌入地址"):
        resolve_marketplace_embed_url(
            "https://determinflow.com",
            override="http://example.com/embed/marketplace",
            allow_loopback_http=True,
        )


def test_configured_marketplace_status_includes_embed_url(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.status() == {
        "configured": True,
        "signed_in": False,
        "account_name": None,
        "marketplace_url": "https://marketplace.example",
        "embed_url": "https://marketplace.example/embed/marketplace",
        "resource_types": ["skill", "prompt", "agent", "workflow", "rule"],
        "publishable_resource_types": ["skill"],
        "functional_categories": [
            "general", "novel", "comic-drama", "media", "development",
            "productivity", "business", "education", "other",
        ],
    }

    overridden = SkillMarketplaceService(
        data_dir=tmp_path / "override",
        skill_manager=_manager(tmp_path / "override"),
        marketplace=FakeMarketplace(),  # type: ignore[arg-type]
        embed_url="https://embed.example/embed/marketplace",
    )
    assert overridden.status()["embed_url"] == "https://embed.example/embed/marketplace"


@pytest.mark.parametrize(
    ("host", "peer", "origin"),
    [
        ("rebind.example", "127.0.0.1", None),
        ("127.0.0.1", "192.168.1.2", None),
        ("127.0.0.1", "127.0.0.1", "https://untrusted.example"),
        ("127.0.0.1", "127.0.0.1", "null"),
    ],
)
def test_desktop_marketplace_rejects_remote_or_cross_origin_access(
    monkeypatch, tmp_path, host, peer, origin,
):
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    app = FastAPI()
    app.state.resource_marketplace_service = _service(tmp_path)
    app.include_router(router)
    headers = {"Origin": origin} if origin else {}
    with TestClient(app, base_url=f"http://{host}", client=(peer, 50000)) as client:
        for path in ("/status", "/submissions", "/review-queue"):
            assert client.get("/api/resource-marketplace" + path, headers=headers).status_code == 403


def test_marketplace_client_validates_list_and_publish_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/resource-marketplace/skills" and request.method == "POST":
            return httpx.Response(200, json={"status": "pending"})
        return httpx.Response(200, json={"items": []})

    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="1.0.0",
        transport=httpx.MockTransport(handler),
    )
    async def exercise() -> None:
        assert await marketplace.list_skills(query="writing") == {"items": []}
        assert await marketplace.publish_skill(
            content=SKILL_TEXT.encode(),
            license_id="MIT",
            rights_confirmed=True,
            resource_type="skill",
            metadata={"author_name": "北辰"},
            terms_confirmed=True,
            terms_version="2026-09-06",
            access_token="access",
        ) == {"status": "pending"}

    asyncio.run(exercise())
    assert requests[0].url.params["q"] == "writing"
    publish_payload = json.loads(requests[1].content)
    assert publish_payload == {
        "content": SKILL_TEXT,
        "license": "MIT",
        "rights_confirmed": True,
        "resource_type": "skill",
        "metadata": {"author_name": "北辰"},
        "terms_confirmed": True,
        "terms_version": "2026-09-06",
    }
    assert requests[1].headers["authorization"] == "Bearer access"


def test_only_user_owned_allowed_file_types_are_shareable(tmp_path: Path) -> None:
    service = _service(tmp_path, account=FakeAccount("access"))
    eligible = asyncio.run(service.eligible_local_skills())
    assert [item["id"] for item in eligible] == ["shared-skill"]
    assert eligible[0]["resource_type"] == "skill"
    assert eligible[0]["usage_guide"] == ""
    assert eligible[0]["preflight"][-1] == {
        "id": "name_unique",
        "label": "资源名称可用",
        "passed": True,
    }

    attached_root = tmp_path / "attached"
    attached_service = _service(
        attached_root,
        manager=_manager(attached_root, with_attachment=True),
        account=FakeAccount("access"),
    )
    assert asyncio.run(attached_service.eligible_local_skills()) == []
    with pytest.raises(LocalSkillError, match="白名单"):
        asyncio.run(
            attached_service.publish(
                skill_id="shared-skill",
                license_id="MIT",
                rights_confirmed=True,
                resource_type="skill",
                metadata={},
                terms_confirmed=True,
                terms_version="2026-09-06",
            )
        )

    core_root = tmp_path / "core"
    core_skill = core_root / "skills" / "builtin" / "shared-skill"
    core_skill.mkdir(parents=True)
    (core_skill / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
    core_manager = _empty_manager(core_root)
    core_service = _service(core_root, manager=core_manager)
    with pytest.raises(LocalSkillError, match="Core 内置"):
        core_service._read_shareable_skill("shared-skill")


def test_publish_requires_login_and_refreshes_once(tmp_path: Path) -> None:
    marketplace = FakeMarketplace()
    service = _service(
        tmp_path,
        marketplace=marketplace,
        account=FakeAccount(),
    )
    with pytest.raises(LocalSkillError, match="登录"):
        asyncio.run(
            service.publish(
                skill_id="shared-skill",
                license_id="MIT",
                rights_confirmed=True,
                resource_type="skill",
                metadata={},
                terms_confirmed=True,
                terms_version="2026-09-06",
            )
        )

    service.account_session = FakeAccount("expired")  # type: ignore[assignment]
    result = asyncio.run(
        service.publish(
            skill_id="shared-skill",
            license_id="MIT",
            rights_confirmed=True,
            resource_type="skill",
            metadata={"author_name": "北辰", "summary": "公开简介"},
            terms_confirmed=True,
            terms_version="2026-09-06",
        )
    )
    assert result == {"status": "pending_review"}
    assert service.account_session.refresh_count == 1  # type: ignore[union-attr]
    assert [item["access_token"] for item in marketplace.published] == ["expired", "renewed"]
    assert marketplace.published[-1]["metadata"] == {
        "author_name": "北辰",
        "summary": "公开简介",
    }


@pytest.mark.parametrize("stale_terms", ["2026-09-03", "2026-09-05", "2026-01-01"])
def test_publish_rejects_unopened_types_and_stale_terms(tmp_path: Path, stale_terms: str) -> None:
    service = _signed_in_service(tmp_path)
    base = {
        "skill_id": "shared-skill",
        "license_id": "MIT",
        "rights_confirmed": True,
        "metadata": {},
        "terms_confirmed": True,
        "terms_version": "2026-09-06",
    }

    with pytest.raises(LocalSkillError, match="仅开放 Skill"):
        asyncio.run(service.publish(resource_type="prompt", **base))

    with pytest.raises(LocalSkillError, match="当前作者发布协议"):
        asyncio.run(
            service.publish(
                resource_type="skill",
                **{**base, "terms_version": stale_terms},
            )
        )


def test_local_routes_are_available_only_in_desktop_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.resource_marketplace_service = _service(
        tmp_path,
        account=FakeAccount(),
    )
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))

    monkeypatch.delenv("DETERMINFLOW_DESKTOP", raising=False)
    assert client.get("/api/resource-marketplace/status").status_code == 404

    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    response = client.get("/api/resource-marketplace/eligible-skills")
    assert response.status_code == 401


def test_unconfigured_marketplace_reports_recoverable_status(tmp_path: Path) -> None:
    service = SkillMarketplaceService(
        data_dir=tmp_path / "data",
        skill_manager=_manager(tmp_path),
        marketplace=None,
    )

    assert service.status() == {
        "configured": False,
        "signed_in": False,
        "account_name": None,
        "marketplace_url": None,
        "embed_url": None,
        "resource_types": ["skill", "prompt", "agent", "workflow", "rule"],
        "publishable_resource_types": ["skill"],
        "functional_categories": [
            "general", "novel", "comic-drama", "media", "development",
            "productivity", "business", "education", "other",
        ],
    }
    with pytest.raises(LocalSkillError, match="尚未配置"):
        asyncio.run(service.list_skills())


def _signed_in_service(
    tmp_path: Path,
    *,
    marketplace: FakeMarketplace | None = None,
    access_token: str = "access",
) -> SkillMarketplaceService:
    return _service(
        tmp_path,
        marketplace=marketplace,
        account=FakeAccount(access_token),
    )


def test_owner_and_review_client_preserve_auth_contract_and_errors() -> None:
    requests: list[httpx.Request] = []
    version_id = SAMPLE_SUBMISSION["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/submissions"):
            return httpx.Response(200, json={"items": [SAMPLE_SUBMISSION]})
        if request.url.path.endswith(f"/submissions/{version_id}"):
            return httpx.Response(200, json={**SAMPLE_SUBMISSION, "content": SKILL_TEXT})
        if request.url.path.endswith("/review-queue"):
            return httpx.Response(200, json={"items": [SAMPLE_SUBMISSION]})
        if request.url.path.endswith(f"/review-queue/{version_id}"):
            return httpx.Response(200, json={**SAMPLE_SUBMISSION, "content": SKILL_TEXT})
        if request.method == "POST" and request.url.path.endswith(f"/reviews/{version_id}"):
            payload = json.loads(request.content)
            if payload["decision"] == "reject":
                return httpx.Response(403, json={"detail": "没有审核权限", "code": "forbidden"})
            return httpx.Response(
                200,
                json={"id": version_id, "status": "published", "slug": "shared-skill", "version": "1.2.3"},
            )
        if request.method == "POST" and str(request.url.path).endswith("/suspend"):
            return httpx.Response(409, json={"detail": "当前版本不匹配"})
        if request.method == "PATCH" and str(request.url.path).endswith("/lifecycle"):
            return httpx.Response(200, json={
                "slug": "shared-skill",
                "deprecated_at": "2026-09-02T00:00:00Z",
                "replacement_slug": "replacement-skill",
                "deprecation_message": "请迁移",
            })
        return httpx.Response(404, json={"detail": "missing"})

    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="1.0.0",
        transport=httpx.MockTransport(handler),
    )

    async def exercise() -> None:
        listed = await marketplace.list_submissions(access_token="access")
        assert listed["items"][0]["id"] == version_id
        detail = await marketplace.get_submission(version_id, access_token="access")
        assert detail["content"] == SKILL_TEXT
        queue = await marketplace.list_review_queue(access_token="access")
        assert queue["items"][0]["status"] == "pending_review"
        shown = await marketplace.get_review_item(version_id, access_token="access")
        assert shown["sha256"] == SAMPLE_SUBMISSION["sha256"]
        approved = await marketplace.review_version(
            version_id,
            decision="approve",
            expected_sha256=SAMPLE_SUBMISSION["sha256"],
            reason=None,
            access_token="access",
        )
        assert approved["status"] == "published"
        with pytest.raises(MarketplaceRequestError) as forbidden:
            await marketplace.review_version(
                version_id,
                decision="reject",
                expected_sha256=SAMPLE_SUBMISSION["sha256"],
                reason="缺少说明",
                access_token="access",
            )
        assert forbidden.value.status_code == 403
        assert forbidden.value.code == "forbidden"
        with pytest.raises(MarketplaceRequestError) as conflict:
            await marketplace.suspend_skill(
                "shared-skill",
                expected_version_id=version_id,
                reason="违规内容",
                access_token="access",
            )
        assert conflict.value.status_code == 409
        assert conflict.value.code == "conflict"
        lifecycle = await marketplace.update_skill_lifecycle(
            "shared-skill",
            deprecated=True,
            replacement_slug="replacement-skill",
            message="请迁移",
            access_token="access",
        )
        assert lifecycle["replacement_slug"] == "replacement-skill"

    asyncio.run(exercise())
    assert [item.headers["authorization"] for item in requests] == ["Bearer access"] * 8
    approve_payload = json.loads(requests[4].content)
    assert approve_payload == {
        "decision": "approve",
        "expected_sha256": SAMPLE_SUBMISSION["sha256"],
    }
    reject_payload = json.loads(requests[5].content)
    assert reject_payload["reason"] == "缺少说明"
    suspend_payload = json.loads(requests[6].content)
    assert suspend_payload == {
        "expected_version_id": version_id,
        "reason": "违规内容",
    }
    lifecycle_payload = json.loads(requests[7].content)
    assert lifecycle_payload == {
        "deprecated": True,
        "replacement_slug": "replacement-skill",
        "message": "请迁移",
    }


def test_lifecycle_client_uses_fixed_withdraw_and_resume_routes() -> None:
    requests: list[httpx.Request] = []
    version_id = SAMPLE_SUBMISSION["id"]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith(f"/submissions/{version_id}/withdraw"):
            return httpx.Response(200, json={"id": version_id, "status": "withdrawn"})
        if request.url.path.endswith("/skills/shared-skill/resume"):
            return httpx.Response(200, json={"slug": "shared-skill", "status": "published"})
        return httpx.Response(404, json={"detail": "missing"})

    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="1.0.0",
        transport=httpx.MockTransport(handler),
    )

    async def exercise() -> None:
        withdrawn = await marketplace.withdraw_submission(version_id, access_token="access")
        resumed = await marketplace.resume_skill(
            "shared-skill",
            expected_version_id=version_id,
            reason="复核后恢复",
            access_token="access",
        )
        assert withdrawn["status"] == "withdrawn"
        assert resumed["status"] == "published"

    asyncio.run(exercise())
    assert [request.headers["authorization"] for request in requests] == [
        "Bearer access",
        "Bearer access",
    ]
    assert requests[0].method == "POST"
    assert json.loads(requests[1].content) == {
        "expected_version_id": version_id,
        "reason": "复核后恢复",
    }


def test_author_lifecycle_requires_guidance_and_forwards_owner_intent(tmp_path: Path) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in_service(tmp_path, marketplace=marketplace)
    with pytest.raises(LocalSkillError, match="必须填写原因"):
        asyncio.run(
            service.update_skill_lifecycle(
                "shared-skill",
                deprecated=True,
                replacement_slug=None,
                message=" ",
            )
        )
    result = asyncio.run(
        service.update_skill_lifecycle(
            "shared-skill",
            deprecated=True,
            replacement_slug="replacement-skill",
            message="请迁移",
        )
    )
    assert result["replacement_slug"] == "replacement-skill"
    assert marketplace.lifecycle_calls == [{
        "deprecated": True,
        "replacement_slug": "replacement-skill",
        "message": "请迁移",
        "access_token": "access",
        "slug": "shared-skill",
    }]


def test_submissions_and_reviews_refresh_expired_tokens_once(tmp_path: Path) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in_service(tmp_path, marketplace=marketplace, access_token="expired")
    listed = asyncio.run(service.list_submissions())
    reviewed = asyncio.run(
        service.review_version(
            SAMPLE_SUBMISSION["id"],
            decision="approve",
            expected_sha256=SAMPLE_SUBMISSION["sha256"],
        )
    )
    assert listed["items"][0]["id"] == SAMPLE_SUBMISSION["id"]
    assert reviewed["status"] == "published"
    assert service.account_session.refresh_count == 1  # type: ignore[union-attr]
    assert marketplace.review_calls[0]["access_token"] == "renewed"


def test_withdraw_and_resume_forward_validated_lifecycle_intent(tmp_path: Path) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in_service(tmp_path, marketplace=marketplace)

    withdrawn = asyncio.run(service.withdraw_submission(SAMPLE_SUBMISSION["id"]))
    resumed = asyncio.run(
        service.resume_skill(
            "shared-skill",
            expected_version_id=SAMPLE_SUBMISSION["id"],
            reason="复核后恢复",
        )
    )

    assert withdrawn["status"] == "withdrawn"
    assert resumed == {"slug": "shared-skill", "status": "published"}
    assert marketplace.withdraw_calls == [{
        "version_id": SAMPLE_SUBMISSION["id"],
        "access_token": "access",
    }]
    assert marketplace.resume_calls == [{
        "expected_version_id": SAMPLE_SUBMISSION["id"],
        "reason": "复核后恢复",
        "access_token": "access",
        "slug": "shared-skill",
    }]


def test_review_mutations_validate_ids_digest_and_reason(tmp_path: Path) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in_service(tmp_path, marketplace=marketplace)

    with pytest.raises(LocalSkillError, match="版本标识"):
        asyncio.run(service.get_submission("../secret"))
    with pytest.raises(LocalSkillError, match="内容摘要"):
        asyncio.run(
            service.review_version(
                SAMPLE_SUBMISSION["id"],
                decision="approve",
                expected_sha256="ABC" + "a" * 61,
            )
        )
    with pytest.raises(LocalSkillError, match="原因"):
        asyncio.run(
            service.review_version(
                SAMPLE_SUBMISSION["id"],
                decision="reject",
                expected_sha256=SAMPLE_SUBMISSION["sha256"],
                reason="   ",
            )
        )
    with pytest.raises(LocalSkillError, match="Skill 标识"):
        asyncio.run(
            service.suspend_skill(
                "Not_A_Slug",
                expected_version_id=SAMPLE_SUBMISSION["id"],
                reason="下架",
            )
        )
    with pytest.raises(LocalSkillError, match="版本标识"):
        asyncio.run(service.withdraw_submission("../secret"))
    with pytest.raises(LocalSkillError, match="原因"):
        asyncio.run(
            service.resume_skill(
                "shared-skill",
                expected_version_id=SAMPLE_SUBMISSION["id"],
                reason=" ",
            )
        )
    assert marketplace.review_calls == []
    assert marketplace.suspend_calls == []
    assert marketplace.resume_calls == []
    assert marketplace.withdraw_calls == []


def test_authenticated_moderation_routes_stay_desktop_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.resource_marketplace_service = _signed_in_service(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    version_id = SAMPLE_SUBMISSION["id"]
    review_body = {
        "decision": "approve",
        "expected_sha256": SAMPLE_SUBMISSION["sha256"],
    }

    monkeypatch.delenv("DETERMINFLOW_DESKTOP", raising=False)
    assert client.get("/api/resource-marketplace/submissions").status_code == 404
    assert client.get(f"/api/resource-marketplace/review-queue/{version_id}").status_code == 404
    assert client.post(
        f"/api/resource-marketplace/reviews/{version_id}",
        json=review_body,
    ).status_code == 404

    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    listed = client.get("/api/resource-marketplace/submissions")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == version_id
    shown = client.get(f"/api/resource-marketplace/review-queue/{version_id}")
    assert shown.status_code == 200
    assert shown.json()["content"] == SKILL_TEXT
    approved = client.post(
        f"/api/resource-marketplace/reviews/{version_id}",
        json=review_body,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "published"
    withdrawn = client.post(f"/api/resource-marketplace/submissions/{version_id}/withdraw")
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    resumed = client.post(
        "/api/resource-marketplace/skills/shared-skill/resume",
        json={"expected_version_id": version_id, "reason": "复核后恢复"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "published"
    rejected_id = client.get("/api/resource-marketplace/submissions/not-a-uuid")
    assert rejected_id.status_code == 400
    forbidden = _signed_in_service(tmp_path / "forbidden")
    forbidden.marketplace.forbidden = True  # type: ignore[union-attr]
    app.state.resource_marketplace_service = forbidden
    denied = client.get("/api/resource-marketplace/review-queue")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"
    conflicted = _signed_in_service(tmp_path / "conflict")
    conflicted.marketplace.conflict = True  # type: ignore[union-attr]
    app.state.resource_marketplace_service = conflicted
    stale = client.post(
        "/api/resource-marketplace/skills/shared-skill/suspend",
        json={"expected_version_id": version_id, "reason": "违规内容"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "conflict"


def test_community_routes_use_login_and_preserve_review_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in_service(tmp_path, marketplace=marketplace)
    app = FastAPI()
    app.include_router(router)
    app.state.resource_marketplace_service = service
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))

    detail = client.get("/api/resource-marketplace/skills/shared-skill")
    assert detail.status_code == 200
    assert detail.json()["viewer"] == {"favorited": False, "review": None}
    reviews = client.get("/api/resource-marketplace/skills/shared-skill/reviews")
    assert reviews.json()["items"][0]["rating"] == 5

    favorite = client.put(
        "/api/resource-marketplace/skills/shared-skill/favorite",
        json={"favorited": True},
    )
    assert favorite.json() == {"favorited": True, "favorite_count": 1}
    review = client.put(
        "/api/resource-marketplace/skills/shared-skill/review",
        json={"rating": 4, "body": "  实际使用正常  "},
    )
    assert review.json() == {"rating": 4, "body": "实际使用正常"}
    report = client.post(
        "/api/resource-marketplace/skills/shared-skill/report",
        json={"reason": "security", "details": "  请求读取凭据  "},
    )
    assert report.json() == {"reported": True}
    assert [call["action"] for call in marketplace.community_calls] == [
        "favorite", "review", "report",
    ]
