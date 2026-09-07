from __future__ import annotations

import hashlib
from pathlib import Path

from src.skill_marketplace.portal import MarketplaceRequestError
from src.skill_marketplace.service import SkillMarketplaceService
from src.skills.config_manager import SkillConfigManager
from src.skills.manager import SkillManager

SKILL_TEXT = """---
name: shared-skill
description: A shareable test Skill
metadata:
  version: 1.2.3
---

# Instructions

Do the useful thing.
"""

SAMPLE_SUBMISSION = {
    "id": "11111111-1111-4111-8111-111111111111",
    "slug": "shared-skill",
    "name": "shared-skill",
    "summary": "A shareable test Skill",
    "version": "1.2.3",
    "sha256": "a" * 64,
    "size_bytes": 42,
    "license": "MIT",
    "status": "pending_review",
    "resource_status": "pending_review",
    "is_current": False,
    "review_reason": None,
    "submitted_at": "2026-08-31T00:00:00Z",
    "reviewed_at": None,
}


class FakeMarketplace:
    base_url = "https://marketplace.example"

    def __init__(self, content: bytes = SKILL_TEXT.encode()) -> None:
        self.content = content
        self.published: list[dict] = []
        self.review_calls: list[dict] = []
        self.suspend_calls: list[dict] = []
        self.resume_calls: list[dict] = []
        self.withdraw_calls: list[dict] = []
        self.lifecycle_calls: list[dict] = []
        self.community_calls: list[dict] = []
        self.review_changed = False
        self.name_check_calls: list[dict] = []
        self.refresh_count = 0
        self.forbidden = False
        self.conflict = False
        self.submissions = [dict(SAMPLE_SUBMISSION)]
        self.page_calls: list[dict] = []
        self.preview_calls: list[dict] = []
        self.download_calls: list[str] = []
        self.author_resource_calls: list[dict] = []
        self.author_version_calls: list[dict] = []
        self.feedback_calls: list[dict] = []
        self.feedback_read_calls: list[dict] = []
        self.feedback_changed = False
        self.author_resources = {
            "items": [
                {
                    "slug": "shared-skill",
                    "latest": dict(SAMPLE_SUBMISSION),
                    "current": None,
                    "candidate": dict(SAMPLE_SUBMISSION),
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 20,
        }
        self.author_versions = {
            "items": [dict(SAMPLE_SUBMISSION)],
            "total": 1,
            "page": 1,
            "page_size": 20,
        }
        self.feedback = {
            "items": [
                {
                    "id": "submission:11111111-1111-4111-8111-111111111111",
                    "kind": "submission",
                    "resource_slug": "shared-skill",
                    "resource_name": "shared-skill",
                    "version": "1.2.3",
                    "status": "rejected",
                    "message": "缺少来源说明",
                    "updated_at": "2026-08-31T01:00:00Z",
                    "unread": True,
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 20,
            "unread_total": 1,
        }

    async def list_skills(
        self,
        *,
        query: str = "",
        category: str = "all",
        sort: str = "updated",
    ) -> dict:
        return {"items": [], "query": query, "category": category, "sort": sort}

    async def list_skill_page(
        self,
        *,
        query: str = "",
        category: str = "all",
        sort: str = "updated",
        page: int = 1,
        page_size: int = 24,
        favorites: bool = False,
        access_token: str | None = None,
    ) -> dict:
        kwargs = {
            "query": query,
            "category": category,
            "sort": sort,
            "page": page,
            "page_size": page_size,
            "favorites": favorites,
            "access_token": access_token,
        }
        self.page_calls.append(kwargs)
        if favorites:
            await self._check_access(access_token or "")
        item = await self.get_skill("shared-skill")
        if item.get("deprecated_at") and not favorites:
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        return {
            "items": [item],
            "total": 1,
            "page": page,
            "page_size": page_size,
        }

    async def preview_skill(
        self,
        slug: str,
        *,
        expected_version_id: str,
        expected_sha256: str,
    ) -> dict:
        self.preview_calls.append(
            {
                "slug": slug,
                "expected_version_id": expected_version_id,
                "expected_sha256": expected_sha256,
            }
        )
        detail = await self.get_skill(slug)
        current_version = str(detail.get("version_id") or "")
        current_sha256 = str(detail.get("sha256") or "")
        if (
            expected_version_id != current_version
            or expected_sha256 != current_sha256
        ):
            raise MarketplaceRequestError(
                "version_changed",
                "资源版本已变化，请刷新详情后重新确认",
                status_code=409,
            )
        return {
            "content": self.content.decode("utf-8"),
            "version_id": current_version,
            "sha256": current_sha256,
        }

    async def get_skill(self, slug: str) -> dict:
        return {
            "resource_id": "22222222-2222-4222-8222-222222222222",
            "version_id": "33333333-3333-4333-8333-333333333333",
            "publisher_id": "pub_0123456789abcdef01234567",
            "resource_type": "skill",
            "functional_category": "general",
            "slug": slug,
            "skill_name": "shared-skill",
            "version": "1.2.3",
            "license": "MIT",
            "sha256": hashlib.sha256(self.content).hexdigest(),
        }

    async def download_skill(self, slug: str) -> tuple[bytes, str]:
        self.download_calls.append(slug)
        digest = hashlib.sha256(self.content).hexdigest()
        return self.content, digest

    async def list_community_reviews(self, slug: str) -> dict:
        return {"items": [{"id": "review", "body": "Useful", "rating": 5}]}

    async def list_community_review_page(
        self,
        slug: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        self.community_calls.append(
            {"action": "reviews.page", "slug": slug, "page": page, "page_size": page_size}
        )
        return {
            "items": [
                {
                    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    "author_label": "社区成员 abc",
                    "rating": 5,
                    "body": "Useful",
                    "created_at": "2026-08-31T00:00:00Z",
                    "updated_at": "2026-08-31T01:00:00Z",
                    "account_id": "acct_hidden",
                    "visibility": "hidden",
                    "moderation_reason": "内部原因",
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        }

    async def get_community_state(self, slug: str, *, access_token: str) -> dict:
        await self._check_access(access_token)
        return {"favorited": False, "review": None}

    async def set_favorite(self, slug: str, **kwargs) -> dict:
        self.community_calls.append({"action": "favorite", "slug": slug, **kwargs})
        await self._check_access(kwargs["access_token"])
        return {"favorited": kwargs["favorited"], "favorite_count": 1}

    async def upsert_community_review(self, slug: str, **kwargs) -> dict:
        self.community_calls.append({"action": "review", "slug": slug, **kwargs})
        await self._check_access(kwargs["access_token"])
        return {"rating": kwargs["rating"], "body": kwargs["body"]}

    async def delete_community_review(self, slug: str, **kwargs) -> dict:
        self.community_calls.append({"action": "delete", "slug": slug, **kwargs})
        await self._check_access(kwargs["access_token"])
        if self.review_changed:
            raise MarketplaceRequestError(
                "review_changed",
                "评价已变化，请刷新后重试",
                status_code=409,
            )
        return {"deleted": True}

    async def report_skill(self, slug: str, **kwargs) -> dict:
        self.community_calls.append({"action": "report", "slug": slug, **kwargs})
        await self._check_access(kwargs["access_token"])
        return {"reported": True}

    async def report_community_review(self, slug: str, review_id: str, **kwargs) -> dict:
        self.community_calls.append(
            {"action": "review.report", "slug": slug, "review_id": review_id, **kwargs}
        )
        await self._check_access(kwargs["access_token"])
        if self.review_changed:
            raise MarketplaceRequestError(
                "review_changed",
                "评价已变化，请刷新后重试",
                status_code=409,
            )
        return {"reported": True}

    async def publish_skill(self, **kwargs) -> dict:
        self.published.append(kwargs)
        if kwargs["access_token"] == "expired":
            raise MarketplaceRequestError(
                "authentication_failed",
                "expired",
                status_code=401,
            )
        return {"status": "pending_review"}

    async def check_resource_names(self, slugs: list[str], *, access_token: str) -> dict:
        await self._check_access(access_token)
        self.name_check_calls.append({"slugs": slugs, "access_token": access_token})
        return {
            "items": [
                {"slug": slug, "status": "conflict" if slug == "taken-skill" else "available"}
                for slug in slugs
            ]
        }

    async def refresh(self, refresh_token: str) -> dict[str, str]:
        assert refresh_token == "refresh"
        self.refresh_count += 1
        return {"access_token": "renewed", "refresh_token": "refresh-2"}

    async def logout(self, refresh_token: str) -> None:
        return None

    async def list_author_resources(self, **kwargs) -> dict:
        await self._check_access(kwargs["access_token"])
        self.author_resource_calls.append(kwargs)
        return {
            **self.author_resources,
            "page": kwargs.get("page", 1),
            "page_size": kwargs.get("page_size", 20),
        }

    async def list_author_versions(self, slug: str, **kwargs) -> dict:
        await self._check_access(kwargs["access_token"])
        self.author_version_calls.append({"slug": slug, **kwargs})
        if slug != "shared-skill":
            raise MarketplaceRequestError("not_found", "Skill 不存在", status_code=404)
        return {
            **self.author_versions,
            "page": kwargs.get("page", 1),
            "page_size": kwargs.get("page_size", 20),
        }

    async def list_feedback(self, **kwargs) -> dict:
        await self._check_access(kwargs["access_token"])
        self.feedback_calls.append(kwargs)
        items = list(self.feedback["items"])
        if kwargs.get("unread_only"):
            items = [item for item in items if item.get("unread")]
        return {
            **self.feedback,
            "items": items,
            "page": kwargs.get("page", 1),
            "page_size": kwargs.get("page_size", 20),
        }

    async def mark_feedback_read(self, **kwargs) -> dict:
        await self._check_access(kwargs["access_token"])
        self.feedback_read_calls.append(kwargs)
        if self.feedback_changed:
            raise MarketplaceRequestError(
                "feedback_changed",
                "反馈状态已变化，请刷新后重试",
                status_code=409,
            )
        return {
            "id": kwargs["feedback_id"],
            "updated_at": kwargs["expected_updated_at"],
            "unread": False,
        }

    async def list_submissions(self, *, access_token: str) -> dict:
        return await self._authenticated_items(access_token)

    async def get_submission(self, version_id: str, *, access_token: str) -> dict:
        item = await self._authenticated_item(access_token, version_id)
        return {**item, "content": SKILL_TEXT}

    async def withdraw_submission(self, version_id: str, *, access_token: str) -> dict:
        await self._authenticated_item(access_token, version_id)
        self.withdraw_calls.append({"version_id": version_id, "access_token": access_token})
        return {"id": version_id, "slug": "shared-skill", "version": "1.2.3", "status": "withdrawn"}

    async def list_review_queue(self, *, access_token: str) -> dict:
        return await self._authenticated_items(access_token)

    async def get_review_item(self, version_id: str, *, access_token: str) -> dict:
        item = await self._authenticated_item(access_token, version_id)
        return {**item, "content": SKILL_TEXT}

    async def review_version(self, version_id: str, **kwargs) -> dict:
        kwargs["version_id"] = version_id
        self.review_calls.append(kwargs)
        await self._authenticated_item(kwargs["access_token"], version_id)
        if self.conflict:
            raise MarketplaceRequestError("conflict", "审核状态已变化", status_code=409)
        return {
            "id": version_id,
            "status": "published" if kwargs["decision"] == "approve" else "rejected",
            "slug": "shared-skill",
            "version": "1.2.3",
        }

    async def suspend_skill(self, slug: str, **kwargs) -> dict:
        kwargs["slug"] = slug
        self.suspend_calls.append(kwargs)
        await self._authenticated_item(kwargs["access_token"], kwargs["expected_version_id"])
        if self.conflict:
            raise MarketplaceRequestError("conflict", "审核状态已变化", status_code=409)
        return {"slug": slug, "status": "suspended"}

    async def resume_skill(self, slug: str, **kwargs) -> dict:
        kwargs["slug"] = slug
        self.resume_calls.append(kwargs)
        await self._authenticated_item(kwargs["access_token"], kwargs["expected_version_id"])
        if self.conflict:
            raise MarketplaceRequestError("conflict", "审核状态已变化", status_code=409)
        return {"slug": slug, "status": "published"}

    async def update_skill_lifecycle(self, slug: str, **kwargs) -> dict:
        kwargs["slug"] = slug
        self.lifecycle_calls.append(kwargs)
        await self._check_access(kwargs["access_token"])
        return {
            "slug": slug,
            "deprecated_at": "2026-09-02T00:00:00Z" if kwargs["deprecated"] else None,
            "replacement_slug": kwargs["replacement_slug"] if kwargs["deprecated"] else None,
            "deprecation_message": kwargs["message"] if kwargs["deprecated"] else None,
        }

    async def _authenticated_items(self, access_token: str) -> dict:
        await self._check_access(access_token)
        return {"items": list(self.submissions)}

    async def _authenticated_item(self, access_token: str, version_id: str) -> dict:
        await self._check_access(access_token)
        for item in self.submissions:
            if item["id"] == version_id:
                return dict(item)
        raise MarketplaceRequestError("not_found", "Skill 不存在", status_code=404)

    async def _check_access(self, access_token: str) -> None:
        if access_token == "expired":
            raise MarketplaceRequestError(
                "authentication_failed",
                "expired",
                status_code=401,
            )
        if self.forbidden:
            raise MarketplaceRequestError("forbidden", "没有审核权限", status_code=403)


class FakeAccount:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        issuer: str = "https://accounts.determinflow.com",
        subject: str = "acct_alice",
    ) -> None:
        self._access_token = access_token
        self.issuer = issuer
        self.subject = subject
        self.refresh_count = 0
        self._session_id = 1 if access_token else 0
        self._session_tokens = {access_token} if access_token else set()

    def access_token(self) -> str | None:
        return self._access_token

    def public_name(self) -> str | None:
        return None

    def local_identity_claims(self) -> tuple[str, str] | None:
        if self._access_token is None:
            return None
        return (self.issuer, self.subject)

    def current_session_id(self) -> int:
        return self._session_id

    def is_current_session(self, session_id: int) -> bool:
        return self._access_token is not None and session_id == self._session_id

    def is_current_access_token(self, access_token: str) -> bool:
        return self._access_token == access_token

    async def refresh_access_token(self, stale_access_token: str) -> str | None:
        if self._access_token is None:
            return None
        if self._access_token != stale_access_token:
            return self._access_token if stale_access_token in self._session_tokens else None
        self.refresh_count += 1
        self._access_token = "renewed"
        self._session_tokens.add("renewed")
        return self._access_token

    async def login(self) -> dict[str, bool]:
        self._session_id += 1
        self._access_token = "access"
        self._session_tokens = {"access"}
        return {"configured": True, "signed_in": True}

    async def logout(self) -> dict[str, bool]:
        self._session_id += 1
        self._access_token = None
        self._session_tokens = set()
        return {"configured": True, "signed_in": False}


def _manager(tmp_path: Path, *, with_attachment: bool = False) -> SkillManager:
    skill_dir = tmp_path / "skills" / "local" / "shared-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_TEXT, encoding="utf-8")
    if with_attachment:
        (skill_dir / "reference.txt").write_text("not allowed", encoding="utf-8")
    config = SkillConfigManager(tmp_path / "config" / "skills.json")
    return _empty_manager(tmp_path, config=config)


def _empty_manager(
    tmp_path: Path,
    *,
    config: SkillConfigManager | None = None,
) -> SkillManager:
    skills_root = tmp_path / "skills"
    return SkillManager(
        skills_root / "local",
        config or SkillConfigManager(tmp_path / "config" / "skills.json"),
        builtin_skills_dir=skills_root / "builtin",
        marketplace_skills_dir=skills_root / "marketplace",
        provenance_path=tmp_path / "resource-provenance.json",
    )


def _service(
    tmp_path: Path,
    *,
    manager: SkillManager | None = None,
    marketplace: FakeMarketplace | None = None,
    account: FakeAccount | None = None,
) -> SkillMarketplaceService:
    return SkillMarketplaceService(
        data_dir=tmp_path / "data",
        skill_manager=manager or _manager(tmp_path),
        marketplace=marketplace or FakeMarketplace(),  # type: ignore[arg-type]
        account_session=account,  # type: ignore[arg-type]
    )
