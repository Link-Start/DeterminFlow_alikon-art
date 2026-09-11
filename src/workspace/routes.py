"""Administrative settings only; products access files through the trusted service."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from src.extension_host.plugin_routes import require_plugin_write_access
from src.workspace.contracts import WorkspaceError
from src.workspace.service import get_workspace_runtime
from src.workspace.settings import WorkspaceSettings, parse_workspace_settings

router = APIRouter(prefix="/api/workspace")


def runtime_for(request):
    return getattr(request.app.state, "workspace_runtime", None) or get_workspace_runtime()


async def settings_payload(runtime):
    settings = runtime.settings() if runtime else WorkspaceSettings()
    providers = await runtime.provider_statuses() if runtime else []
    selected = next((provider for provider in providers if provider["id"] == settings.provider_id), None)
    effective = bool(settings.enabled and selected and selected["healthy"])
    reason = "" if effective else ((selected or {}).get("reason") or ("持久工作区未启用" if not settings.enabled else "工作区插件未就绪"))
    if runtime and runtime.settings_store.read_error:
        reason = "工作区配置读取失败，请重新保存配置"
    return {"settings": settings.to_dict(), "providers": providers,
            "effective_enabled": effective, "reason": reason}


@router.get("/settings")
async def get_settings(request: Request):
    return await settings_payload(runtime_for(request))


class SettingsUpdate(BaseModel):
    settings: dict


@router.put("/settings", dependencies=[Depends(require_plugin_write_access)])
async def put_settings(payload: SettingsUpdate, request: Request):
    runtime = runtime_for(request)
    if runtime is None:
        raise HTTPException(503, "持久工作区不可用")
    try:
        settings = parse_workspace_settings({**runtime.settings().to_dict(), **payload.settings})
        await runtime.replace_settings(settings)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except WorkspaceError as error:
        raise HTTPException(400, str(error)) from error
    return await settings_payload(runtime)
