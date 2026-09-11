"""Bounded memory provider health and activation checks."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Mapping
from typing import Any

from src.memory.settings import MemorySettings

logger = logging.getLogger(__name__)

HEALTH_TIMEOUT_SECONDS = 5.0
HEALTH_REASON_MAX = 200
STAGED_REMOVE_ACTIONS = frozenset({"remove"})


def clean_health_reason(reason: object) -> str:
    text = " ".join(str(reason or "").split())
    if len(text) > HEALTH_REASON_MAX:
        return text[: HEALTH_REASON_MAX - 1] + "..."
    return text


async def probe_provider_health(
    provider: Any,
    *,
    timeout: float = HEALTH_TIMEOUT_SECONDS,
) -> tuple[bool, str, bool]:
    """Return (healthy, reason, exposes_health). Never raises or leaks secrets."""

    health = getattr(provider, "health", None)
    if not callable(health) or not inspect.iscoroutinefunction(health):
        return False, "记忆提供者不提供 health()，无法启用外部记忆", False
    try:
        result = await asyncio.wait_for(health(), timeout=timeout)
    except asyncio.TimeoutError:
        return False, "记忆提供者健康检查超时", True
    except Exception:
        logger.warning("memory provider health failed", exc_info=True)
        return False, "记忆提供者健康检查失败", True
    if not isinstance(result, tuple) or len(result) != 2:
        return False, "记忆提供者健康检查失败", True
    healthy, reason = result
    if not isinstance(healthy, bool):
        return False, "记忆提供者健康检查失败", True
    return healthy, clean_health_reason(reason), True


def plugin_record_for(management: Any, plugin_id: str) -> dict[str, Any] | None:
    if management is None or not plugin_id:
        return None
    getter = getattr(management, "get_record", None)
    if not callable(getter):
        return None
    try:
        record = getter(plugin_id)
    except Exception:
        return None
    return record if isinstance(record, dict) else None


def evaluate_external_enable_gate(
    *,
    provider_id: str,
    providers: Mapping[str, Any],
    plugin_record: Mapping[str, Any] | None,
    healthy: bool,
    health_reason: str,
    exposes_health: bool,
) -> str:
    """Return a blocking reason, or empty string when enabling is allowed."""

    if not provider_id:
        return "未选择记忆提供者"
    if provider_id not in providers:
        return "记忆提供者未注册"
    if plugin_record is None:
        return "记忆提供者插件不可用"
    status = str(plugin_record.get("runtime_status") or "").strip()
    if status != "running":
        return "记忆提供者插件未运行"
    if plugin_record.get("active_enabled") is not True:
        return "记忆提供者插件未处于活动状态"
    if plugin_record.get("desired_enabled") is not True:
        return "记忆提供者插件已计划停用"
    pending = str(plugin_record.get("pending_action") or "").strip()
    if pending in STAGED_REMOVE_ACTIONS:
        return "记忆提供者插件已计划卸载"
    if plugin_record.get("restart_required"):
        return "记忆提供者有待生效变更，请重启后再启用"
    if not exposes_health:
        return "记忆提供者不提供 health()，无法启用外部记忆"
    if not healthy:
        return health_reason or "记忆提供者健康检查失败"
    return ""


def describe_effective_state(
    settings: MemorySettings,
    providers: list[dict[str, Any]],
) -> tuple[bool, str]:
    if not settings.enabled:
        return False, "记忆总开关已关闭"
    if not settings.external_enabled:
        return False, "外部记忆未启用"
    if not settings.provider_id:
        return False, "未选择记忆提供者"
    status = next(
        (item for item in providers if item.get("id") == settings.provider_id),
        None,
    )
    if status is None:
        return False, "记忆提供者不存在"
    if str(status.get("status") or "") != "running":
        return False, "记忆提供者未运行"
    if status.get("healthy") is not True:
        return False, str(status.get("reason") or "记忆提供者健康检查失败")
    return True, ""


async def build_provider_statuses(
    *,
    provider_ids: list[str],
    providers: Mapping[str, Any],
    owner_status_name,
    management: Any = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider_id in provider_ids:
        if not provider_id or provider_id in seen:
            continue
        seen.add(provider_id)
        record = plugin_record_for(management, provider_id)
        name = str((record or {}).get("name") or provider_id)
        status = str(owner_status_name(provider_id) or "").strip() or "missing"
        if record is not None and status == "missing":
            status = str(record.get("runtime_status") or status)
        provider = providers.get(provider_id)
        if provider is None:
            result.append(
                {
                    "id": provider_id,
                    "name": name,
                    "status": status,
                    "healthy": False,
                    "reason": "记忆提供者未注册",
                }
            )
            continue
        healthy, reason, _exposes = await probe_provider_health(provider)
        result.append(
            {
                "id": provider_id,
                "name": name,
                "status": status,
                "healthy": healthy,
                "reason": reason,
            }
        )
    return result
