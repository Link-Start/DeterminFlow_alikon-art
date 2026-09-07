"""Local publishing and atomic installation for marketplace Skills."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from src.account.service import CoreAccountService
from src.skills.loader import SkillLoader
from src.skills.manager import SkillManager

from .catalog import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    DEFAULT_PRIVATE_PAGE_SIZE,
    FUNCTIONAL_CATEGORIES,
    annotate_installations,
    validate_author_status,
    validate_catalog_filters,
    validate_catalog_page,
    validate_feedback_id,
    validate_feedback_updated_at,
    validate_preview_pin,
    verified_preview_payload,
)
from .community import CommunityOperations
from .drafts import (
    PublishDraftStore,
    bind_draft_access,
    normalize_expected_revision,
    require_local_identity,
)
from .errors import LocalSkillError
from .installs import install_marketplace_skill
from .local_skills import (
    ALLOWED_PUBLISH_LICENSES,
    local_skill_preview,
    prepare_skill_upload,
    read_shareable_skill,
    require_publication_version,
    require_publish_license,
    require_skill_id,
    skill_identity,
    validate_skill_content,
)
from .operation_log import record_marketplace_operation
from .publish_metadata import require_publish_text_limits
from .ownership import SKILL_ID_PATTERN, installation_state, resolve_openable_skill
from .updates import update_marketplace_skill
from .portal import (
    MarketplaceRequestError,
    ResourceMarketplaceClient,
    resolve_marketplace_embed_url,
)

_SKILL_ID_PATTERN = SKILL_ID_PATTERN
_PUBLIC_RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_VERSION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_MAX_REASON_CHARS = 1000
_MARKETPLACE_TERMS_VERSION = "2026-09-06"


class SkillMarketplaceService(CommunityOperations):
    def __init__(
        self,
        *,
        data_dir: Path,
        skill_manager: SkillManager,
        marketplace: ResourceMarketplaceClient | None,
        account_session: CoreAccountService | None = None,
        embed_url: str | None = None,
        allow_loopback_http: bool = False,
    ) -> None:
        self.data_dir = data_dir.expanduser().resolve()
        self.skill_manager = skill_manager
        self.marketplace = marketplace
        self.account_session = account_session
        self.state_path = self.data_dir / "resource-marketplace" / "state.json"
        self._lock = asyncio.Lock()
        self._drafts = PublishDraftStore(
            self.data_dir / "resource-marketplace" / "drafts"
        )
        self._clear_legacy_session()
        self.embed_url = (
            resolve_marketplace_embed_url(
                marketplace.base_url,
                override=embed_url,
                allow_loopback_http=allow_loopback_http,
            )
            if marketplace is not None
            else None
        )

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.marketplace is not None,
            "signed_in": (
                self.marketplace is not None
                and self.account_session is not None
                and self.account_session.access_token() is not None
            ),
            "account_name": (
                self.account_session.public_name()
                if self.account_session is not None
                else None
            ),
            "marketplace_url": self.marketplace.base_url if self.marketplace else None,
            "embed_url": self.embed_url,
            "resource_types": ["skill", "prompt", "agent", "workflow", "rule"],
            "publishable_resource_types": ["skill"],
            "functional_categories": list(FUNCTIONAL_CATEGORIES),
        }

    async def login(self) -> dict[str, Any]:
        self._require_marketplace()
        if self.account_session is None:
            raise LocalSkillError("account_unavailable", "Core 账号服务尚未初始化", status_code=503)
        await self.account_session.login()
        return self.status()

    async def logout(self) -> dict[str, Any]:
        self._require_marketplace()
        if self.account_session is None:
            raise LocalSkillError("account_unavailable", "Core 账号服务尚未初始化", status_code=503)
        await self.account_session.logout()
        return self.status()

    async def list_skills(
        self,
        *,
        query: str = "",
        category: str = "all",
        sort: str = "updated",
    ) -> dict[str, Any]:
        validate_catalog_filters(category=category, sort=sort)
        catalog = await self._require_marketplace().list_skills(
            query=query,
            category=category,
            sort=sort,
        )
        return annotate_installations(catalog, self._installation_state)

    async def list_skill_page(
        self,
        *,
        query: str = "",
        category: str = "all",
        sort: str = "updated",
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PAGE_SIZE,
        favorites: bool | None = None,
    ) -> dict[str, Any]:
        validate_catalog_filters(category=category, sort=sort)
        page, page_size = validate_catalog_page(page=page, page_size=page_size)
        marketplace = self._require_marketplace()
        if favorites is True:

            async def operation(access_token: str) -> dict[str, Any]:
                return await marketplace.list_skill_page(
                    query=query,
                    category=category,
                    sort=sort,
                    page=page,
                    page_size=page_size,
                    favorites=True,
                    access_token=access_token,
                )

            catalog = await self._authenticated_request(operation)
        else:
            catalog = await marketplace.list_skill_page(
                query=query,
                category=category,
                sort=sort,
                page=page,
                page_size=page_size,
                favorites=False,
            )
        if (
            not isinstance(catalog, dict)
            or not isinstance(catalog.get("items"), list)
            or not isinstance(catalog.get("total"), int)
            or not isinstance(catalog.get("page"), int)
            or not isinstance(catalog.get("page_size"), int)
        ):
            raise LocalSkillError("invalid_response", "资源广场返回了无效分页", status_code=502)
        return annotate_installations(catalog, self._installation_state)

    async def preview_skill(
        self,
        slug: str,
        *,
        expected_version_id: str,
        expected_sha256: str,
    ) -> dict[str, str]:
        self._validate_slug(slug)
        expected_version_id, expected_sha256 = validate_preview_pin(
            expected_version_id=expected_version_id,
            expected_sha256=expected_sha256,
        )
        body = await self._require_marketplace().preview_skill(
            slug,
            expected_version_id=expected_version_id,
            expected_sha256=expected_sha256,
        )
        return verified_preview_payload(
            body,
            expected_version_id=expected_version_id,
            expected_sha256=expected_sha256,
        )

    async def open_installed_skill(self, slug: str) -> dict[str, Any]:
        skill_id = resolve_openable_skill(
            slug,
            skill_manager=self.skill_manager,
            marketplace_url=self.marketplace.base_url if self.marketplace else None,
        )
        return {"opened": True, "skill_id": skill_id}

    async def get_skill(self, slug: str) -> dict[str, Any]:
        self._validate_slug(slug)
        detail = await self._require_marketplace().get_skill(slug)
        detail = {**detail, "installation": self._installation_state(detail)}
        if self.account_session is None or self.account_session.access_token() is None:
            return {**detail, "viewer": None}

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().get_community_state(
                slug,
                access_token=access_token,
            )

        return {**detail, "viewer": await self._authenticated_request(operation)}

    async def eligible_local_skills(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for summary in self.skill_manager.get_skills_summary():
            skill_id = str(summary.get("id") or "")
            skill = self.skill_manager.get_skill(skill_id)
            if skill is None:
                continue
            try:
                path, content = read_shareable_skill(self.skill_manager, skill_id)
            except LocalSkillError:
                continue
            try:
                frontmatter, _body = SkillLoader._parse_skill_md(content.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue
            metadata = frontmatter.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            file_version = str(metadata.get("version") or frontmatter.get("version") or "")
            marketplace_metadata = metadata.get("marketplace")
            marketplace_metadata = (
                marketplace_metadata if isinstance(marketplace_metadata, dict) else {}
            )
            result.append(
                {
                    "resource_type": "skill",
                    "id": skill_id,
                    "name": summary.get("name") or skill_id,
                    "description": summary.get("description") or "",
                    "version": file_version,
                    "size_bytes": len(content),
                    "path": str(path),
                    "category": summary.get("category") or "uncategorized",
                    "author": summary.get("author") or "",
                    "tags": summary.get("tags") or [],
                    "compatibility": skill.requires_core or skill.compatibility,
                    "declared_license": skill.license,
                    "release_notes": marketplace_metadata.get("release_notes") or "",
                    "usage_guide": "",
                    "primary_locale": skill.language,
                    "required_tools": skill.required_tools,
                    "required_plugins": skill.required_plugins,
                    "required_apps": skill.required_apps,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "preflight": [
                        {"id": "ownership", "label": "资源归属", "passed": True},
                        {"id": "structure", "label": "单文件结构", "passed": True},
                        {"id": "encoding", "label": "UTF-8 编码", "passed": True},
                        {"id": "manifest", "label": "清单字段", "passed": True},
                        {"id": "size", "label": "文件大小", "passed": True},
                        {"id": "integrity", "label": "内容哈希", "passed": True},
                        {
                            "id": "version_format",
                            "label": "语义化版本",
                            "passed": bool(_SEMVER_PATTERN.fullmatch(file_version)),
                        },
                    ],
                }
            )
        if not result:
            return result

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().check_resource_names(
                [item["id"] for item in result],
                access_token=access_token,
            )

        checked = await self._authenticated_request(operation)
        rows = checked.get("items") if isinstance(checked, dict) else None
        statuses = {
            row.get("slug"): row.get("status")
            for row in rows or []
            if isinstance(row, dict)
        }
        labels = {
            "available": "资源名称可用",
            "owned": "资源名称归当前账号",
            "conflict": "资源名称已被其他作者使用",
        }
        for item in result:
            name_status = statuses.get(item["id"], "unknown")
            item["name_status"] = name_status
            item["preflight"].append(
                {
                    "id": "name_unique",
                    "label": labels.get(name_status, "资源名称检查失败"),
                    "passed": name_status in {"available", "owned"},
                }
            )
        return result

    @record_marketplace_operation("publish")
    async def publish(
        self,
        *,
        skill_id: str,
        resource_type: str,
        license_id: str,
        rights_confirmed: bool,
        terms_confirmed: bool,
        terms_version: str | None,
        metadata: dict[str, Any],
        expected_sha256: str | None = None,
        target_slug: str | None = None,
        publication_version: str | None = None,
    ) -> dict[str, Any]:
        if resource_type != "skill":
            raise LocalSkillError(
                "unsupported_resource_type",
                "当前仅开放 Skill 投稿",
                status_code=422,
            )
        if license_id not in ALLOWED_PUBLISH_LICENSES:
            raise LocalSkillError("invalid_license", "请选择支持的使用授权")
        if not rights_confirmed:
            raise LocalSkillError("rights_required", "必须确认拥有分享权利")
        if not terms_confirmed or terms_version != _MARKETPLACE_TERMS_VERSION:
            raise LocalSkillError("terms_required", "必须接受当前作者发布协议")
        require_publish_text_limits(metadata)
        _path, content = read_shareable_skill(self.skill_manager, skill_id)
        locked_target = require_skill_id(target_slug) if target_slug else None
        prepared_version = (
            require_publication_version(publication_version)
            if publication_version
            else None
        )
        if locked_target is not None and prepared_version is None:
            raise LocalSkillError("invalid_version", "发布版本必须是有效的语义化版本")
        if locked_target is not None or prepared_version is not None:
            source_name, source_version = skill_identity(content)
            prepared = prepare_skill_upload(
                content,
                name=locked_target or source_name,
                version=prepared_version or source_version,
            )
        else:
            prepared = content
        require_publish_license(license_id, content=prepared)
        digest = hashlib.sha256(prepared).hexdigest()
        if expected_sha256 is not None:
            pinned = self._validate_sha256(expected_sha256)
            if digest != pinned:
                raise LocalSkillError(
                    "local_skill_changed",
                    "本地 Skill 已变化，请重新预览后提交",
                    status_code=409,
                )

        async def upload(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().publish_skill(
                content=prepared,
                license_id=license_id,
                rights_confirmed=rights_confirmed,
                resource_type=resource_type,
                metadata=metadata,
                terms_confirmed=terms_confirmed,
                terms_version=terms_version,
                access_token=access_token,
                target_slug=locked_target,
                publication_version=prepared_version,
            )

        return await self._authenticated_request(upload)

    async def get_publish_draft(self, skill_id: str) -> dict[str, Any]:
        access = bind_draft_access(self.account_session, self._require_marketplace().base_url)
        draft, last_source_skill_id = await self._drafts.get(
            **access,
            skill_id=skill_id,
        )
        return {
            "draft": draft,
            "last_source_skill_id": last_source_skill_id or None,
        }

    async def save_publish_draft(
        self,
        skill_id: str,
        *,
        expected_revision: int | None,
        base_version: str,
        base_sha256: str,
        fields: dict[str, Any],
        source_skill_id: str = "",
        publication_version: str = "",
    ) -> dict[str, Any]:
        access = bind_draft_access(self.account_session, self._require_marketplace().base_url)
        require_skill_id(skill_id)
        source = source_skill_id.strip() if isinstance(source_skill_id, str) else ""
        if source:
            read_shareable_skill(self.skill_manager, require_skill_id(source))
        else:
            read_shareable_skill(self.skill_manager, skill_id)
        draft = await self._drafts.save(
            **access,
            skill_id=skill_id,
            expected_revision=normalize_expected_revision(
                expected_revision,
                allow_null=True,
            ),
            base_version=base_version,
            base_sha256=base_sha256,
            fields=fields,
            source_skill_id=source,
            publication_version=publication_version,
        )
        return {"draft": draft}

    async def delete_publish_draft(
        self,
        skill_id: str,
        *,
        expected_revision: int,
    ) -> dict[str, bool]:
        access = bind_draft_access(self.account_session, self._require_marketplace().base_url)
        return await self._drafts.delete(
            **access,
            skill_id=skill_id,
            expected_revision=normalize_expected_revision(
                expected_revision,
                allow_null=False,
            ),
        )

    async def preview_local_skill(
        self,
        skill_id: str,
        *,
        target_slug: str | None = None,
        publication_version: str | None = None,
    ) -> dict[str, str]:
        self._require_draft_identity()
        return local_skill_preview(
            self.skill_manager,
            require_skill_id(skill_id),
            target_slug=target_slug,
            publication_version=publication_version,
        )

    async def list_author_resources(
        self,
        *,
        query: str = "",
        status: str = "all",
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PRIVATE_PAGE_SIZE,
    ) -> dict[str, Any]:
        status = validate_author_status(status)
        page, page_size = validate_catalog_page(page=page, page_size=page_size)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().list_author_resources(
                query=query,
                status=status,
                page=page,
                page_size=page_size,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def list_author_versions(
        self,
        slug: str,
        *,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PRIVATE_PAGE_SIZE,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        page, page_size = validate_catalog_page(page=page, page_size=page_size)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().list_author_versions(
                slug,
                page=page,
                page_size=page_size,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def list_feedback(
        self,
        *,
        page: int = DEFAULT_PAGE,
        page_size: int = DEFAULT_PRIVATE_PAGE_SIZE,
        unread_only: bool = False,
    ) -> dict[str, Any]:
        page, page_size = validate_catalog_page(page=page, page_size=page_size)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().list_feedback(
                page=page,
                page_size=page_size,
                unread_only=unread_only,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def mark_feedback_read(
        self,
        *,
        feedback_id: str,
        expected_updated_at: str,
    ) -> dict[str, Any]:
        feedback_id = validate_feedback_id(feedback_id)
        expected_updated_at = validate_feedback_updated_at(expected_updated_at)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().mark_feedback_read(
                feedback_id=feedback_id,
                expected_updated_at=expected_updated_at,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def list_submissions(self) -> dict[str, Any]:
        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().list_submissions(
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def get_submission(self, version_id: str) -> dict[str, Any]:
        normalized = self._validate_version_id(version_id)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().get_submission(
                normalized,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def withdraw_submission(self, version_id: str) -> dict[str, Any]:
        normalized = self._validate_version_id(version_id)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().withdraw_submission(
                normalized,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def list_review_queue(self) -> dict[str, Any]:
        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().list_review_queue(
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def get_review_item(self, version_id: str) -> dict[str, Any]:
        normalized = self._validate_version_id(version_id)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().get_review_item(
                normalized,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def review_version(
        self,
        version_id: str,
        *,
        decision: str,
        expected_sha256: str,
        reason: str | None = None,
        expected_current_version_id: str | None = None,
        expected_current_version_provided: bool = False,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise LocalSkillError("invalid_decision", "审核决定无效")
        normalized_id = self._validate_version_id(version_id)
        digest = self._validate_sha256(expected_sha256)
        normalized_reason = self._validate_reason(reason, required=(decision == "reject"))
        current_id = (
            self._validate_version_id(expected_current_version_id)
            if expected_current_version_id is not None
            else None
        )

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().review_version(
                normalized_id,
                decision=decision,
                expected_sha256=digest,
                reason=normalized_reason,
                expected_current_version_id=current_id,
                expected_current_version_provided=expected_current_version_provided,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def suspend_skill(
        self,
        slug: str,
        *,
        expected_version_id: str,
        reason: str,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        version_id = self._validate_version_id(expected_version_id)
        normalized_reason = self._validate_reason(reason, required=True)
        if normalized_reason is None:
            raise LocalSkillError("reason_required", "下架必须填写原因")

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().suspend_skill(
                slug,
                expected_version_id=version_id,
                reason=normalized_reason,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def resume_skill(
        self,
        slug: str,
        *,
        expected_version_id: str,
        reason: str,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        version_id = self._validate_version_id(expected_version_id)
        normalized_reason = self._validate_reason(reason, required=True)
        if normalized_reason is None:
            raise LocalSkillError("reason_required", "恢复上架必须填写原因")

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().resume_skill(
                slug,
                expected_version_id=version_id,
                reason=normalized_reason,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    async def update_skill_lifecycle(
        self,
        slug: str,
        *,
        deprecated: bool,
        replacement_slug: str | None,
        message: str | None,
    ) -> dict[str, Any]:
        self._validate_slug(slug)
        replacement = replacement_slug.strip() if isinstance(replacement_slug, str) else None
        if replacement:
            self._validate_slug(replacement)
        guidance = self._validate_reason(message, required=deprecated)

        async def operation(access_token: str) -> dict[str, Any]:
            return await self._require_marketplace().update_skill_lifecycle(
                slug,
                deprecated=deprecated,
                replacement_slug=replacement,
                message=guidance,
                access_token=access_token,
            )

        return await self._authenticated_request(operation)

    def _installation_state(self, detail: dict[str, Any]) -> dict[str, Any]:
        return installation_state(
            detail,
            skill_manager=self.skill_manager,
            marketplace_url=self.marketplace.base_url if self.marketplace else None,
        )

    @record_marketplace_operation("install")
    async def install(
        self,
        slug: str,
        *,
        expected_version_id: str,
        expected_sha256: str,
    ) -> dict[str, Any]:
        return await install_marketplace_skill(
            self,
            slug,
            expected_version_id=expected_version_id,
            expected_sha256=expected_sha256,
        )

    @record_marketplace_operation("update")
    async def update(
        self,
        slug: str,
        *,
        expected_version_id: str,
        expected_sha256: str,
    ) -> dict[str, Any]:
        return await update_marketplace_skill(
            self,
            slug,
            expected_version_id=expected_version_id,
            expected_sha256=expected_sha256,
        )

    async def _authenticated_request(self, operation):
        self._require_marketplace()
        account = self.account_session
        if account is None:
            raise LocalSkillError("account_unavailable", "Core 账号服务尚未初始化", status_code=503)
        access_token = account.access_token()
        if access_token is None:
            raise LocalSkillError("login_required", "请先登录 DeterminFlow", status_code=401)
        session_id = account.current_session_id()

        def session_changed() -> bool:
            return not account.is_current_session(session_id)

        try:
            result = await operation(access_token)
            if session_changed():
                raise LocalSkillError(
                    "login_required", "登录状态已变化，请重试", status_code=401,
                )
            return result
        except MarketplaceRequestError as exc:
            if exc.code != "authentication_failed":
                raise

        if session_changed():
            raise LocalSkillError(
                "login_required", "登录状态已变化，请重试", status_code=401,
            )
        refreshed_token = await account.refresh_access_token(access_token)
        if refreshed_token is None or session_changed():
            raise LocalSkillError(
                "login_required", "账号登录已失效，请重新登录", status_code=401,
            )
        result = await operation(refreshed_token)
        if session_changed():
            raise LocalSkillError(
                "login_required", "登录状态已变化，请重试", status_code=401,
            )
        return result

    def _require_draft_identity(self) -> tuple[str, str]:
        marketplace = self._require_marketplace()
        return require_local_identity(self.account_session, marketplace.base_url)

    def _read_shareable_skill(self, skill_id: str) -> tuple[Path, bytes]:
        return read_shareable_skill(self.skill_manager, skill_id)

    @staticmethod
    def _validate_skill_content(content: bytes) -> str:
        return validate_skill_content(content)

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if not _SKILL_ID_PATTERN.fullmatch(slug):
            raise LocalSkillError("invalid_slug", "Skill 标识格式无效")

    @staticmethod
    def _validate_version_id(version_id: str) -> str:
        value = version_id.strip()
        if not _VERSION_ID_PATTERN.fullmatch(value):
            raise LocalSkillError("invalid_version_id", "版本标识格式无效")
        return str(UUID(value))

    @staticmethod
    def _require_public_id(value: Any, field: str) -> str:
        if not isinstance(
            value, str
        ) or not _PUBLIC_RESOURCE_ID_PATTERN.fullmatch(value):
            raise LocalSkillError(
                "missing_provenance",
                f"资源广场详情缺少可信 {field}",
                status_code=502,
            )
        return value

    @staticmethod
    def _validate_sha256(digest: str) -> str:
        if not _SHA256_PATTERN.fullmatch(digest):
            raise LocalSkillError("invalid_digest", "内容摘要必须是 64 位小写十六进制")
        return digest

    @staticmethod
    def _validate_reason(reason: str | None, *, required: bool) -> str | None:
        text = reason.strip() if isinstance(reason, str) else ""
        if required and not text:
            raise LocalSkillError("reason_required", "必须填写原因")
        if len(text) > _MAX_REASON_CHARS:
            raise LocalSkillError("reason_too_long", "原因不能超过 1000 字")
        return text or None

    def _clear_legacy_session(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(state, dict) or state.get("marketplace_session") is None:
            return
        state["marketplace_session"] = None
        temporary = self.state_path.with_suffix(".json.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _require_marketplace(self) -> ResourceMarketplaceClient:
        if self.marketplace is None:
            raise LocalSkillError(
                "marketplace_not_configured",
                "资源广场服务尚未配置",
                status_code=503,
            )
        return self.marketplace
