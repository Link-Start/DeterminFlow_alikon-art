"""Desktop-local API routes for the Resource Marketplace."""

from __future__ import annotations

import ipaddress
import os
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.account.portal import AccountRequestError

from .catalog import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DEFAULT_PRIVATE_PAGE_SIZE,
    DEFAULT_REVIEW_PAGE_SIZE,
    parse_favorites_flag,
    parse_unread_only_flag,
)
from .portal import MarketplaceRequestError
from .publish_metadata import PUBLISH_TEXT_LIMITS
from .service import LocalSkillError, SkillMarketplaceService

router = APIRouter(prefix="/api/resource-marketplace", tags=["resource-marketplace"])


class PublishMetadata(BaseModel):
    display_name: str = Field(default="", max_length=80)
    author_name: str = Field(default="", max_length=80)
    summary: str = Field(default="", max_length=PUBLISH_TEXT_LIMITS["summary"])
    functional_category: str = Field(default="general", max_length=32)
    primary_locale: str = Field(default="und", max_length=16)
    tags: list[str] = Field(default_factory=list, max_length=20)
    release_notes: str = Field(default="", max_length=PUBLISH_TEXT_LIMITS["release_notes"])
    usage_guide: str = Field(default="", max_length=PUBLISH_TEXT_LIMITS["usage_guide"])


class PublishRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=64)
    resource_type: Literal["skill"] = "skill"
    license: str = Field(min_length=1, max_length=32)
    rights_confirmed: bool
    terms_confirmed: bool = False
    terms_version: str | None = Field(default=None, max_length=32)
    metadata: PublishMetadata | None = None
    expected_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    target_slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    publication_version: str | None = Field(default=None, min_length=1, max_length=64)


class ReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    expected_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    reason: str | None = Field(default=None, max_length=1000)
    expected_current_version_id: str | None = Field(default=None, max_length=64)


class DraftFieldsBody(BaseModel):
    license: str = Field(default="", max_length=32)
    display_name: str = Field(default="", max_length=80)
    author_name: str = Field(default="", max_length=80)
    summary: str = Field(default="", max_length=1024)
    functional_category: str = Field(default="", max_length=32)
    primary_locale: str = Field(default="", max_length=16)
    tags_csv: str = Field(default="", max_length=680)
    release_notes: str = Field(default="", max_length=2000)
    usage_guide: str = Field(default="", max_length=8000)


class SaveDraftRequest(BaseModel):
    expected_revision: int | None = Field(default=None, strict=True, ge=1, le=2_147_483_647)
    base_version: str = Field(max_length=64)
    base_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    fields: DraftFieldsBody
    source_skill_id: str = Field(default="", max_length=64)
    publication_version: str = Field(default="", max_length=64)


class DeleteDraftRequest(BaseModel):
    expected_revision: int = Field(strict=True, ge=1, le=2_147_483_647)


class FeedbackReadRequest(BaseModel):
    id: str = Field(min_length=1, max_length=80)
    expected_updated_at: str = Field(min_length=1, max_length=64)


class SuspendRequest(BaseModel):
    expected_version_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)


class LifecycleRequest(BaseModel):
    deprecated: bool
    replacement_slug: str | None = Field(default=None, max_length=64)
    message: str | None = Field(default=None, max_length=1000)


class FavoriteRequest(BaseModel):
    favorited: bool


class InstallRequest(BaseModel):
    expected_version_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    expected_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class CommunityReviewRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str = Field(default="", max_length=2000)


class DeleteCommunityReviewRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=64)
    expected_updated_at: str = Field(min_length=1, max_length=64)


class ReportSkillRequest(BaseModel):
    reason: Literal["security", "misleading", "copyright", "spam", "other"]
    details: str = Field(default="", max_length=2000)


class ReportCommunityReviewRequest(BaseModel):
    expected_updated_at: str = Field(min_length=1, max_length=64)
    reason: Literal["security", "misleading", "copyright", "spam", "other"]
    details: str = Field(default="", max_length=2000)


def _service(request: Request) -> SkillMarketplaceService:
    if os.getenv("DETERMINFLOW_DESKTOP") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    origin = request.headers.get("origin")
    try:
        local_peer = (
            request.client is not None
            and ipaddress.ip_address(request.client.host).is_loopback
        )
        local_host = _loopback_host(request.url.hostname)
        local_origin = not origin or (
            urlsplit(origin).scheme in {"http", "https"}
            and _loopback_host(urlsplit(origin).hostname)
        )
    except ValueError:
        local_peer = local_host = local_origin = False
    if not (local_peer and local_host and local_origin):
        raise HTTPException(status_code=403, detail="资源广场桌面接口仅允许本机访问")
    service = getattr(request.app.state, "resource_marketplace_service", None)
    if not isinstance(service, SkillMarketplaceService):
        raise HTTPException(status_code=503, detail="资源广场尚未初始化")
    return service


def _loopback_host(host: str | None) -> bool:
    if host == "localhost":
        return True
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _private(payload: object) -> JSONResponse:
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


def _raise_user_error(exc: Exception) -> None:
    if isinstance(exc, (AccountRequestError, LocalSkillError, MarketplaceRequestError)):
        headers = {"Cache-Control": "no-store"}
        detail: dict[str, object] = {"code": exc.code, "message": exc.message}
        retry_after = getattr(exc, "retry_after_seconds", None)
        if isinstance(retry_after, int) and 1 <= retry_after <= 3600:
            detail["retry_after_seconds"] = retry_after
            headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
            headers=headers,
        ) from exc
    raise exc


@router.get("/status")
async def status(request: Request):
    service = _service(request)
    refresh_profile = getattr(service.account_session, "refresh_public_name", None)
    if callable(refresh_profile):
        await refresh_profile()
    return service.status()


@router.post("/login")
async def login(request: Request):
    try:
        return await _service(request).login()
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/logout")
async def logout(request: Request):
    try:
        return await _service(request).logout()
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/skills")
async def list_skills(
    request: Request,
    q: Annotated[str, Query(max_length=64)] = "",
    category: Annotated[str, Query(max_length=32)] = "all",
    sort: Annotated[str, Query(max_length=16)] = "updated",
):
    try:
        return await _service(request).list_skills(query=q, category=category, sort=sort)
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/catalog/skills")
async def list_skill_page(
    request: Request,
    q: Annotated[str, Query(max_length=64)] = "",
    category: Annotated[str, Query(max_length=32)] = "all",
    sort: Annotated[str, Query(max_length=16)] = "updated",
    page: Annotated[int, Query()] = DEFAULT_PAGE,
    page_size: Annotated[int, Query()] = DEFAULT_PAGE_SIZE,
    favorites: Annotated[str | None, Query(max_length=5)] = None,
):
    try:
        return await _service(request).list_skill_page(
            query=q,
            category=category,
            sort=sort,
            page=page,
            page_size=page_size,
            favorites=parse_favorites_flag(favorites),
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/skills/{slug}/preview")
async def preview_skill(
    slug: str,
    request: Request,
    expected_version_id: Annotated[
        str,
        Query(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"),
    ],
    expected_sha256: Annotated[
        str,
        Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
    ],
):
    try:
        return await _service(request).preview_skill(
            slug,
            expected_version_id=expected_version_id,
            expected_sha256=expected_sha256,
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/skills/{slug}/open-installed")
async def open_installed_skill(slug: str, request: Request):
    try:
        return _private(await _service(request).open_installed_skill(slug))
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/skills/{slug}")
async def get_skill(slug: str, request: Request):
    try:
        return _private(await _service(request).get_skill(slug))
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/skills/{slug}/reviews")
async def list_community_reviews(slug: str, request: Request):
    try:
        return _private(await _service(request).list_community_reviews(slug))
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/skills/{slug}/reviews/page")
async def list_community_review_page(
    slug: str,
    request: Request,
    page: Annotated[int, Query()] = DEFAULT_PAGE,
    page_size: Annotated[int, Query()] = DEFAULT_REVIEW_PAGE_SIZE,
):
    try:
        return _private(
            await _service(request).list_community_review_page(
                slug,
                page=page,
                page_size=page_size,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.put("/skills/{slug}/favorite")
async def set_favorite(slug: str, payload: FavoriteRequest, request: Request):
    try:
        return _private(
            await _service(request).set_favorite(slug, favorited=payload.favorited)
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.put("/skills/{slug}/review")
async def upsert_community_review(
    slug: str,
    payload: CommunityReviewRequest,
    request: Request,
):
    try:
        return _private(
            await _service(request).upsert_community_review(
                slug,
                rating=payload.rating,
                body=payload.body,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.delete("/skills/{slug}/review")
async def delete_community_review(
    slug: str,
    payload: DeleteCommunityReviewRequest,
    request: Request,
):
    try:
        return _private(
            await _service(request).delete_community_review(
                slug,
                review_id=payload.review_id,
                expected_updated_at=payload.expected_updated_at,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/skills/{slug}/report")
async def report_skill(slug: str, payload: ReportSkillRequest, request: Request):
    try:
        return _private(
            await _service(request).report_skill(
                slug,
                reason=payload.reason,
                details=payload.details,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/skills/{slug}/reviews/{review_id}/report")
async def report_community_review(
    slug: str,
    review_id: str,
    payload: ReportCommunityReviewRequest,
    request: Request,
):
    try:
        return _private(
            await _service(request).report_community_review(
                slug,
                review_id=review_id,
                expected_updated_at=payload.expected_updated_at,
                reason=payload.reason,
                details=payload.details,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/eligible-skills")
async def eligible_skills(request: Request):
    try:
        return {"items": await _service(request).eligible_local_skills()}
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/publish")
async def publish(payload: PublishRequest, request: Request):
    try:
        return _private(
            await _service(request).publish(
                skill_id=payload.skill_id,
                resource_type=payload.resource_type,
                license_id=payload.license,
                rights_confirmed=payload.rights_confirmed,
                terms_confirmed=payload.terms_confirmed,
                terms_version=payload.terms_version,
                metadata=payload.metadata.model_dump(exclude_none=True) if payload.metadata else {},
                expected_sha256=payload.expected_sha256,
                target_slug=payload.target_slug,
                publication_version=payload.publication_version,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/publish-drafts/{skill_id}")
async def get_publish_draft(skill_id: str, request: Request):
    try:
        return _private(await _service(request).get_publish_draft(skill_id))
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.put("/publish-drafts/{skill_id}")
async def save_publish_draft(skill_id: str, payload: SaveDraftRequest, request: Request):
    try:
        return _private(
            await _service(request).save_publish_draft(
                skill_id,
                expected_revision=payload.expected_revision,
                base_version=payload.base_version,
                base_sha256=payload.base_sha256,
                fields=payload.fields.model_dump(),
                source_skill_id=payload.source_skill_id,
                publication_version=payload.publication_version,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.delete("/publish-drafts/{skill_id}")
async def delete_publish_draft(
    skill_id: str,
    payload: DeleteDraftRequest,
    request: Request,
):
    try:
        return _private(
            await _service(request).delete_publish_draft(
                skill_id,
                expected_revision=payload.expected_revision,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/local-skills/{skill_id}/preview")
async def preview_local_skill(
    skill_id: str,
    request: Request,
    target_slug: Annotated[str | None, Query(max_length=64)] = None,
    publication_version: Annotated[str | None, Query(max_length=64)] = None,
):
    try:
        return _private(
            await _service(request).preview_local_skill(
                skill_id,
                target_slug=target_slug,
                publication_version=publication_version,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/author/resources")
async def list_author_resources(
    request: Request,
    q: Annotated[str, Query(max_length=64)] = "",
    status: Annotated[str, Query(max_length=32)] = "all",
    page: Annotated[int, Query()] = DEFAULT_PAGE,
    page_size: Annotated[int, Query()] = DEFAULT_PRIVATE_PAGE_SIZE,
):
    try:
        return _private(
            await _service(request).list_author_resources(
                query=q,
                status=status,
                page=page,
                page_size=page_size,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/author/resources/{slug}/versions")
async def list_author_versions(
    slug: str,
    request: Request,
    page: Annotated[int, Query()] = DEFAULT_PAGE,
    page_size: Annotated[int, Query()] = DEFAULT_PRIVATE_PAGE_SIZE,
):
    try:
        return _private(
            await _service(request).list_author_versions(
                slug,
                page=page,
                page_size=page_size,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/feedback")
async def list_feedback(
    request: Request,
    page: Annotated[int, Query()] = DEFAULT_PAGE,
    page_size: Annotated[int, Query()] = DEFAULT_PRIVATE_PAGE_SIZE,
    unread_only: Annotated[str | None, Query(max_length=5)] = None,
):
    try:
        return _private(
            await _service(request).list_feedback(
                page=page,
                page_size=page_size,
                unread_only=parse_unread_only_flag(unread_only),
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/feedback/read")
async def mark_feedback_read(payload: FeedbackReadRequest, request: Request):
    try:
        return _private(
            await _service(request).mark_feedback_read(
                feedback_id=payload.id,
                expected_updated_at=payload.expected_updated_at,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/skills/{slug}/install")
async def install(slug: str, payload: InstallRequest, request: Request):
    try:
        return _private(
            await _service(request).install(
                slug,
                expected_version_id=payload.expected_version_id,
                expected_sha256=payload.expected_sha256,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/skills/{slug}/update")
async def update(slug: str, payload: InstallRequest, request: Request):
    try:
        return _private(
            await _service(request).update(
                slug,
                expected_version_id=payload.expected_version_id,
                expected_sha256=payload.expected_sha256,
            )
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/submissions")
async def list_submissions(request: Request):
    try:
        return await _service(request).list_submissions()
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/submissions/{version_id}")
async def get_submission(version_id: str, request: Request):
    try:
        return await _service(request).get_submission(version_id)
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/submissions/{version_id}/withdraw")
async def withdraw_submission(version_id: str, request: Request):
    try:
        return await _service(request).withdraw_submission(version_id)
    except (LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/review-queue")
async def list_review_queue(request: Request):
    try:
        return await _service(request).list_review_queue()
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.get("/review-queue/{version_id}")
async def get_review_item(version_id: str, request: Request):
    try:
        return await _service(request).get_review_item(version_id)
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/reviews/{version_id}")
async def review_version(version_id: str, payload: ReviewRequest, request: Request):
    try:
        return await _service(request).review_version(
            version_id,
            decision=payload.decision,
            expected_sha256=payload.expected_sha256,
            reason=payload.reason,
            expected_current_version_id=payload.expected_current_version_id,
            expected_current_version_provided="expected_current_version_id" in payload.model_fields_set,
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/skills/{slug}/suspend")
async def suspend_skill(slug: str, payload: SuspendRequest, request: Request):
    try:
        return await _service(request).suspend_skill(
            slug,
            expected_version_id=payload.expected_version_id,
            reason=payload.reason,
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.post("/skills/{slug}/resume")
async def resume_skill(slug: str, payload: SuspendRequest, request: Request):
    try:
        return await _service(request).resume_skill(
            slug,
            expected_version_id=payload.expected_version_id,
            reason=payload.reason,
        )
    except (LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)


@router.patch("/skills/{slug}/lifecycle")
async def update_skill_lifecycle(
    slug: str,
    payload: LifecycleRequest,
    request: Request,
):
    try:
        return await _service(request).update_skill_lifecycle(
            slug,
            deprecated=payload.deprecated,
            replacement_slug=payload.replacement_slug,
            message=payload.message,
        )
    except (AccountRequestError, LocalSkillError, MarketplaceRequestError) as exc:
        _raise_user_error(exc)
