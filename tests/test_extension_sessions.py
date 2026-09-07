from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Annotated, Callable

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import InjectedToolArg, StructuredTool
from pydantic import BaseModel

import src.agent.session as session_module
import src.agent.session_lifecycle as lifecycle_module
from src.agent.extension_sessions import ExtensionSessionRuntime
from src.agent.session import AgentSession
from src.agent.session_manager import SessionManager
from src.web.api_routes import get_session_system_prompt


@pytest.fixture
def detached_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(lifecycle_module, "SESSIONS_DIR", tmp_path)
    agent_def = SimpleNamespace(
        model=None,
        model_params={},
        system_prompt_template="",
    )
    monkeypatch.setattr(
        "src.agent.definition.get_agent_definition",
        lambda agent_type: agent_def if agent_type == "plugin-page-assistant" else None,
    )
    manager = SessionManager()
    manager._prompt_builder = SimpleNamespace(
        build=lambda agent_type, **kwargs: f"prompt:{agent_type}"
    )

    def configure(self, session):
        session.compiled_graph = object()
        self._manager.register_runtime_session(session)

    monkeypatch.setattr(ExtensionSessionRuntime, "_configure_graph", configure)
    return manager, ExtensionSessionRuntime(manager).for_owner("example-plugin")


def test_detached_session_is_parentless_workspace_free_and_cold_after_turn(
    detached_runtime,
    monkeypatch,
):
    asyncio.run(_test_detached_session_is_parentless(detached_runtime, monkeypatch))


async def _test_detached_session_is_parentless(detached_runtime, monkeypatch):
    manager, runtime = detached_runtime
    manager.main_session_id = "existing-main"
    ref = await runtime.ensure_detached(
        external_ref="portal-session-1",
        agent_type="plugin-page-assistant",
        scope_hash="scope-1",
    )

    session = manager.sessions[ref.session_id]
    assert ref.created is True
    assert len(ref.session_id) == 32
    assert session.session_type == "sub"
    assert session.parent_id is None
    assert session.workspace_path is None
    assert session.lifecycle_profile == "detached_conversation"
    assert manager.main_session_id == "existing-main"
    summary = manager._session_catalog.get(ref.session_id).to_summary()
    assert summary["runtime_scope"] == "interactive"
    assert summary["lifecycle_profile"] == "detached_conversation"
    assert summary["resource_owner"] == "example-plugin"

    async def send_message(self, content, **kwargs):
        self.record.extend(
            [
                {"id": "msg_00001", "type": "user", "content": content},
                {"id": "msg_00002", "type": "assistant", "content": "reply"},
            ]
        )
        return "reply"

    monkeypatch.setattr(AgentSession, "send_message", send_message)
    assert await runtime.invoke(ref.session_id, "hello") == "reply"
    assert ref.session_id not in manager.sessions
    persisted = AgentSession.load(ref.session_id)
    assert persisted is not None
    assert persisted.record[-1]["content"] == "reply"


def test_prompt_inspection_resolves_cold_detached_tools_without_rehydrating(
    monkeypatch,
):
    def query_account() -> str:
        """查询账号概况。"""
        return "ok"

    tool = StructuredTool.from_function(
        query_account,
        name="novelbuilt_account",
        description="查询账号概况",
    )

    class FakeAssembler:
        def __init__(self):
            self.calls = []

        def build(self, agent_type, **kwargs):
            self.calls.append((agent_type, kwargs))
            return [tool]

    agent_def = SimpleNamespace(agent_type="plugin-page-assistant")
    monkeypatch.setattr(
        "src.agent.definition.get_agent_definition",
        lambda agent_type: agent_def if agent_type == agent_def.agent_type else None,
    )
    monkeypatch.setattr(
        "src.core.model_manager.get_model_manager",
        lambda: SimpleNamespace(
            get_default_model=lambda: "provider:model",
            get_default_params=lambda: {"temperature": 0.7},
            get_provider=lambda _provider_id: {},
        ),
    )
    manager = SessionManager()
    assembler = FakeAssembler()
    manager._tool_assembler = assembler
    session = AgentSession(
        session_id="cold-detached",
        session_type="sub",
        agent_type=agent_def.agent_type,
        lifecycle_profile="detached_conversation",
        system_prompt="system",
    )
    session.status = "completed"
    session.compiled_graph = None
    session.tools = []
    manager.sessions[session.session_id] = session
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(session_manager=manager),
        ),
    )

    response = asyncio.run(get_session_system_prompt(session.session_id, request))

    assert response["tools_count"] == 1
    assert response["tools"][0]["name"] == "novelbuilt_account"
    assert response["tools"][0]["description"] == "查询账号概况"
    assert response["tools"][0]["schema"]["function"]["name"] == "novelbuilt_account"
    assert assembler.calls == [
        (
            agent_def.agent_type,
            {
                "is_workflow_node": False,
                "agent_definition": agent_def,
                "workspace_path": "",
                "enable_complete_node_task": False,
                "enable_reject_upstream": False,
            },
        )
    ]
    assert session.compiled_graph is None
    assert session.tools == []


def test_prompt_inspection_uses_llm_visible_tool_schema():
    class ToolArgs(BaseModel):
        action: str
        runtime_callback: Annotated[Callable[[], None], InjectedToolArg]

    def invoke_tool(action: str, runtime_callback: Callable[[], None]) -> str:
        """Run an action."""
        return action

    tool = StructuredTool.from_function(
        invoke_tool,
        name="novelbuilt_account",
        description="查询账号概况",
        args_schema=ToolArgs,
    )
    manager = SessionManager()
    session = AgentSession(
        session_id="active-detached",
        session_type="sub",
        agent_type="plugin-page-assistant",
        lifecycle_profile="detached_conversation",
        system_prompt="system",
    )
    session.tools = [tool]
    manager.sessions[session.session_id] = session
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(session_manager=manager),
        ),
    )

    response = asyncio.run(get_session_system_prompt(session.session_id, request))

    assert response["tools_count"] == 1
    inspected_tool = response["tools"][0]
    assert inspected_tool["name"] == "novelbuilt_account"
    assert inspected_tool["parameters"] == {
        "action": {
            "type": "string",
            "description": "",
            "required": True,
        }
    }
    assert inspected_tool["schema"]["function"]["parameters"]["required"] == ["action"]
    assert "runtime_callback" not in inspected_tool["schema"]["function"]["parameters"]["properties"]
    assert response["token_estimate"]["tools"] > 0


def test_prompt_inspection_uses_actual_model_messages_not_display_record(monkeypatch):
    monkeypatch.setattr(
        "src.core.model_manager.get_model_manager",
        lambda: SimpleNamespace(
            get_default_model=lambda: "provider:model",
            get_default_params=lambda: {
                "temperature": 0.7,
                "reasoning_effort": "high",
            },
            get_provider=lambda _provider_id: {},
        ),
    )
    manager = SessionManager()
    session = AgentSession(
        session_id="model-context",
        session_type="sub",
        agent_type="plugin-page-assistant",
        lifecycle_profile="task",
        system_prompt="system prompt",
        model_params={"temperature": 0.2, "reasoning_effort": "low"},
    )
    session.lc_messages = [
        SystemMessage(content="system prompt"),
        HumanMessage(
            content="<PRODUCT_CONTEXT>{\"chapter\":3}</PRODUCT_CONTEXT>\n<USER_MESSAGE>你好</USER_MESSAGE>",
            additional_kwargs={
                "display_content": "你好",
                "source": "extension",
                "injection_meta": [{"name": "current_time"}],
                "model_context": {"chapter": 3},
            },
        ),
        AIMessage(content="回答"),
    ]
    session.record = [
        {"type": "user", "content": "你好"},
        {"type": "compression_divider", "content": "仅供前端展示"},
    ]
    manager.sessions[session.session_id] = session
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(session_manager=manager),
        ),
    )

    response = asyncio.run(get_session_system_prompt(session.session_id, request))

    assert response["context_scope"] == "current_effective"
    assert response["messages"] == [
        {"role": "system", "content": "system prompt"},
        {
            "role": "user",
            "content": "<PRODUCT_CONTEXT>{\"chapter\":3}</PRODUCT_CONTEXT>\n<USER_MESSAGE>你好</USER_MESSAGE>",
        },
        {"role": "assistant", "content": "回答"},
    ]
    assert response["message_counts"] == {
        "system": 1,
        "user": 1,
        "assistant": 1,
        "tool": 0,
    }
    assert response["model_config"]["temperature"] == 0.2
    assert response["model_config"]["model_params"]["reasoning_effort"] == "low"


def test_detached_invocation_passes_bounded_opaque_context(
    detached_runtime,
    monkeypatch,
):
    asyncio.run(_test_detached_invocation_context(detached_runtime, monkeypatch))


async def _test_detached_invocation_context(detached_runtime, monkeypatch):
    _, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-context",
        agent_type="plugin-page-assistant",
        scope_hash="scope-context",
    )

    async def send_message(self, content, **kwargs):
        assert kwargs["invocation_context"] == {
            "grant_id": "grant-1",
            "request_id": "request-1",
        }
        return "reply"

    monkeypatch.setattr(AgentSession, "send_message", send_message)
    assert await runtime.invoke(
        ref.session_id,
        "hello",
        invocation_context={"grant_id": "grant-1", "request_id": "request-1"},
    ) == "reply"


def test_detached_invocation_passes_immutable_model_context(
    detached_runtime,
    monkeypatch,
):
    asyncio.run(_test_detached_invocation_model_context(detached_runtime, monkeypatch))


async def _test_detached_invocation_model_context(detached_runtime, monkeypatch):
    _, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-model-context",
        agent_type="plugin-page-assistant",
        scope_hash="scope-model-context",
    )
    source_context = {
        "locale": "zh-CN",
        "page_context": {"surface": "workbench", "resource_key": None},
        "confirmed_action_observation": None,
    }

    async def send_message(self, content, **kwargs):
        assert content == "查看当前作品"
        assert kwargs["model_context"] == source_context
        kwargs["model_context"]["locale"] = "changed"
        return "reply"

    monkeypatch.setattr(AgentSession, "send_message", send_message)
    assert await runtime.invoke(
        ref.session_id,
        "查看当前作品",
        model_context=source_context,
    ) == "reply"
    assert source_context["locale"] == "zh-CN"


def test_detached_invocation_rejects_oversized_model_context(detached_runtime):
    asyncio.run(_test_detached_invocation_rejects_model_context(detached_runtime))


async def _test_detached_invocation_rejects_model_context(detached_runtime):
    _, runtime = detached_runtime
    with pytest.raises(ValueError, match="64 KiB"):
        await runtime.invoke(
            "missing-session",
            "hello",
            model_context={"payload": "x" * (64 * 1024)},
        )


def test_detached_runtime_resumes_original_pending_tool_calls(
    detached_runtime,
    monkeypatch,
):
    asyncio.run(_test_detached_runtime_resumes_tools(detached_runtime, monkeypatch))


async def _test_detached_runtime_resumes_tools(detached_runtime, monkeypatch):
    manager, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-resume",
        agent_type="plugin-page-assistant",
        scope_hash="scope-resume",
    )
    session = manager.sessions[ref.session_id]
    session.pending_tool_resolutions = {
        "call-write-1": {
            "name": "novelbuilt_chapters",
            "run_id": "call-write-1",
            "metadata": {"action_id": "action-1"},
        }
    }
    session.status = "awaiting_tool_resolution"
    captured: dict[str, object] = {}

    async def resume_tools(self, resolutions, **kwargs):
        captured["resolutions"] = resolutions
        captured["kwargs"] = kwargs
        return "批准后的最终回复"

    monkeypatch.setattr(AgentSession, "resume_tools", resume_tools)

    result = await runtime.resume_tools(
        ref.session_id,
        {"call-write-1": {"ok": True, "state": "succeeded"}},
        event_callback=None,
    )

    assert result == "批准后的最终回复"
    assert captured == {
        "resolutions": {"call-write-1": {"ok": True, "state": "succeeded"}},
        "kwargs": {"event_callback": None, "invocation_context": {}},
    }
    assert ref.session_id not in manager.sessions


def test_detached_invocation_rejects_invalid_opaque_context(detached_runtime):
    asyncio.run(_test_detached_invocation_rejects_context(detached_runtime))


async def _test_detached_invocation_rejects_context(detached_runtime):
    _, runtime = detached_runtime
    with pytest.raises(ValueError, match="无效键"):
        await runtime.invoke(
            "missing-session",
            "hello",
            invocation_context={"invalid key": "value"},
        )
    with pytest.raises(ValueError, match="单值过大"):
        await runtime.invoke(
            "missing-session",
            "hello",
            invocation_context={"grant_id": "x" * 4097},
        )


def test_detached_session_reuses_persisted_conversation_after_restart(
    detached_runtime,
    monkeypatch,
):
    asyncio.run(_test_detached_session_reuses(detached_runtime, monkeypatch))


async def _test_detached_session_reuses(detached_runtime, monkeypatch):
    manager, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-2",
        agent_type="plugin-page-assistant",
        scope_hash="scope-2",
    )

    async def first_turn(self, content, **kwargs):
        self.record.append({"id": "msg_00001", "type": "user", "content": content})
        return "first"

    monkeypatch.setattr(AgentSession, "send_message", first_turn)
    await runtime.invoke(ref.session_id, "first")

    restarted = SessionManager()
    restarted._prompt_builder = manager._prompt_builder
    restarted.load_sessions()
    restarted_runtime = ExtensionSessionRuntime(restarted).for_owner("example-plugin")
    reused = await restarted_runtime.ensure_detached(
        external_ref="portal-session-2",
        agent_type="plugin-page-assistant",
        scope_hash="scope-2",
    )
    assert reused.created is False
    assert reused.session_id == ref.session_id

    async def second_turn(self, content, **kwargs):
        assert self.record[-1]["content"] == "first"
        return "second"

    monkeypatch.setattr(AgentSession, "send_message", second_turn)
    assert await restarted_runtime.invoke(ref.session_id, "second") == "second"


def test_detached_session_refreshes_agent_model_override(detached_runtime, monkeypatch):
    asyncio.run(_test_detached_session_refreshes_agent_model(detached_runtime, monkeypatch))


async def _test_detached_session_refreshes_agent_model(detached_runtime, monkeypatch):
    manager, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-model",
        agent_type="plugin-page-assistant",
        scope_hash="scope-model",
    )
    replacement = SimpleNamespace(
        model="alpha:candidate",
        model_params={"temperature": 0.4},
        system_prompt_template="",
    )
    monkeypatch.setattr(
        "src.agent.definition.get_agent_definition",
        lambda agent_type: replacement if agent_type == "plugin-page-assistant" else None,
    )

    reused = await runtime.ensure_detached(
        external_ref="portal-session-model",
        agent_type="plugin-page-assistant",
        scope_hash="scope-model",
    )

    assert reused.created is False
    session = manager.sessions[ref.session_id]
    assert session.model_id == "alpha:candidate"
    assert session.model_params == {"temperature": 0.4}


def test_detached_session_replaces_failed_conversation(detached_runtime):
    asyncio.run(_test_detached_session_replaces_failed_conversation(detached_runtime))


async def _test_detached_session_replaces_failed_conversation(detached_runtime):
    manager, runtime = detached_runtime
    failed = await runtime.ensure_detached(
        external_ref="portal-session-failed",
        agent_type="plugin-page-assistant",
        scope_hash="scope-failed",
    )
    manager.sessions[failed.session_id].status = "error"

    replacement = await runtime.ensure_detached(
        external_ref="portal-session-failed",
        agent_type="plugin-page-assistant",
        scope_hash="scope-failed",
    )

    assert replacement.created is True
    assert replacement.session_id != failed.session_id
    assert manager.get_session(failed.session_id) is None
    assert manager.sessions[replacement.session_id].status == "completed"


def test_detached_session_fails_closed_across_owner_and_scope(detached_runtime):
    asyncio.run(_test_detached_session_fails_closed(detached_runtime))


async def _test_detached_session_fails_closed(detached_runtime):
    manager, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-3",
        agent_type="plugin-page-assistant",
        scope_hash="scope-3",
    )

    with pytest.raises(PermissionError, match="scope"):
        await runtime.ensure_detached(
            external_ref="portal-session-3",
            agent_type="plugin-page-assistant",
            scope_hash="different-scope",
        )

    other_owner = ExtensionSessionRuntime(manager).for_owner("other-plugin")
    with pytest.raises(PermissionError, match="owner"):
        other_owner._load_owned(ref.session_id)


def test_detached_session_creation_is_idempotent_under_concurrency(detached_runtime):
    asyncio.run(_test_detached_creation_is_idempotent(detached_runtime))


async def _test_detached_creation_is_idempotent(detached_runtime):
    manager, runtime = detached_runtime
    first, second = await asyncio.gather(
        runtime.ensure_detached(
            external_ref="portal-session-concurrent",
            agent_type="plugin-page-assistant",
            scope_hash="scope-concurrent",
        ),
        runtime.ensure_detached(
            external_ref="portal-session-concurrent",
            agent_type="plugin-page-assistant",
            scope_hash="scope-concurrent",
        ),
    )

    assert first.session_id == second.session_id
    assert sorted([first.created, second.created]) == [False, True]
    matching = [
        item
        for item in manager._session_catalog.values()
        if item.external_ref == "portal-session-concurrent"
    ]
    assert len(matching) == 1


def test_detached_invocation_lock_is_released_after_waiters_finish(
    detached_runtime,
    monkeypatch,
):
    asyncio.run(_test_detached_invocation_lock_is_released(detached_runtime, monkeypatch))


async def _test_detached_invocation_lock_is_released(detached_runtime, monkeypatch):
    _, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-lock",
        agent_type="plugin-page-assistant",
        scope_hash="scope-lock",
    )
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    active = 0
    peak = 0

    async def send_message(self, content, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if content == "first":
            first_started.set()
            await release_first.wait()
        active -= 1
        return content

    monkeypatch.setattr(AgentSession, "send_message", send_message)
    first = asyncio.create_task(runtime.invoke(ref.session_id, "first"))
    await first_started.wait()
    second = asyncio.create_task(runtime.invoke(ref.session_id, "second"))
    await asyncio.sleep(0)
    release_first.set()

    assert await asyncio.gather(first, second) == ["first", "second"]
    assert peak == 1
    assert ref.session_id not in runtime._invocation_locks
    assert ref.session_id not in runtime._invocation_users


def test_detached_session_can_be_deleted_by_owner_reference(detached_runtime):
    asyncio.run(_test_detached_session_delete_by_reference(detached_runtime))


async def _test_detached_session_delete_by_reference(detached_runtime):
    manager, runtime = detached_runtime
    ref = await runtime.ensure_detached(
        external_ref="portal-session-delete",
        agent_type="plugin-page-assistant",
        scope_hash="scope-delete",
    )

    assert (
        await runtime.delete_detached(
            external_ref="portal-session-delete",
            scope_hash="scope-delete",
        )
        is True
    )
    assert manager.get_session(ref.session_id) is None
    assert (
        await runtime.delete_detached(
            external_ref="portal-session-delete",
            scope_hash="scope-delete",
        )
        is False
    )


def test_existing_detached_turn_uses_current_prompt_without_losing_history(
    detached_runtime, monkeypatch,
):
    async def scenario():
        manager, runtime = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="prompt-refresh", agent_type="plugin-page-assistant", scope_hash="s",
        )
        session = manager.sessions[ref.session_id]
        session.record.append({"id": "old-user", "type": "user", "content": "previous"})
        await runtime._deactivate(session)
        manager._prompt_builder.build = lambda *args, **kwargs: "updated prompt"

        async def send(self, content, **kwargs):
            assert self.system_prompt == "updated prompt"
            assert self.lc_messages[0].content == "updated prompt"
            assert self.record[-1]["content"] == "previous"
            return "reply"

        monkeypatch.setattr(AgentSession, "send_message", send)
        assert await runtime.invoke(ref.session_id, "new question") == "reply"
        assert AgentSession.load(ref.session_id).system_prompt == "updated prompt"

    asyncio.run(scenario())


def test_detached_resume_and_observation_keep_the_turn_prompt(detached_runtime, monkeypatch):
    async def scenario():
        manager, runtime = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="prompt-resume", agent_type="plugin-page-assistant", scope_hash="s",
        )
        original = manager.sessions[ref.session_id].system_prompt
        manager._prompt_builder.build = lambda *args, **kwargs: "future prompt"

        async def resume(self, resolutions, **kwargs):
            assert self.system_prompt == original
            return "resumed"

        async def observe(self, content, **kwargs):
            assert content == ""
            assert self.system_prompt == original
            return "observed"

        monkeypatch.setattr(AgentSession, "resume_tools", resume)
        assert await runtime.resume_tools(ref.session_id, {"call": {"ok": True}}) == "resumed"
        monkeypatch.setattr(AgentSession, "send_message", observe)
        assert await runtime.invoke(ref.session_id, None, model_context={"result": "ok"}) == "observed"

    asyncio.run(scenario())


def test_blocked_new_message_does_not_refresh_pending_turn_prompt(detached_runtime):
    async def scenario():
        manager, runtime = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="prompt-pending", agent_type="plugin-page-assistant", scope_hash="s",
        )
        session = manager.sessions[ref.session_id]
        original = session.system_prompt
        session.pending_tool_resolutions = {"call": {"tool_call_id": "call"}}
        manager._prompt_builder.build = lambda *args, **kwargs: "future prompt"
        with pytest.raises(RuntimeError, match="等待外部工具结果"):
            await runtime.invoke(ref.session_id, "new question")
        assert AgentSession.load(ref.session_id).system_prompt == original

    asyncio.run(scenario())
