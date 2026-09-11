from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import HumanMessage

from src.agent.message_context import compose_user_model_content
from src.workspace.contracts import WorkspaceError
from src.workspace.context import prepare_workspace_context, serialized_tokens, strip_workspace_context
from src.workspace.service import LOCAL_SCOPE, WorkspaceRuntimeService, set_workspace_runtime
from src.workspace.settings import WorkspaceSettings, WorkspaceSettingsStore
from src.workspace.validation import validate_request

SCOPE = "a" * 64


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def setup_runtime(monkeypatch):
    options = {"enabled": True, "scope": "user"}
    monkeypatch.setattr("src.agent.definition.get_agent_definition", lambda _: SimpleNamespace(extension_options={"workspace": options}))
    provider = SimpleNamespace(health=AsyncMock(return_value=True), execute=AsyncMock(return_value={"available": True}))
    auth = SimpleNamespace(authorize=AsyncMock(return_value=True))
    states = {"storage": "running", "product": "running"}
    runtime = WorkspaceRuntimeService()
    runtime.attach(providers={"storage": provider}, authorizers={"product": auth},
                   owner_status=lambda owner: {"status": states.get(owner, "missing")})
    runtime.settings_store.save(WorkspaceSettings(enabled=True, provider_id="storage"))
    set_workspace_runtime(runtime)
    yield runtime, provider, auth, states, options
    set_workspace_runtime(None)


async def execute(runtime, **overrides):
    return await runtime.execute(**{"resource_owner": "product", "external_ref": "session-1",
                                    "workspace_scope": SCOPE, "agent_type": "assistant", "operation": "status", **overrides})


@pytest.mark.anyio
async def test_default_disabled_never_calls_provider_or_authorizer(setup_runtime):
    runtime, provider, auth, *_ = setup_runtime
    runtime.settings_store.save(WorkspaceSettings())
    with pytest.raises(WorkspaceError, match="未启用"):
        await execute(runtime)
    provider.health.assert_not_called()
    provider.execute.assert_not_called()
    auth.authorize.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["status", "list", "read_text", "write", "delete", "search", "versions"])
async def test_every_external_operation_authorized(setup_runtime, operation):
    runtime, provider, auth, *_ = setup_runtime
    auth.authorize.return_value = False
    fields = {"path": "notes/a.md"} if operation not in {"status", "list", "search"} else {}
    if operation in {"write", "delete"}:
        fields.update(idempotency_key="once", expected_version="v1")
    if operation == "write":
        fields["content"] = b"hello"
    with pytest.raises(WorkspaceError) as caught:
        await execute(runtime, operation=operation, **fields)
    assert caught.value.status_code == 403
    provider.execute.assert_not_called()
    assert auth.authorize.call_args.kwargs["operation"] == operation


@pytest.mark.anyio
async def test_user_bridge_bypasses_opt_in_but_not_auth(setup_runtime):
    runtime, _, auth, _, options = setup_runtime
    options["enabled"] = False
    with pytest.raises(WorkspaceError):
        await execute(runtime)
    await execute(runtime, access="user")
    assert auth.authorize.call_args.kwargs["access"] == "user"
    with pytest.raises(WorkspaceError):
        await execute(runtime, resource_owner="", external_ref="", workspace_scope=LOCAL_SCOPE, access="user")


@pytest.mark.anyio
async def test_local_binding_only_verified_internal_main(setup_runtime):
    runtime, provider, _, _, options = setup_runtime
    options["scope"] = "local"
    runtime.settings_store.save(replace(runtime.settings(), local_main_enabled=True))
    main = SimpleNamespace(session_type="main", agent_type="main", resource_owner="", lifecycle_profile="default", external_ref="")
    await runtime.execute_for_session(main, invocation_context={"workspace_scope": SCOPE}, operation="status")
    assert provider.execute.call_args.args[0].scope == LOCAL_SCOPE
    main.resource_owner = "product"
    with pytest.raises(WorkspaceError):
        await runtime.execute_for_session(main, invocation_context={"workspace_scope": LOCAL_SCOPE}, operation="status")


@pytest.mark.anyio
async def test_plugin_health_and_disable_gate(setup_runtime):
    runtime, provider, _, states, _ = setup_runtime
    provider.health.return_value = False
    with pytest.raises(WorkspaceError):
        await runtime.replace_settings(runtime.settings())
    await runtime.replace_settings(replace(runtime.settings(), enabled=False))
    provider.execute.assert_not_called()
    assert runtime.settings().enabled is False
    states["storage"] = "missing"
    with pytest.raises(WorkspaceError):
        await runtime.replace_settings(replace(runtime.settings(), enabled=True))


@pytest.mark.anyio
async def test_uncommitted_write_not_success_and_settings_change_fenced(setup_runtime):
    runtime, provider, auth, *_ = setup_runtime
    provider.execute.return_value = {"committed": False}
    with pytest.raises(WorkspaceError, match="持久保存"):
        await execute(runtime, operation="write", path="notes/a.md", content=b"a", idempotency_key="one")
    async def disable(**_):
        runtime.settings_store.save(replace(runtime.settings(), enabled=False))
        return True
    auth.authorize.side_effect = disable
    provider.execute.reset_mock()
    with pytest.raises(WorkspaceError, match="变化"):
        await execute(runtime)
    provider.execute.assert_not_called()


@pytest.mark.parametrize("path", ["/secret", "../x", "notes/../x", "notes//x", "a\\b", "a\0b", "a\nb", "./a", "notes/"])
def test_paths_reject_escape(path):
    with pytest.raises(WorkspaceError):
        validate_request(SCOPE, "read_text", {"path": path})


@pytest.mark.parametrize("fields", [{"scope": SCOPE}, {"access": "user"}, {"limit": 12001}, {"offset": True}])
def test_request_rejects_unknown_routing_and_unbounded_fields(fields):
    with pytest.raises(WorkspaceError):
        validate_request(SCOPE, "read_text", {"path": "a.txt", **fields})


def session():
    return SimpleNamespace(session_type="sub", agent_type="assistant", resource_owner="product",
                           lifecycle_profile="detached_conversation", external_ref="session-1", lc_messages=[], record=[])


@pytest.mark.anyio
async def test_context_bounded_and_original_user_preserved_no_hidden_scope(setup_runtime):
    runtime, provider, *_ = setup_runtime
    runtime.settings_store.save(replace(runtime.settings(), context_token_budget=256))
    async def answer(request):
        if request.operation == "list":
            return {"files": [{"path": "materials/novel.txt", "version": "v1", "size": 7}], "total": 1}
        return {"file": {"version": "v1"}, "text": "测试用户资料" * 1000, "truncated": False}
    provider.execute.side_effect = answer
    result = await prepare_workspace_context(session=session(), content="我的原话", source="human",
        invocation_context={"workspace_scope": SCOPE}, model_context={"locale": "zh-CN"}, append_input=True)
    block = result["workspace"]
    assert serialized_tokens(block) <= 256
    composed = compose_user_model_content("我的原话", model_context=result)
    assert "<USER_MESSAGE>\n我的原话\n</USER_MESSAGE>" in composed
    assert SCOPE not in composed and "_binding" not in composed
    assert block["truncated"]


@pytest.mark.anyio
async def test_missing_optional_files_and_tool_resume_no_reload(setup_runtime):
    _, provider, *_ = setup_runtime
    async def answer(request):
        if request.operation == "list":
            return {"files": [], "total": 0}
        raise WorkspaceError("missing", code="workspace_not_found", status_code=404)
    provider.execute.side_effect = answer
    current = session()
    kwargs = dict(session=current, content="你好", source="human", invocation_context={"workspace_scope": SCOPE}, model_context=None)
    result = await prepare_workspace_context(**kwargs, append_input=True)
    assert result["workspace"]["status"] == "available"
    assert result["workspace"]["documents"] == []
    current.lc_messages = [HumanMessage(content=compose_user_model_content("你好", model_context=result), additional_kwargs={"display_content": "你好", "model_context": result})]
    provider.execute.reset_mock()
    await prepare_workspace_context(**kwargs, append_input=False)
    provider.execute.assert_not_called()
    assert "workspace" in current.lc_messages[0].additional_kwargs["model_context"]


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["disable", "scope", "omit", "plugin"])
async def test_stale_context_removed_from_actual_messages_even_on_resume(setup_runtime, change):
    runtime, _, _, states, _ = setup_runtime
    current = session()
    block = {"workspace": {"documents": [{"text": "SECRET"}], "_binding": "old"}, "locale": "zh-CN"}
    current.lc_messages = [HumanMessage(content=compose_user_model_content("original", model_context=block), additional_kwargs={"model_context": block, "display_content": "original"})]
    current.record = [{"type": "user", "content": "original", "model_context": block.copy()}]
    invocation = {"workspace_scope": SCOPE}
    if change == "disable":
        runtime.settings_store.save(WorkspaceSettings())
    if change == "scope":
        invocation = {"workspace_scope": "b" * 64}
    if change == "omit":
        invocation = {}
    if change == "plugin":
        states["storage"] = "missing"
    await prepare_workspace_context(session=current, content="", source="human", invocation_context=invocation, model_context=None, append_input=False)
    assert "SECRET" not in current.lc_messages[0].content
    assert "workspace" not in current.record[0]["model_context"]
    assert current.record[0]["content"] == "original"


def test_corrupt_settings_fail_closed_and_can_recover(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("invalid")
    store = WorkspaceSettingsStore(path)
    assert store.load().enabled is False
    assert store.read_error
    store.save(WorkspaceSettings())
    assert not store.read_error
    assert WorkspaceSettingsStore(path).load() == WorkspaceSettings()


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["disable", "context", "scope", "omit", "plugin", "provider"])
async def test_real_restored_session_strips_stale_context_before_graph(setup_runtime, change):
    from src.agent.session import AgentSession
    from tests.test_tool_resume_recovery import _ResumeGraph, _success_events, _no_save
    runtime, provider, _, states, _ = setup_runtime
    async def answer(request):
        if request.operation == "list":
            return {"files": [], "total": 0}
        return {"file": {"version": "v1"}, "text": "PRIVATE-WORKSPACE-NOTE", "truncated": False}
    provider.execute.side_effect = answer
    current = AgentSession(session_type="sub", agent_type="assistant", resource_owner="product", external_ref="session-1")
    current.compiled_graph = _ResumeGraph(events=_success_events("first response"))
    current.async_save = _no_save
    await current._invoke_graph_once("original user", event_callback=None, max_rounds=2,
                                     invocation_context={"workspace_scope": SCOPE})
    assert any("PRIVATE-WORKSPACE-NOTE" in str(message.content) for message in current.lc_messages)
    snapshot = current.to_dict()
    restored = AgentSession.from_dict(snapshot)
    restored.compiled_graph = _ResumeGraph(events=_success_events("resumed"))
    restored.async_save = _no_save
    invocation = {"workspace_scope": SCOPE}
    if change == "disable":
        runtime.settings_store.save(replace(runtime.settings(), enabled=False))
    if change == "context":
        runtime.settings_store.save(replace(runtime.settings(), context_enabled=False))
    if change == "scope":
        invocation = {"workspace_scope": "b" * 64}
    if change == "omit":
        invocation = {}
    if change == "plugin":
        states["storage"] = "missing"
    if change == "provider":
        runtime.settings_store.save(replace(runtime.settings(), provider_id="other"))
    provider.execute.reset_mock()
    await restored._invoke_graph_once("", event_callback=None, max_rounds=2,
                                      invocation_context=invocation, append_input=False)
    provider.execute.assert_not_called()
    assert all("PRIVATE-WORKSPACE-NOTE" not in str(message.content)
               for message in restored.compiled_graph.states[0]["messages"])
    assert all("workspace" not in (item.get("model_context") or {}) for item in restored.record)
    assert restored.record[0]["content"] == "original user"


def test_serialized_langchain_message_cleanup_rewrites_composed_body():
    context = {"workspace": {"_binding": "old", "documents": [{"text": "SECRET"}]}}
    message = {"type": "human", "content": compose_user_model_content("original", model_context=context),
               "additional_kwargs": {"model_context": context, "display_content": "original"}}
    strip_workspace_context([message])
    assert message["content"] == "original"


@pytest.mark.anyio
async def test_materialization_requires_fresh_authorization_and_recovers_cold_cache(setup_runtime, tmp_path):
    import hashlib
    from src.workspace.cache import WorkspaceCache
    runtime, provider, auth, *_ = setup_runtime
    runtime.cache = WorkspaceCache(tmp_path / "cache")
    content = b"durable file bytes"
    provider.execute.return_value = {"file": {"path": "a.txt", "version": "v1", "sha256": hashlib.sha256(content).hexdigest()}, "content": content}
    runtime.settings_store.save(replace(runtime.settings(), enabled=False))
    with pytest.raises(WorkspaceError):
        await runtime.materialize_for_session(session(), invocation_context={"workspace_scope": SCOPE}, path="a.txt")
    assert not runtime.cache.root.exists()
    runtime.settings_store.save(replace(runtime.settings(), enabled=True))
    auth.authorize.return_value = False
    with pytest.raises(WorkspaceError):
        await runtime.materialize_for_session(session(), invocation_context={"workspace_scope": SCOPE}, path="a.txt")
    assert not runtime.cache.root.exists()
    auth.authorize.return_value = True
    first = await runtime.materialize_for_session(session(), invocation_context={"workspace_scope": SCOPE}, path="a.txt")
    assert first.read_bytes() == content
    runtime.clear_cache()
    assert not first.exists()
    assert (await runtime.materialize_for_session(session(), invocation_context={"workspace_scope": SCOPE}, path="a.txt")).read_bytes() == content
    auth.authorize.return_value = False
    with pytest.raises(WorkspaceError):
        await runtime.materialize_for_session(session(), invocation_context={"workspace_scope": SCOPE}, path="a.txt")
    runtime.clear_cache()


@pytest.mark.anyio
async def test_live_model_calls_hide_disabled_workspace_tools_preserve_coding(setup_runtime, monkeypatch):
    from langchain_core.messages import AIMessage
    from src.core.graph_builder import _make_llm_node
    from src.session.context import set_session_context
    runtime, _, _, states, options = setup_runtime
    advertised = []
    class Model:
        def bind_tools(self, tools, strict=True):
            class Bound:
                async def ainvoke(self, messages):
                    advertised.append([tool.name for tool in tools])
                    return AIMessage(content="ok")
            return Bound()
    monkeypatch.setattr("src.core.model_manager.get_model_manager", lambda: SimpleNamespace(get_model_info=lambda _: {"maxContextTokens": 100000}))
    tools = [SimpleNamespace(name="execute_command"), SimpleNamespace(name="workspace_read")]
    node = _make_llm_node(Model(), tools)
    set_session_context(session_type="sub", resource_owner="product", invocation_context={"workspace_scope": SCOPE})
    state = {"messages": [HumanMessage(content="hello")], "agent_type": "assistant", "session_id": "s", "remaining_rounds": 2, "metadata": {}}
    await node(state)
    assert advertised[-1] == ["execute_command", "workspace_read"]
    runtime.settings_store.save(replace(runtime.settings(), enabled=False))
    await node(state)
    assert advertised[-1] == ["execute_command"]
    runtime.settings_store.save(replace(runtime.settings(), enabled=True))
    states["storage"] = "missing"
    await node(state)
    assert advertised[-1] == ["execute_command"]
    states["storage"] = "running"
    options["enabled"] = False
    await node(state)
    assert advertised[-1] == ["execute_command"]
