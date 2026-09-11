"""Provider-neutral gates and authorization for optional persistent workspaces."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import tempfile
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from src.workspace.cache import WorkspaceCache
from src.workspace.contracts import WorkspaceError
from src.workspace.settings import WorkspaceSettings, WorkspaceSettingsStore
from src.workspace.validation import validate_request, valid_scope

_runtime: WorkspaceRuntimeService | None = None
LOCAL_SCOPE = hashlib.sha256(b"determinflow:local-workspace:v1").hexdigest()


def get_workspace_runtime() -> WorkspaceRuntimeService | None:
    return _runtime


def set_workspace_runtime(runtime: WorkspaceRuntimeService | None) -> None:
    global _runtime
    _runtime = runtime


def forbidden() -> WorkspaceError:
    return WorkspaceError("无权访问此工作区", code="workspace_forbidden", status_code=403)


def agent_options(agent_type: str) -> dict:
    from src.agent.definition import get_agent_definition
    definition = get_agent_definition(agent_type)
    options = getattr(definition, "extension_options", {})
    value = options.get("workspace") if isinstance(options, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else {}


class WorkspaceRuntimeService:
    def __init__(self, *, settings_store: WorkspaceSettingsStore | None = None, cache_root: Path | None = None):
        self.settings_store = settings_store or WorkspaceSettingsStore()
        self.cache = WorkspaceCache(cache_root or Path(tempfile.gettempdir()) / "determinflow-workspace-cache")
        self._providers: dict[str, Any] = {}
        self._authorizers: dict[str, Any] = {}
        self._owner_status = None
        self._management = None

    def attach(self, *, providers=None, authorizers=None, owner_status=None, management=None):
        self._providers = dict(providers or {})
        self._authorizers = dict(authorizers or {})
        self._owner_status = owner_status
        self._management = management

    def settings(self) -> WorkspaceSettings:
        return self.settings_store.load()

    def _running(self, owner: str) -> bool:
        # Registrations alone are not activation proof.
        try:
            state = self._owner_status(owner) if self._owner_status else {}
            record = self._management.get_record(owner) if self._management is not None else None
        except Exception:
            return False
        if not isinstance(state, Mapping) or state.get("status") != "running":
            return False
        if self._management is not None:
            if not record or record.get("active_enabled") is not True or record.get("desired_enabled") is not True:
                return False
            if record.get("pending_action") == "remove" or record.get("restart_required"):
                return False
        return True

    async def _provider(self, settings: WorkspaceSettings):
        provider = self._providers.get(settings.provider_id)
        if not provider or not self._running(settings.provider_id):
            raise WorkspaceError("工作区插件未就绪")
        try:
            health = provider.health
            if not inspect.iscoroutinefunction(health):
                raise WorkspaceError("工作区插件不支持健康检查")
            healthy = await asyncio.wait_for(health(), min(5, settings.timeout_seconds))
            if healthy is not True:
                raise WorkspaceError("工作区存储不可用")
        except WorkspaceError:
            raise
        except Exception:
            raise WorkspaceError("工作区健康检查失败") from None
        return provider

    async def provider_statuses(self) -> list[dict]:
        ids = sorted(set(self._providers) | ({self.settings().provider_id} if self.settings().provider_id else set()))
        result = []
        for provider_id in ids:
            reason = ""
            try:
                await self._provider(WorkspaceSettings(provider_id=provider_id))
            except WorkspaceError as error:
                reason = str(error)
            result.append({"id": provider_id, "name": provider_id, "healthy": not reason, "reason": reason})
        return result

    async def replace_settings(self, settings: WorkspaceSettings) -> None:
        if settings.enabled:
            await self._provider(settings)
        self.settings_store.save(settings)

    async def execute(self, *, resource_owner: str, external_ref: str, workspace_scope: str,
                      agent_type: str, operation: str, access: str = "agent", **request_fields) -> dict:
        """Product calls always require owner authorization, including read/status."""
        return await self._execute(resource_owner=resource_owner, external_ref=external_ref,
                                   workspace_scope=workspace_scope, agent_type=agent_type,
                                   operation=operation, access=access, local=False, fields=request_fields)

    async def _execute(self, *, resource_owner, external_ref, workspace_scope, agent_type,
                       operation, access, local, fields):
        settings = self.settings()
        if not settings.enabled:
            raise WorkspaceError("持久工作区未启用")
        request = validate_request(workspace_scope, operation, fields)
        if access not in {"agent", "user"}:
            raise forbidden()
        if access == "agent":
            options = agent_options(agent_type)
            expected_scope = "local" if local else "user"
            if options.get("enabled") is not True or options.get("scope") != expected_scope:
                raise forbidden()
        if local:
            if not settings.local_main_enabled:
                raise forbidden()
        else:
            authorizer = self._authorizers.get(resource_owner)
            if not authorizer or not self._running(resource_owner) or not external_ref:
                raise forbidden()
            try:
                allowed = await asyncio.wait_for(authorizer.authorize(
                    external_ref=external_ref, workspace_scope=workspace_scope,
                    operation=operation, path=request.path, access=access,
                ), settings.timeout_seconds)
            except Exception:
                raise forbidden() from None
            if allowed is not True:
                raise forbidden()
        provider = await self._provider(settings)
        if not local and not self._running(resource_owner):
            raise forbidden()
        # Settings and plugin activation may change while awaiting authorization.
        if self.settings() != settings or not self._running(settings.provider_id):
            raise WorkspaceError("工作区配置已变化，请重试")
        try:
            result = await asyncio.wait_for(provider.execute(request), settings.timeout_seconds)
        except WorkspaceError:
            raise
        except asyncio.TimeoutError:
            raise WorkspaceError("工作区操作超时，请用原请求重试") from None
        except Exception:
            raise WorkspaceError("工作区操作失败") from None
        if not isinstance(result, dict):
            raise WorkspaceError("工作区返回结果无效")
        if operation in {"write", "delete"} and result.get("committed") is not True:
            raise WorkspaceError("文件尚未完成持久保存")
        return result

    async def execute_for_session(self, session: Any, *, invocation_context: Mapping | None,
                                  operation: str, **fields) -> dict:
        owner = str(getattr(session, "resource_owner", "") or "")
        local = (getattr(session, "session_type", "") == "main" and not owner
                 and getattr(session, "lifecycle_profile", "") != "detached_conversation")
        scope = LOCAL_SCOPE if local else (invocation_context or {}).get("workspace_scope", "")
        if not valid_scope(scope):
            raise forbidden()
        return await self._execute(resource_owner=owner, external_ref=getattr(session, "external_ref", ""),
                                   workspace_scope=scope, agent_type=session.agent_type, operation=operation,
                                   access="agent", local=local, fields=fields)

    async def materialize_for_session(self, session: Any, *, invocation_context: Mapping | None,
                                      path: str, version: str | None = None) -> Path:
        """Explicit trusted script import; returns a disposable path after fresh auth/read.

        Never advertised as an Agent tool, never changes its coding-tool permissions.
        Callers must commit intended changes through execute_for_session, not this cache.
        """
        result = await self.execute_for_session(session, invocation_context=invocation_context,
                                                operation="read", path=path, version=version)
        local = (getattr(session, "session_type", "") == "main" and not getattr(session, "resource_owner", "")
                 and getattr(session, "lifecycle_profile", "") != "detached_conversation")
        scope = LOCAL_SCOPE if local else (invocation_context or {}).get("workspace_scope", "")
        return self.cache.materialize(scope, result)

    def clear_cache(self) -> None:
        """Discard materializations after their consumers finish; persistent files remain."""
        self.cache.clear()
