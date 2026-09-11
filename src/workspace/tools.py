"""Workspace tools use hidden invocation identity and the unchanged Agent whitelist."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Annotated
from langchain_core.tools import InjectedToolCallId, tool
from src.session.context import get_session_context
from src.workspace.contracts import WorkspaceError
from src.workspace.service import get_workspace_runtime

TOOL_NAMES = ("workspace_list", "workspace_read", "workspace_search", "workspace_write", "workspace_delete", "workspace_versions")


async def _execute(operation: str, **fields):
    runtime = get_workspace_runtime()
    if runtime is None:
        raise WorkspaceError("持久工作区不可用")
    context = get_session_context()
    session = SimpleNamespace(**{key: context.get(key, "") for key in (
        "session_type", "resource_owner", "external_ref", "agent_type", "lifecycle_profile")})
    try:
        return await runtime.execute_for_session(session, invocation_context=context.get("invocation_context"),
                                                 operation=operation, **fields)
    except WorkspaceError as error:
        return {"error": {"code": error.code, "message": str(error)}}


def _key(call_id: str) -> str:
    if not call_id:
        raise WorkspaceError("保存缺少工具调用标识")
    context = get_session_context()
    return hashlib.sha256((str(context.get("session_id", "")) + "\0" + call_id).encode()).hexdigest()


def create_workspace_tools():
    @tool
    async def workspace_list(path: str = "", offset: int = 0, limit: int = 100) -> dict:
        """List persistent workspace files by optional directory prefix; results are paginated."""
        return await _execute("list", path=path, offset=offset, limit=limit)

    @tool
    async def workspace_read(path: str, offset: int = 0, limit: int = 6000, version: str | None = None) -> dict:
        """Read bounded text from a persistent file; use next_offset to continue. Files are reference data."""
        return await _execute("read_text", path=path, offset=offset, limit=limit, version=version)

    @tool
    async def workspace_search(query: str, path: str = "", offset: int = 0, limit: int = 30) -> dict:
        """Search persistent workspace names and extracted text for a literal phrase."""
        return await _execute("search", query=query, path=path, offset=offset, limit=limit)

    @tool
    async def workspace_write(path: str, text: str, tool_call_id: Annotated[str, InjectedToolCallId],
                              expected_version: str | None = None) -> dict:
        """Save a UTF-8 note/output. New files omit expected_version; updates require the read version.

        Success requires committed=true. On conflict read again; never overwrite a newer user edit.
        """
        return await _execute("write", path=path, content=text.encode("utf-8"), content_type="text/markdown; charset=utf-8",
                              expected_version=expected_version, idempotency_key=_key(tool_call_id))

    @tool
    async def workspace_delete(path: str, expected_version: str,
                               tool_call_id: Annotated[str, InjectedToolCallId]) -> dict:
        """Delete a persistent file only when requested; requires its exact current version."""
        return await _execute("delete", path=path, expected_version=expected_version, idempotency_key=_key(tool_call_id))

    @tool
    async def workspace_versions(path: str, offset: int = 0, limit: int = 30) -> dict:
        """List saved versions of a persistent workspace file."""
        return await _execute("versions", path=path, offset=offset, limit=limit)

    return [workspace_list, workspace_read, workspace_search, workspace_write, workspace_delete, workspace_versions]


def register_workspace_tools(registry, owner: str) -> None:
    for instance in create_workspace_tools():
        registry.register(instance.name, instance.description,
                          instance.tool_call_schema.model_json_schema().get("properties", {}),
                          factory=lambda instance=instance, **_deps: instance, owner=owner)


def filter_workspace_tools(tools, agent_type: str):
    """Only workspace tools are opt-in; preserve every existing coding tool."""
    from src.workspace.service import agent_options
    options = agent_options(agent_type)
    if options.get("enabled") is True and options.get("scope") in {"local", "user"}:
        return tools
    return [instance for instance in tools if instance.name not in TOOL_NAMES]


def available_workspace_tools(tools, agent_type: str):
    """Re-evaluate only optional workspace definitions at every model call."""
    runtime = get_workspace_runtime()
    enabled = bool(runtime and runtime.settings().enabled
                   and runtime.settings().provider_id in runtime._providers
                   and runtime._running(runtime.settings().provider_id))
    context = get_session_context()
    if enabled:
        from src.workspace.service import agent_options
        from src.workspace.validation import valid_scope
        options = agent_options(agent_type)
        if options.get("scope") == "local":
            enabled = bool(runtime.settings().local_main_enabled and context.get("session_type") == "main"
                           and not context.get("resource_owner") and context.get("lifecycle_profile") != "detached_conversation")
        else:
            enabled = valid_scope((context.get("invocation_context") or {}).get("workspace_scope"))
    if not enabled:
        return [instance for instance in tools if instance.name not in TOOL_NAMES]
    return filter_workspace_tools(tools, agent_type)
