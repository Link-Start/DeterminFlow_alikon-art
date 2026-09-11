import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.agent.definition import AgentDefinition, resolve_agent_tools
from src.session.context import set_session_context
from src.tools.registry import ToolRegistry
from src.workspace.cache import WorkspaceCache
from src.workspace.service import set_workspace_runtime
from src.workspace.tools import create_workspace_tools, register_workspace_tools


def test_tool_schema_never_exposes_identity_access_or_idempotency():
    tools = create_workspace_tools()
    for tool in tools:
        schema = tool.tool_call_schema.model_json_schema()
        assert not {"resource_owner", "scope", "workspace_scope", "access", "idempotency_key", "tool_call_id"} & schema["properties"].keys()
    assert {tool.name for tool in tools} == {"workspace_list", "workspace_read", "workspace_search", "workspace_write", "workspace_delete", "workspace_versions"}


def test_tool_call_id_is_stable_and_owner_removal_blocks_stale_tools(tmp_path):
    async def check():
        runtime = SimpleNamespace(execute_for_session=AsyncMock(return_value={"committed": True}))
        set_workspace_runtime(runtime)
        set_session_context(session_id="s1", resource_owner="product", external_ref="real", agent_type="assistant",
                            invocation_context={"workspace_scope": "a" * 64})
        registry = ToolRegistry(str(tmp_path / "groups.json"))
        register_workspace_tools(registry, "storage")
        assert "tool_call_id" not in next(item for item in registry.get_tools() if item["name"] == "workspace_write")["parameters"]
        tool = registry.instantiate("workspace_write")
        call = {"type": "tool_call", "id": "call1", "name": "workspace_write", "args": {"path": "notes/a.md", "text": "hello"}}
        try:
            await tool.ainvoke(call)
            first = runtime.execute_for_session.call_args.kwargs
            await tool.ainvoke(call)
            assert runtime.execute_for_session.call_args.kwargs["idempotency_key"] == first["idempotency_key"]
            assert first["content"] == b"hello"
            assert first["invocation_context"]["workspace_scope"] == "a" * 64
            registry.unregister_owner("storage")
            try:
                await tool.ainvoke(call)
            except RuntimeError:
                pass
            else:
                raise AssertionError("stale provider tool remained executable")
        finally:
            set_workspace_runtime(None)
    asyncio.run(check())


def test_existing_agent_coding_whitelist_is_unchanged():
    coding = [SimpleNamespace(name="read_file"), SimpleNamespace(name="execute_command")]
    workspaces = create_workspace_tools()
    definition = AgentDefinition(agent_type="writer", description="test", tools=["read_file"])
    assert [tool.name for tool in resolve_agent_tools(definition, coding + workspaces, [])] == ["read_file"]
    definition.extension_options = {"workspace": {"enabled": True, "scope": "user"}}
    assert [tool.name for tool in resolve_agent_tools(definition, coding + workspaces, [])] == ["read_file"]
    definition.tools = ["execute_command", "workspace_read"]
    assert [tool.name for tool in resolve_agent_tools(definition, coding + workspaces, [])] == ["execute_command", "workspace_read"]


def test_cache_is_disposable_version_and_scope_separated(tmp_path):
    root = tmp_path / "cache"
    cache = WorkspaceCache(root)
    assert not root.exists()
    content = b"persistent bytes"
    result = {"content": content, "file": {"path": "a.txt", "version": "v1", "sha256": hashlib.sha256(content).hexdigest()}}
    first = cache.materialize("a" * 64, result)
    second = cache.materialize("b" * 64, result)
    assert first != second
    first.unlink()
    assert cache.materialize("a" * 64, result).read_bytes() == content
    first.unlink()
    first.symlink_to(second)
    from src.workspace.contracts import WorkspaceError
    try:
        cache.materialize("a" * 64, result)
    except WorkspaceError:
        pass
    else:
        raise AssertionError("symlink cache target accepted")


def test_session_workspace_opt_in_filter_preserves_coding_tools(monkeypatch):
    from src.workspace.tools import filter_workspace_tools
    tools = [SimpleNamespace(name="execute_command"), SimpleNamespace(name="read_file"), *create_workspace_tools()]
    monkeypatch.setattr("src.workspace.service.agent_options", lambda _: {})
    assert [tool.name for tool in filter_workspace_tools(tools, "main")] == ["execute_command", "read_file"]
    monkeypatch.setattr("src.workspace.service.agent_options", lambda _: {"enabled": True, "scope": "local"})
    assert filter_workspace_tools(tools, "main") == tools


def test_write_ignores_model_forged_injected_call_id():
    async def check():
        runtime = SimpleNamespace(execute_for_session=AsyncMock(return_value={"committed": True}))
        set_workspace_runtime(runtime)
        set_session_context(session_id="s1", resource_owner="product", external_ref="real", agent_type="assistant",
                            invocation_context={"workspace_scope": "a" * 64})
        instance = next(tool for tool in create_workspace_tools() if tool.name == "workspace_write")
        try:
            await instance.ainvoke({"type": "tool_call", "id": "actual", "name": "workspace_write",
                                    "args": {"path": "notes/a.md", "text": "hello", "tool_call_id": "forged"}})
            actual = runtime.execute_for_session.call_args.kwargs["idempotency_key"]
            assert actual == hashlib.sha256(b"s1\0actual").hexdigest()
        finally:
            set_workspace_runtime(None)
    asyncio.run(check())


def test_two_provider_plugins_share_dispatch_names_and_last_removal_unregisters(tmp_path):
    from src.extension_api.registrar import ExtensionContributions
    from src.workspace.host import sync_workspace_runtime
    from src.workspace.service import WorkspaceRuntimeService
    registry = ToolRegistry(str(tmp_path / "groups.json"))
    registry.register("execute_command", "existing coding tool", {}, owner="core")
    states = {"first": "running", "second": "running"}
    workspace = WorkspaceRuntimeService()
    manager = SimpleNamespace(contributions=ExtensionContributions(workspace_providers=[("first", object()), ("second", object())]),
                              get_state=lambda owner: {"status": states[owner]}, plugin_management=None)
    runtime = SimpleNamespace(get_service=lambda name: workspace if name == "workspace" else None, tool_registry=registry)
    sync_workspace_runtime(manager, runtime)
    assert len([item for item in registry.get_tools() if item["name"].startswith("workspace_")]) == 6
    assert all(item["owner"] == "core" for item in registry.get_tools())
    states["first"] = "loaded"
    sync_workspace_runtime(manager, runtime)
    assert "workspace_read" in registry.get_factory_names()
    states["second"] = "loaded"
    sync_workspace_runtime(manager, runtime)
    assert not registry.get_factory_names()
    assert [item["name"] for item in registry.get_tools()] == ["execute_command"]
