"""Privacy-safe structured logs for local marketplace install and publish."""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger("determinflow.marketplace.operations")

ALLOWED_OPERATIONS = frozenset({"install", "publish", "update"})
ALLOWED_RESULTS = frozenset({"success", "failure"})
ALLOWED_ERROR_CODES = frozenset(
    {
        "already_exists",
        "account_unavailable",
        "attachments_not_allowed",
        "authentication_failed",
        "conflict",
        "config_unavailable",
        "forbidden",
        "identity_mismatch",
        "identity_unavailable",
        "integrity_mismatch",
        "internal_error",
        "invalid_body",
        "invalid_description",
        "invalid_digest",
        "invalid_encoding",
        "invalid_integrity",
        "invalid_license",
        "invalid_name",
        "invalid_response",
        "invalid_size",
        "invalid_skill",
        "invalid_slug",
        "local_skill_changed",
        "login_changed",
        "login_required",
        "local_modified",
        "marketplace_not_configured",
        "network_unavailable",
        "missing_provenance",
        "no_update",
        "not_found",
        "not_user_owned",
        "rate_limited",
        "request_failed",
        "read_failed",
        "rights_required",
        "terms_required",
        "too_large",
        "unsupported_resource_type",
        "version_changed",
    }
)
LOG_FIELDS = frozenset({"operation", "result", "error_code", "duration_ms"})

P = ParamSpec("P")
T = TypeVar("T")


def emit_marketplace_operation(
    *,
    operation: str,
    result: str,
    duration_ms: int,
    error_code: str | None = None,
) -> None:
    """Write one allowlisted outcome. Unknown fields and secrets are dropped."""
    if operation not in ALLOWED_OPERATIONS or result not in ALLOWED_RESULTS:
        return
    payload: dict[str, Any] = {
        "operation": operation,
        "result": result,
        "duration_ms": max(0, int(duration_ms)),
    }
    if result == "failure":
        payload["error_code"] = (
            error_code if error_code in ALLOWED_ERROR_CODES else "internal_error"
        )
    try:
        logger.log(
            logging.INFO if result == "success" else logging.WARNING,
            "marketplace_operation %s",
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            extra={"df_marketplace": dict(payload)},
        )
    except Exception:
        return


def record_marketplace_operation(
    operation: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            started = time.perf_counter()
            try:
                value = await fn(*args, **kwargs)
            except Exception as exc:
                emit_marketplace_operation(
                    operation=operation,
                    result="failure",
                    error_code=_error_code(exc),
                    duration_ms=_duration_ms(started),
                )
                raise
            emit_marketplace_operation(
                operation=operation,
                result="success",
                duration_ms=_duration_ms(started),
            )
            return value

        return wrapped

    return decorator


def logged_payload(record: logging.LogRecord) -> Mapping[str, Any]:
    payload = getattr(record, "df_marketplace", None)
    if not isinstance(payload, dict):
        return {}
    return {
        key: payload[key]
        for key in LOG_FIELDS
        if key in payload
    }


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in ALLOWED_ERROR_CODES:
        return code
    return "internal_error"


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
