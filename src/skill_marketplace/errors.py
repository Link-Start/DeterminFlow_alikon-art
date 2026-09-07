"""User-facing marketplace errors that routes can translate safely."""

from __future__ import annotations

from typing import Any

MAX_RETRY_AFTER_SECONDS = 3600


def normalize_retry_after_seconds(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and value.strip().isdigit():
        seconds = int(value.strip())
    else:
        return None
    if 1 <= seconds <= MAX_RETRY_AFTER_SECONDS:
        return seconds
    return None


class LocalSkillError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retry_after_seconds = normalize_retry_after_seconds(retry_after_seconds)
