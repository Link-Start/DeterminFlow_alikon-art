"""HTTP routes for settings sections and Core memory settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.extension_host.plugin_routes import require_plugin_write_access
from src.memory.provider_status import (
    describe_effective_state,
    evaluate_external_enable_gate,
    plugin_record_for,
    probe_provider_health,
)
from src.memory.service import get_memory_runtime
from src.memory.contracts import MemoryUnavailableError
from src.memory.management import MemoryJobConflict
from src.memory.settings import (
    MEMORY_SETTING_KEY_SET,
    MEMORY_SETTINGS_SCHEMA,
    default_memory_settings,
    parse_memory_settings,
)
from src.settings.catalog import collect_plugin_sections, list_settings_sections

router = APIRouter(prefix="/api")


class MemorySettingsUpdate(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


def _plugin_management(request: Request):
    manager = getattr(request.app.state, "extension_manager", None)
    return getattr(manager, "plugin_management", None)


def _memory_runtime(request: Request):
    runtime = getattr(request.app.state, "memory_runtime", None)
    if runtime is not None:
        return runtime
    return get_memory_runtime()


def _read_settings(runtime):
    settings = runtime.resolved_memory_settings()
    if runtime.settings_read_error:
        raise HTTPException(status_code=503, detail="记忆配置读取失败，已停用外部记忆；请修复配置文件后重启")
    return settings


async def _memory_settings_payload(request: Request) -> dict[str, Any]:
    runtime = _memory_runtime(request)
    management = _plugin_management(request)
    if runtime is None:
        settings = default_memory_settings()
        providers: list[dict[str, Any]] = []
    else:
        settings = _read_settings(runtime)
        providers = await runtime.provider_statuses(management)
    effective, reason = describe_effective_state(settings, providers)
    return {
        "settings": settings.to_dict(),
        "providers": providers,
        "effective_enabled": effective,
        "reason": reason,
        "schema": {"type": "object", "properties": MEMORY_SETTINGS_SCHEMA},
    }


@router.get("/settings/sections")
async def get_settings_sections(request: Request) -> dict[str, Any]:
    plugin_sections = collect_plugin_sections(_plugin_management(request))
    return {"sections": list_settings_sections(plugin_sections)}


@router.get("/memory/settings")
async def get_memory_settings(request: Request) -> dict[str, Any]:
    return await _memory_settings_payload(request)


@router.put(
    "/memory/settings",
    dependencies=[Depends(require_plugin_write_access)],
)
async def put_memory_settings(
    payload: MemorySettingsUpdate,
    request: Request,
) -> dict[str, Any]:
    runtime = _memory_runtime(request)
    if runtime is None:
        raise HTTPException(status_code=503, detail="记忆运行时不可用")
    incoming = payload.settings
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="settings 必须是 object")
    unknown = sorted(set(incoming) - MEMORY_SETTING_KEY_SET)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="memory settings 包含未知字段: " + ", ".join(unknown),
        )
    current = _read_settings(runtime)
    merged = {**current.to_dict(), **incoming}
    try:
        settings = parse_memory_settings(merged, unknown="reject")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if settings.enables_external():
        providers = runtime.registered_providers()
        provider = providers.get(settings.provider_id)
        healthy = False
        health_reason = "记忆提供者未注册"
        exposes_health = False
        if provider is not None:
            healthy, health_reason, exposes_health = await probe_provider_health(
                provider
            )
        blocked = evaluate_external_enable_gate(
            provider_id=settings.provider_id,
            providers=providers,
            plugin_record=plugin_record_for(
                _plugin_management(request),
                settings.provider_id,
            ),
            healthy=healthy,
            health_reason=health_reason,
            exposes_health=exposes_health,
        )
        if blocked:
            raise HTTPException(status_code=400, detail=blocked)
    await runtime.replace_settings(settings)
    return await _memory_settings_payload(request)


class MemoryJobRetry(BaseModel):
    job_id: str = Field(min_length=1, max_length=128)


@router.get("/memory/jobs", dependencies=[Depends(require_plugin_write_access)])
async def get_memory_jobs(request: Request) -> dict[str, Any]:
    runtime = _memory_runtime(request)
    if runtime is None:
        raise HTTPException(status_code=503, detail="记忆运行时不可用")
    return runtime.memory_job_status()


@router.post("/memory/jobs/{session_id}/retry", dependencies=[Depends(require_plugin_write_access)])
async def retry_memory_job(session_id: str, payload: MemoryJobRetry, request: Request) -> dict[str, Any]:
    runtime = _memory_runtime(request)
    if runtime is None:
        raise HTTPException(status_code=503, detail="记忆运行时不可用")
    try:
        return await runtime.retry_failed_memory_job(session_id, payload.job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="记忆整理会话不存在") from exc
    except MemoryJobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MemoryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="记忆整理参数无效") from exc
