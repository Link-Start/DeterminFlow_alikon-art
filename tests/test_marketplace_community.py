from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.skill_marketplace.portal import MarketplaceRequestError, ResourceMarketplaceClient
from src.skill_marketplace.catalog import validate_review_updated_at
from src.skill_marketplace.routes import router
from src.skill_marketplace.service import LocalSkillError, SkillMarketplaceService
from marketplace_fixtures import FakeAccount, FakeMarketplace, _empty_manager, _service

REVIEW_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UPDATED_AT = "2026-08-31T01:00:00Z"


@pytest.mark.parametrize("stamp", ["yesterday", "2026-02-30T01:00:00Z", "2026-09-05T00:00:00"])
def test_review_revision_requires_valid_timestamp(stamp: str) -> None:
    with pytest.raises(LocalSkillError, match="评价修订时间无效"):
        validate_review_updated_at(stamp)


@pytest.mark.parametrize("stamp", [UPDATED_AT, "2026-09-05T08:00:00.123+00:00"])
def test_review_revision_preserves_exact_comparison_value(stamp: str) -> None:
    assert validate_review_updated_at(stamp) == stamp


def test_worker_validation_errors_are_client_errors_not_service_failures() -> None:
    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="test",
        transport=httpx.MockTransport(lambda request: httpx.Response(
            400, json={"code": "invalid_report", "detail": "Invalid report target"}, request=request,
        )),
    )
    with pytest.raises(MarketplaceRequestError) as error:
        asyncio.run(marketplace.report_community_review(
            "shared-skill", REVIEW_ID, expected_updated_at=UPDATED_AT,
            reason="spam", details="", access_token="access",
        ))
    assert error.value.status_code == 400
    assert error.value.code == "invalid_report"


def _desktop(tmp_path: Path, service: SkillMarketplaceService, monkeypatch) -> TestClient:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    app = FastAPI()
    app.state.resource_marketplace_service = service
    app.include_router(router)
    return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))


def _signed_in(tmp_path: Path, **kwargs) -> SkillMarketplaceService:
    return _service(
        tmp_path,
        account=kwargs.pop("account", FakeAccount("access")),
        **kwargs,
    )


def test_review_page_is_anonymous_and_strips_private_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace = FakeMarketplace()
    service = _service(tmp_path, manager=_empty_manager(tmp_path), marketplace=marketplace)
    with _desktop(tmp_path, service, monkeypatch) as client:
        defaulted = client.get("/api/resource-marketplace/skills/shared-skill/reviews/page")
        assert defaulted.status_code == 200
        assert defaulted.headers["cache-control"] == "no-store"
        body = defaulted.json()
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert body["total"] == 1
        assert body["items"] == [
            {
                "id": REVIEW_ID,
                "author_label": "社区成员 abc",
                "rating": 5,
                "body": "Useful",
                "created_at": "2026-08-31T00:00:00Z",
                "updated_at": UPDATED_AT,
            }
        ]
        assert marketplace.community_calls[0] == {
            "action": "reviews.page",
            "slug": "shared-skill",
            "page": 1,
            "page_size": 20,
        }

        paged = client.get(
            "/api/resource-marketplace/skills/shared-skill/reviews/page?page=2&page_size=10"
        )
        assert paged.status_code == 200
        assert paged.json()["page"] == 2
        assert paged.json()["page_size"] == 10
        assert client.get("/api/resource-marketplace/skills/shared-skill/reviews/page?page=0").status_code == 400
        assert client.get(
            "/api/resource-marketplace/skills/shared-skill/reviews/page?page=100001"
        ).status_code == 400
        assert client.get(
            "/api/resource-marketplace/skills/shared-skill/reviews/page?page_size=0"
        ).status_code == 400
        assert client.get(
            "/api/resource-marketplace/skills/shared-skill/reviews/page?page_size=101"
        ).status_code == 400


def test_delete_and_report_review_use_login_and_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace = FakeMarketplace()
    service = _signed_in(tmp_path, marketplace=marketplace)
    with _desktop(tmp_path, service, monkeypatch) as client:
        deleted = client.request(
            "DELETE",
            "/api/resource-marketplace/skills/shared-skill/review",
            json={"review_id": REVIEW_ID, "expected_updated_at": UPDATED_AT},
        )
        assert deleted.status_code == 200
        assert deleted.headers["cache-control"] == "no-store"
        assert deleted.json() == {"deleted": True}
        reported = client.post(
            f"/api/resource-marketplace/skills/shared-skill/reviews/{REVIEW_ID}/report",
            json={"expected_updated_at": UPDATED_AT, "reason": "spam", "details": "  重复广告  "},
        )
        assert reported.status_code == 200
        assert reported.json() == {"reported": True}
        assert [call["action"] for call in marketplace.community_calls] == [
            "delete",
            "review.report",
        ]
        assert marketplace.community_calls[0]["review_id"] == REVIEW_ID
        assert marketplace.community_calls[0]["expected_updated_at"] == UPDATED_AT
        assert marketplace.community_calls[1]["details"] == "重复广告"

        invalid = client.request(
            "DELETE",
            "/api/resource-marketplace/skills/shared-skill/review",
            json={"review_id": "not-a-uuid", "expected_updated_at": UPDATED_AT},
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"]["code"] == "invalid_review_id"
        pathish = client.request(
            "DELETE",
            "/api/resource-marketplace/skills/shared-skill/review",
            json={"review_id": REVIEW_ID, "expected_updated_at": "https://evil.example/stamp"},
        )
        assert pathish.status_code == 400
        assert pathish.json()["detail"]["code"] == "invalid_review"

    signed_out = _service(
        tmp_path / "anon",
        manager=_empty_manager(tmp_path / "anon"),
        account=FakeAccount(),
    )
    with _desktop(tmp_path / "anon", signed_out, monkeypatch) as anon:
        denied = anon.request(
            "DELETE",
            "/api/resource-marketplace/skills/shared-skill/review",
            json={"review_id": REVIEW_ID, "expected_updated_at": UPDATED_AT},
        )
        assert denied.status_code == 401
        assert denied.json()["detail"]["code"] == "login_required"


def test_review_cas_conflict_and_rate_limit_propagate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace = FakeMarketplace()
    marketplace.review_changed = True
    service = _signed_in(tmp_path, marketplace=marketplace)
    with _desktop(tmp_path, service, monkeypatch) as client:
        stale = client.request(
            "DELETE",
            "/api/resource-marketplace/skills/shared-skill/review",
            json={"review_id": REVIEW_ID, "expected_updated_at": UPDATED_AT},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "review_changed"
        assert stale.headers["cache-control"] == "no-store"

    class LimitedMarketplace(FakeMarketplace):
        async def report_community_review(self, slug: str, review_id: str, **kwargs) -> dict:
            await self._check_access(kwargs["access_token"])
            raise MarketplaceRequestError(
                "rate_limited",
                "评价举报过于频繁，请稍后重试",
                status_code=429,
                retry_after_seconds=42,
            )

    limited = _signed_in(tmp_path / "limited", marketplace=LimitedMarketplace())
    with _desktop(tmp_path / "limited", limited, monkeypatch) as client:
        throttled = client.post(
            f"/api/resource-marketplace/skills/shared-skill/reviews/{REVIEW_ID}/report",
            json={"expected_updated_at": UPDATED_AT, "reason": "spam", "details": ""},
        )
        assert throttled.status_code == 429
        assert throttled.json()["detail"] == {
            "code": "rate_limited",
            "message": "评价举报过于频繁，请稍后重试",
            "retry_after_seconds": 42,
        }
        assert throttled.headers["retry-after"] == "42"
        assert throttled.headers["cache-control"] == "no-store"


def test_own_review_keeps_id_and_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OwnReviewMarketplace(FakeMarketplace):
        async def get_community_state(self, slug: str, *, access_token: str) -> dict:
            await self._check_access(access_token)
            return {
                "favorited": False,
                "review": {
                    "id": REVIEW_ID,
                    "rating": 4,
                    "body": "实际使用正常",
                    "updated_at": UPDATED_AT,
                    "visibility": "hidden",
                    "moderation_reason": "请补充使用说明",
                },
            }

        async def upsert_community_review(self, slug: str, **kwargs) -> dict:
            await self._check_access(kwargs["access_token"])
            return {
                "id": REVIEW_ID,
                "rating": kwargs["rating"],
                "body": kwargs["body"],
                "updated_at": UPDATED_AT,
                "visibility": "hidden",
                "moderation_reason": "请补充使用说明",
            }

    marketplace = OwnReviewMarketplace()
    service = _signed_in(tmp_path, marketplace=marketplace)
    with _desktop(tmp_path, service, monkeypatch) as client:
        detail = client.get("/api/resource-marketplace/skills/shared-skill")
        assert detail.status_code == 200
        assert detail.json()["viewer"]["review"] == {
            "id": REVIEW_ID,
            "rating": 4,
            "body": "实际使用正常",
            "updated_at": UPDATED_AT,
            "visibility": "hidden",
            "moderation_reason": "请补充使用说明",
        }
        saved = client.put(
            "/api/resource-marketplace/skills/shared-skill/review",
            json={"rating": 4, "body": "实际使用正常"},
        )
        assert saved.json()["id"] == REVIEW_ID
        assert saved.json()["visibility"] == "hidden"
        assert saved.json()["moderation_reason"] == "请补充使用说明"


def test_portal_review_page_delete_report_and_retry_after() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.endswith("/reviews/page"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": REVIEW_ID,
                            "author_label": "社区成员 abc",
                            "rating": 5,
                            "body": "Useful",
                            "created_at": "2026-08-31T00:00:00Z",
                            "updated_at": UPDATED_AT,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                },
            )
        if request.method == "DELETE" and path.endswith("/review"):
            payload = json.loads(request.content)
            assert payload == {"review_id": REVIEW_ID, "expected_updated_at": UPDATED_AT}
            return httpx.Response(200, json={"deleted": True})
        if request.method == "POST" and path.endswith(f"/reviews/{REVIEW_ID}/report"):
            return httpx.Response(
                429,
                json={
                    "code": "rate_limited",
                    "detail": "评价举报过于频繁，请稍后重试",
                    "retry_after_seconds": 30,
                },
                headers={"Retry-After": "30"},
            )
        if request.method == "POST" and path.endswith("/report"):
            return httpx.Response(
                409,
                json={"code": "review_changed", "detail": "评价已变化，请刷新后重试"},
            )
        return httpx.Response(404, json={"detail": "missing"})

    marketplace = ResourceMarketplaceClient(
        "https://marketplace.example",
        app_version="1.0.0",
        transport=httpx.MockTransport(handler),
    )

    async def exercise() -> None:
        page = await marketplace.list_community_review_page("shared-skill", page=1, page_size=20)
        assert page["items"][0]["id"] == REVIEW_ID
        deleted = await marketplace.delete_community_review(
            "shared-skill",
            review_id=REVIEW_ID,
            expected_updated_at=UPDATED_AT,
            access_token="access",
        )
        assert deleted == {"deleted": True}
        with pytest.raises(MarketplaceRequestError) as limited:
            await marketplace.report_community_review(
                "shared-skill",
                REVIEW_ID,
                expected_updated_at=UPDATED_AT,
                reason="spam",
                details="",
                access_token="access",
            )
        assert limited.value.code == "rate_limited"
        assert limited.value.status_code == 429
        assert limited.value.retry_after_seconds == 30
        assert limited.value.message == "评价举报过于频繁，请稍后重试"
        with pytest.raises(MarketplaceRequestError) as changed:
            await marketplace.report_skill(
                "shared-skill",
                reason="spam",
                details="",
                access_token="access",
            )
        assert changed.value.code == "review_changed"
        assert changed.value.status_code == 409

    asyncio.run(exercise())
    assert "authorization" not in requests[0].headers
    assert requests[1].headers["authorization"] == "Bearer access"


def test_local_review_validation_rejects_paths(tmp_path: Path) -> None:
    service = _signed_in(tmp_path)
    with pytest.raises(LocalSkillError) as error:
        asyncio.run(
            service.delete_community_review(
                "shared-skill",
                review_id="../secret",
                expected_updated_at=UPDATED_AT,
            )
        )
    assert error.value.code == "invalid_review_id"
