"""Catalog query validation and preview integrity checks."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from .errors import LocalSkillError
from .bundle import unpack

MAX_SKILL_BYTES = 256 * 1024
DEFAULT_PAGE = 1
MAX_PAGE = 100_000
DEFAULT_PAGE_SIZE = 24
DEFAULT_PRIVATE_PAGE_SIZE = 20
DEFAULT_REVIEW_PAGE_SIZE = 20
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 100
AUTHOR_RESOURCE_STATUSES = frozenset(
    {
        "all",
        "published",
        "pending",
        "changes",
        "suspended",
        "deprecated",
        "withdrawn",
    }
)
_FEEDBACK_ID_PATTERN = re.compile(
    r"^(?:submission|report):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
REPORT_REASONS = frozenset({"security", "misleading", "copyright", "spam", "other"})
FUNCTIONAL_CATEGORIES = (
    "general",
    "novel",
    "comic-drama",
    "media",
    "development",
    "productivity",
    "business",
    "education",
    "other",
)
LEGACY_SKILL_CATEGORIES = frozenset(
    {"coding", "research", "communication", "memory", "workflow", "domain"}
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def validate_catalog_filters(*, category: str, sort: str) -> None:
    if (
        category != "all"
        and category not in FUNCTIONAL_CATEGORIES
        and category not in LEGACY_SKILL_CATEGORIES
    ):
        raise LocalSkillError("invalid_category", "资源分类无效")
    if sort not in {"updated", "popular"}:
        raise LocalSkillError("invalid_sort", "排序方式无效")


def validate_catalog_page(*, page: int, page_size: int) -> tuple[int, int]:
    if not isinstance(page, int) or page < 1 or page > MAX_PAGE:
        raise LocalSkillError("invalid_page", "页码必须是 1 到 100000 的整数")
    if (
        not isinstance(page_size, int)
        or page_size < MIN_PAGE_SIZE
        or page_size > MAX_PAGE_SIZE
    ):
        raise LocalSkillError("invalid_page_size", "每页数量必须是 1 到 100 的整数")
    return page, page_size


def validate_author_status(status: str) -> str:
    value = status.strip() or "all"
    if value not in AUTHOR_RESOURCE_STATUSES:
        raise LocalSkillError("invalid_status", "作者资源状态筛选无效")
    return value


def parse_unread_only_flag(value: str | None) -> bool:
    if value is None or value == "" or value == "false":
        return False
    if value == "true":
        return True
    raise LocalSkillError("invalid_unread_only", "未读筛选只能是 true 或 false")


def validate_feedback_id(value: str) -> str:
    text = value.strip()
    if not _FEEDBACK_ID_PATTERN.fullmatch(text):
        raise LocalSkillError("invalid_feedback_id", "反馈标识格式无效")
    return text


def validate_feedback_updated_at(value: str) -> str:
    text = value.strip()
    if not text or len(text) > 64:
        raise LocalSkillError("invalid_feedback", "反馈修订时间无效")
    return text


def validate_review_id(value: str) -> str:
    text = value.strip()
    if not _UUID_PATTERN.fullmatch(text):
        raise LocalSkillError("invalid_review_id", "评价标识格式无效")
    return str(UUID(text))


def validate_review_updated_at(value: str) -> str:
    text = value.strip()
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
        text,
    ):
        raise LocalSkillError("invalid_review", "评价修订时间无效")
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LocalSkillError("invalid_review", "评价修订时间无效") from exc
    return text


def parse_favorites_flag(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise LocalSkillError("invalid_favorites", "收藏筛选只能是 true 或 false")


def validate_preview_pin(*, expected_version_id: str, expected_sha256: str) -> tuple[str, str]:
    version_id = expected_version_id.strip()
    digest = expected_sha256.strip()
    if not _PUBLIC_RESOURCE_ID_PATTERN.fullmatch(version_id):
        raise LocalSkillError("invalid_version_id", "版本标识格式无效")
    if not _SHA256_PATTERN.fullmatch(digest):
        raise LocalSkillError("invalid_digest", "内容摘要必须是 64 位小写十六进制")
    return version_id, digest


def verified_preview_payload(
    body: dict[str, Any],
    *,
    expected_version_id: str,
    expected_sha256: str,
) -> dict[str, str]:
    content = body.get("content")
    version_id = body.get("version_id")
    digest = body.get("sha256")
    if not isinstance(content, str) or not isinstance(version_id, str) or not isinstance(digest, str):
        raise LocalSkillError("invalid_response", "资源广场返回了无效预览", status_code=502)
    if "\x00" in content:
        raise LocalSkillError("invalid_encoding", "SKILL.md 必须是 UTF-8 文本")
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LocalSkillError("invalid_encoding", "SKILL.md 必须是 UTF-8 文本") from exc
    unpack(encoded)
    actual_digest = hashlib.sha256(encoded).hexdigest()
    if version_id != expected_version_id:
        raise LocalSkillError(
            "version_changed",
            "资源版本已变化，请刷新详情后重新确认",
            status_code=409,
        )
    if actual_digest != expected_sha256 or digest != expected_sha256:
        raise LocalSkillError("integrity_mismatch", "Skill 预览完整性校验失败", status_code=502)
    return {
        "content": content,
        "version_id": version_id,
        "sha256": actual_digest,
    }


def annotate_installations(catalog: dict[str, Any], installation_state) -> dict[str, Any]:
    return {
        **catalog,
        "items": [
            {**item, "installation": installation_state(item)}
            for item in catalog.get("items", [])
            if isinstance(item, dict)
        ],
    }
