"""Limits for new submissions; legacy drafts and local packages keep their limits."""

from typing import Any

from .errors import LocalSkillError

PUBLISH_TEXT_LIMITS = {"summary": 50, "release_notes": 150, "usage_guide": 1000}
_FIELD_LABELS = {"summary": "资源简介", "release_notes": "版本说明", "usage_guide": "详细使用说明"}


def require_publish_text_limits(metadata: dict[str, Any]) -> None:
    for field, limit in PUBLISH_TEXT_LIMITS.items():
        if field not in metadata:
            continue
        value = metadata[field]
        if not isinstance(value, str) or len(value) > limit:
            raise LocalSkillError(
                "invalid_metadata",
                f"{_FIELD_LABELS[field]}（{field}）请限制在 {limit} 字以内",
                status_code=422,
            )
