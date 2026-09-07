"""Community favorite, review, and report operations for the local client."""

from __future__ import annotations

from typing import Any

from .catalog import (
    DEFAULT_PAGE,
    DEFAULT_REVIEW_PAGE_SIZE,
    REPORT_REASONS,
    validate_catalog_page,
    validate_review_id,
    validate_review_updated_at,
)
from .errors import LocalSkillError

_PUBLIC_REVIEW_FIELDS = (
    "id",
    "author_label",
    "rating",
    "body",
    "created_at",
    "updated_at",
)


def public_review_items(items: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append({key: item[key] for key in _PUBLIC_REVIEW_FIELDS if key in item})
    return rows


def sanitize_public_review_list(body: dict[str, Any]) -> dict[str, Any]:
    return {**body, "items": public_review_items(body.get("items"))}


class CommunityOperations:
    async def list_community_reviews(self, slug: str) -> dict[str, Any]:
        self._validate_slug(slug)
        body = await self._require_marketplace().list_community_reviews(slug)
        return sanitize_public_review_list(body)

    async def list_community_review_page(
        self,
        slug: str,
        *,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_REVIEW_PAGE_SIZE,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        page, page_size = validate_catalog_page(page=page, page_size=page_size)
        body = await self._require_marketplace().list_community_review_page(
            slug,
            page=page,
            page_size=page_size,
        )
        return sanitize_public_review_list(body)

    async def set_favorite(self, slug: str, *, favorited: bool) -> dict[str, Any]:
        self._validate_slug(slug)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().set_favorite(
                slug,
                favorited=favorited,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def upsert_community_review(
        self,
        slug: str,
        *,
        rating: int,
        body: str,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        if rating < 1 or rating > 5:
            raise LocalSkillError("invalid_rating", "评分必须在 1 到 5 之间")
        normalized_body = body.strip()
        if len(normalized_body) > 2000:
            raise LocalSkillError("invalid_review", "评价不能超过 2000 字")

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().upsert_community_review(
                slug,
                rating=rating,
                body=normalized_body,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def delete_community_review(
        self,
        slug: str,
        *,
        review_id: str,
        expected_updated_at: str,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        review_id = validate_review_id(review_id)
        expected_updated_at = validate_review_updated_at(expected_updated_at)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().delete_community_review(
                slug,
                review_id=review_id,
                expected_updated_at=expected_updated_at,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def report_skill(
        self,
        slug: str,
        *,
        reason: str,
        details: str,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        if reason not in REPORT_REASONS:
            raise LocalSkillError("invalid_report", "举报类型无效")
        normalized_details = details.strip()
        if len(normalized_details) > 2000:
            raise LocalSkillError("invalid_report", "举报说明不能超过 2000 字")

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().report_skill(
                slug,
                reason=reason,
                details=normalized_details,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def report_community_review(
        self,
        slug: str,
        *,
        review_id: str,
        expected_updated_at: str,
        reason: str,
        details: str,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        review_id = validate_review_id(review_id)
        expected_updated_at = validate_review_updated_at(expected_updated_at)
        if reason not in REPORT_REASONS:
            raise LocalSkillError("invalid_report", "举报类型无效")
        normalized_details = details.strip()
        if len(normalized_details) > 2000:
            raise LocalSkillError("invalid_report", "举报说明不能超过 2000 字")

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().report_community_review(
                slug,
                review_id,
                expected_updated_at=expected_updated_at,
                reason=reason,
                details=normalized_details,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)
