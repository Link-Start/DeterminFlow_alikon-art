from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import src.agent.session as session_module
import src.agent.session_lifecycle as lifecycle_module
from src.agent.extension_sessions import ExtensionSessionRuntime
from src.agent.session import AgentSession
from src.agent.session_manager import SessionManager
from src.core.tool_resolution import pending_tool_resolution


class _ResumeGraph:
    def __init__(
        self,
        events: list[dict] | None = None,
        error: Exception | None = None,
        hang: asyncio.Event | None = None,
    ):
        self.events = events or []
        self.error = error
        self.hang = hang
        self.calls = 0
        self.states: list[dict] = []

    async def astream_events(self, state, **_kwargs):
        self.calls += 1
        self.states.append(state)
        if self.hang is not None:
            self.hang.set()
            await asyncio.Event().wait()
        for event in self.events:
            if event.get("event") == "on_chain_end":
                output = dict((event.get("data") or {}).get("output") or {})
                extra = list(output.get("messages") or [])
                event = {
                    **event,
                    "data": {
                        **(event.get("data") or {}),
                        "output": {
                            **output,
                            "messages": [*state["messages"], *extra],
                        },
                    },
                }
            yield event
        if self.error is not None:
            raise self.error


def _tool_contents(session: AgentSession) -> list[tuple[str, str]]:
    return [
        (str(message.get("tool_call_id") or ""), str(message.get("content") or ""))
        for message in session.record
        if message.get("type") == "tool"
    ]


def _pending_session(*tool_call_ids: str, remaining: int = 2) -> AgentSession:
    session = AgentSession(session_type="sub", agent_type="test")
    session.record = [
        {"id": "msg_00001", "type": "user", "content": "执行操作"},
        {
            "id": "msg_00002",
            "type": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": "write", "arguments": "{}"},
                }
                for tool_call_id in tool_call_ids
            ],
        },
    ]
    session._msg_counter = 2
    session.lc_messages = [
        HumanMessage(content="执行操作"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": tool_call_id, "name": "write", "args": {}}
                for tool_call_id in tool_call_ids
            ],
        ),
    ]
    session.pending_tool_resolutions = {
        tool_call_id: {
            "name": "write",
            "run_id": tool_call_id,
            "metadata": {"action_id": f"action-{tool_call_id}"},
        }
        for tool_call_id in tool_call_ids
    }
    session.pending_tool_remaining_rounds = remaining
    session.status = "awaiting_tool_resolution"
    return session


def _success_events(text: str) -> list[dict]:
    final = AIMessage(content=text)
    return [
        {"event": "on_chat_model_end", "run_id": "resume-model", "data": {"output": final}},
        {
            "event": "on_chain_end",
            "tags": [],
            "data": {
                "output": {
                    "messages": [final],
                    "remaining_rounds": 1,
                }
            },
        },
    ]


def _next_pending_events(tool_call_id: str) -> list[dict]:
    model_output = AIMessage(
        content="",
        tool_calls=[{"id": tool_call_id, "name": "write", "args": {}}],
    )
    return [
        {
            "event": "on_chat_model_end",
            "run_id": "next-model",
            "data": {"output": model_output},
        },
        {
            "event": "on_tool_start",
            "run_id": "node-next",
            "name": "write",
            "data": {"input": {}},
        },
        {
            "event": "on_tool_end",
            "run_id": "node-next",
            "name": "write",
            "data": {
                "output": pending_tool_resolution(
                    tool_call_id=tool_call_id,
                    name="write",
                    metadata={"action_id": f"action-{tool_call_id}"},
                ),
            },
        },
        {
            "event": "on_chain_end",
            "tags": [],
            "data": {
                "output": {
                    "messages": [model_output],
                    "remaining_rounds": 1,
                }
            },
        },
    ]


async def _no_save(*_args, **_kwargs):
    return None


def test_resume_tools_survives_model_failure_without_duplicate_tool_messages():
    async def scenario():
        session = _pending_session("call-a", "call-b")
        session.compiled_graph = _ResumeGraph(error=RuntimeError("model failed"))
        session.async_save = _no_save
        resolutions = {
            "call-a": {"ok": True, "state": "succeeded", "value": 1},
            "call-b": {"ok": True, "state": "succeeded", "value": 2},
        }
        with pytest.raises(RuntimeError, match="model failed"):
            await session.resume_tools(resolutions)
        first_tools = _tool_contents(session)
        assert [item[0] for item in first_tools] == ["call-a", "call-b"]
        assert session.status != "error"
        assert session.pending_tool_resolutions == {}

        session.compiled_graph = _ResumeGraph(events=_success_events("续答完成"))
        result = await session.resume_tools(resolutions)
        return session, first_tools, result

    session, first_tools, result = asyncio.run(scenario())
    assert result == "续答完成"
    assert _tool_contents(session) == first_tools
    assert session.status == "completed"
    assert sum(isinstance(message, ToolMessage) for message in session.lc_messages) == 2


def test_resume_tools_rejects_same_ids_with_different_content():
    async def scenario():
        session = _pending_session("call-a")
        session.compiled_graph = _ResumeGraph(error=RuntimeError("model failed"))
        session.async_save = _no_save
        await _failed_resume(session, {"call-a": {"ok": True, "token": "alpha"}})
        with pytest.raises(ValueError, match="内容"):
            await session.resume_tools({"call-a": {"ok": True, "token": "beta"}})
        return _tool_contents(session)

    tools = asyncio.run(scenario())
    assert tools == [("call-a", '{"ok":true,"token":"alpha"}')]


def test_resume_tools_requires_exact_id_set():
    async def scenario():
        session = _pending_session("call-a", "call-b")
        session.compiled_graph = _ResumeGraph(events=_success_events("ok"))
        session.async_save = _no_save
        with pytest.raises(ValueError, match="精确匹配"):
            await session.resume_tools({"call-a": {"ok": True}})
        with pytest.raises(ValueError, match="精确匹配"):
            await session.resume_tools({
                "call-a": {"ok": True},
                "call-b": {"ok": True},
                "call-c": {"ok": True},
            })
        return session

    session = asyncio.run(scenario())
    assert session.pending_tool_resolutions.keys() == {"call-a", "call-b"}
    assert _tool_contents(session) == []


def test_accepted_resolutions_round_trip_without_invocation_grants():
    async def scenario():
        session = _pending_session("call-a")
        session.compiled_graph = _ResumeGraph(error=RuntimeError("model failed"))
        session.async_save = _no_save
        await _failed_resume(
            session,
            {"call-a": {"ok": True, "state": "succeeded"}},
            invocation_context={"grant_id": "grant-should-not-persist"},
        )
        snapshot = session.to_dict()
        restored = AgentSession.from_dict(snapshot)
        restored.compiled_graph = _ResumeGraph(events=_success_events("cold resume"))
        restored.async_save = _no_save
        result = await restored.resume_tools({"call-a": {"ok": True, "state": "succeeded"}})
        return snapshot, restored, result

    snapshot, restored, result = asyncio.run(scenario())
    dumped = json.dumps(snapshot, ensure_ascii=False)
    assert "grant-should-not-persist" not in dumped
    assert "invocation_context" not in snapshot
    assert "accepted_tool_resume" in snapshot
    assert result == "cold resume"
    assert _tool_contents(restored) == [
        ("call-a", '{"ok":true,"state":"succeeded"}'),
    ]
    assert sum(
        1 for message in restored.record if message.get("type") == "tool"
    ) == 1


def test_completed_resume_replays_without_reinvoking_graph():
    async def scenario():
        session = _pending_session("call-a")
        graph = _ResumeGraph(events=_success_events("最终回复"))
        session.compiled_graph = graph
        session.async_save = _no_save
        first = await session.resume_tools({"call-a": {"ok": True}})
        second = await session.resume_tools({"call-a": {"ok": True}})
        return session, graph, first, second

    session, graph, first, second = asyncio.run(scenario())
    assert first == second == "最终回复"
    assert graph.calls == 1
    assert _tool_contents(session) == [("call-a", '{"ok":true}')]


def test_next_approval_group_does_not_replay_old_tools():
    async def scenario():
        session = _pending_session("call-old")
        session.compiled_graph = _ResumeGraph(events=_next_pending_events("call-new"))
        session.async_save = _no_save
        await session.resume_tools({"call-old": {"ok": True, "batch": 1}})
        old_tools = _tool_contents(session)
        assert session.status == "awaiting_tool_resolution"
        assert set(session.pending_tool_resolutions) == {"call-new"}

        replayed = []

        async def collect(event):
            replayed.append(event)

        await session.resume_tools(
            {"call-old": {"ok": True, "batch": 1}}, event_callback=collect,
        )
        assert session.compiled_graph.calls == 1
        assert len(replayed) == 1
        assert replayed[0]["type"] == "tool_pending"
        assert replayed[0]["tool_call_id"] == "call-new"
        assert replayed[0]["metadata"] == {"action_id": "action-call-new"}
        with pytest.raises(ValueError, match="精确匹配"):
            await session.resume_tools({
                "call-old": {"ok": True, "batch": 1},
                "call-new": {"ok": True, "batch": 2},
            })

        session.compiled_graph = _ResumeGraph(events=_success_events("第二组完成"))
        result = await session.resume_tools({"call-new": {"ok": True, "batch": 2}})
        replay = await session.resume_tools({"call-new": {"ok": True, "batch": 2}})
        return session, old_tools, result, replay

    session, old_tools, result, replay = asyncio.run(scenario())
    assert result == replay == "第二组完成"
    assert old_tools == [("call-old", '{"batch":1,"ok":true}')]
    assert _tool_contents(session) == [
        ("call-old", '{"batch":1,"ok":true}'),
        ("call-new", '{"batch":2,"ok":true}'),
    ]


def test_resume_tools_fails_closed_after_new_tool_side_effect():
    async def scenario():
        session = _pending_session("call-a")
        session.compiled_graph = _ResumeGraph(
            events=[
                {
                    "event": "on_tool_start",
                    "run_id": "side-effect",
                    "name": "write_file",
                    "data": {"input": {"path": "/tmp/out.txt"}},
                },
            ],
            error=RuntimeError("failed after tool start"),
        )
        session.async_save = _no_save
        with pytest.raises(RuntimeError, match="failed after tool start"):
            await session.resume_tools({"call-a": {"ok": True}})
        with pytest.raises(RuntimeError, match="副作用"):
            await session.resume_tools({"call-a": {"ok": True}})
        return session

    session = asyncio.run(scenario())
    assert session.status == "error"


def test_cancelled_resume_keeps_filled_tools_and_can_continue():
    async def scenario():
        session = _pending_session("call-a")
        started = asyncio.Event()
        session.compiled_graph = _ResumeGraph(hang=started)
        session.async_save = _no_save
        task = asyncio.create_task(
            session.resume_tools({"call-a": {"ok": True, "state": "succeeded"}})
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        filled = _tool_contents(session)
        session.compiled_graph = _ResumeGraph(events=_success_events("取消后续答"))
        result = await session.resume_tools(
            {"call-a": {"ok": True, "state": "succeeded"}}
        )
        return session, filled, result

    session, filled, result = asyncio.run(scenario())
    assert filled == [("call-a", '{"ok":true,"state":"succeeded"}')]
    assert _tool_contents(session) == filled
    assert result == "取消后续答"


def test_interactive_main_send_message_recovery_is_unchanged():
    async def scenario():
        session = AgentSession(
            session_type="main",
            agent_type="test",
            runtime_scope="interactive",
        )
        session.compiled_graph = _ResumeGraph(error=RuntimeError("provider failed"))
        session.async_save = _no_save

        async def no_compress(*_args, **_kwargs):
            return None

        session._check_and_compress_messages = no_compress
        try:
            await session.send_message("hello")
        except RuntimeError:
            pass
        return session

    session = asyncio.run(scenario())
    assert session.status == "running"
    assert session.failed_turn is not None
    assert session.failed_turn["retryable"] is True
    assert session.record == []


def test_send_message_stays_blocked_while_resume_is_incomplete():
    async def scenario():
        session = _pending_session("call-a")
        session.compiled_graph = _ResumeGraph(error=RuntimeError("model failed"))
        session.async_save = _no_save
        await _failed_resume(session, {"call-a": {"ok": True}})
        with pytest.raises(RuntimeError, match="外部工具"):
            await session.send_message("another turn")
        return session.status

    status = asyncio.run(scenario())
    assert status != "error"


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
    graphs: dict[str, object] = {"current": object()}

    def configure(self, session):
        session.compiled_graph = graphs["current"]
        self._manager.register_runtime_session(session)

    monkeypatch.setattr(ExtensionSessionRuntime, "_configure_graph", configure)
    runtime = ExtensionSessionRuntime(manager).for_owner("example-plugin")
    return manager, runtime, graphs


def test_detached_runtime_resumes_after_error_and_cold_reload(detached_runtime):
    async def scenario():
        manager, runtime, graphs = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="portal-session-resume-recovery",
            agent_type="plugin-page-assistant",
            scope_hash="scope-resume-recovery",
        )
        session = manager.sessions[ref.session_id]
        _install_pending(session, "call-write-1")
        graphs["current"] = _ResumeGraph(error=RuntimeError("model failed"))
        session.compiled_graph = graphs["current"]
        with pytest.raises(RuntimeError, match="model failed"):
            await runtime.resume_tools(
                ref.session_id,
                {"call-write-1": {"ok": True, "state": "succeeded"}},
                invocation_context={"grant_id": "short-lived-grant"},
            )
        assert ref.session_id not in manager.sessions

        persisted = AgentSession.load(ref.session_id)
        assert persisted is not None
        assert "grant_id" not in str(persisted.to_dict())
        assert persisted.status != "error" or bool(
            persisted.to_dict().get("accepted_tool_resume")
        )

        reused = await runtime.ensure_detached(
            external_ref="portal-session-resume-recovery",
            agent_type="plugin-page-assistant",
            scope_hash="scope-resume-recovery",
        )
        assert reused.created is False
        assert reused.session_id == ref.session_id

        graphs["current"] = _ResumeGraph(events=_success_events("cold runtime resume"))
        result = await runtime.resume_tools(
            ref.session_id,
            {"call-write-1": {"ok": True, "state": "succeeded"}},
            invocation_context={"grant_id": "retry-grant"},
        )
        loaded = AgentSession.load(ref.session_id)
        return result, loaded

    result, loaded = asyncio.run(scenario())
    assert result == "cold runtime resume"
    assert loaded is not None
    assert _tool_contents(loaded) == [
        ("call-write-1", '{"ok":true,"state":"succeeded"}'),
    ]
    assert loaded.status == "completed"


def test_detached_runtime_replays_completed_result_after_lost_response(
    detached_runtime,
):
    async def scenario():
        _manager, runtime, graphs = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="portal-session-replay",
            agent_type="plugin-page-assistant",
            scope_hash="scope-replay",
        )
        session = _manager.sessions[ref.session_id]
        _install_pending(session, "call-write-1")
        graph = _ResumeGraph(events=_success_events("已完成回复"))
        graphs["current"] = graph
        session.compiled_graph = graph
        first = await runtime.resume_tools(
            ref.session_id,
            {"call-write-1": {"ok": True}},
        )
        second = await runtime.resume_tools(
            ref.session_id,
            {"call-write-1": {"ok": True}},
        )
        return first, second, graph.calls

    first, second, calls = asyncio.run(scenario())
    assert first == second == "已完成回复"
    assert calls == 1


def test_detached_concurrent_resume_is_serialized(detached_runtime):
    async def scenario():
        _manager, runtime, graphs = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="portal-session-concurrent-resume",
            agent_type="plugin-page-assistant",
            scope_hash="scope-concurrent-resume",
        )
        session = _manager.sessions[ref.session_id]
        _install_pending(session, "call-write-1")
        started = asyncio.Event()
        graphs["current"] = _ResumeGraph(hang=started)
        session.compiled_graph = graphs["current"]
        first = asyncio.create_task(
            runtime.resume_tools(ref.session_id, {"call-write-1": {"ok": True}})
        )
        await started.wait()
        second = asyncio.create_task(
            runtime.resume_tools(ref.session_id, {"call-write-1": {"ok": True}})
        )
        await asyncio.sleep(0)
        graphs["current"] = _ResumeGraph(events=_success_events("after-wait"))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second_result = await asyncio.wait_for(second, timeout=5)
        loaded = AgentSession.load(ref.session_id)
        return second_result, loaded

    second_result, loaded = asyncio.run(scenario())
    assert second_result == "after-wait"
    assert loaded is not None
    assert _tool_contents(loaded) == [("call-write-1", '{"ok":true}')]


async def _failed_resume(session: AgentSession, resolutions: dict, **kwargs) -> None:
    with pytest.raises(RuntimeError):
        await session.resume_tools(resolutions, **kwargs)


def _install_pending(session: AgentSession, tool_call_id: str) -> None:
    session.record = [
        {"id": "msg_00001", "type": "user", "content": "执行操作"},
        {
            "id": "msg_00002",
            "type": "assistant",
            "content": "",
            "tool_calls": [{
                "id": tool_call_id,
                "type": "function",
                "function": {"name": "write", "arguments": "{}"},
            }],
        },
    ]
    session._msg_counter = 2
    session.lc_messages = [
        HumanMessage(content="执行操作"),
        AIMessage(
            content="",
            tool_calls=[{"id": tool_call_id, "name": "write", "args": {}}],
        ),
    ]
    session.pending_tool_resolutions = {
        tool_call_id: {
            "name": "write",
            "run_id": tool_call_id,
            "metadata": {"action_id": "action-1"},
        }
    }
    session.pending_tool_remaining_rounds = 2
    session.status = "awaiting_tool_resolution"


def test_cancel_after_new_tool_start_fails_closed():
    async def scenario():
        session = _pending_session('call-a')
        session.compiled_graph = _ResumeGraph(events=_next_pending_events('call-new'))
        session.async_save = _no_save

        async def cancel_at_tool(event):
            if event['type'] == 'tool_start':
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await session.resume_tools({'call-a': {'ok': True}}, event_callback=cancel_at_tool)
        restored = AgentSession.from_dict(session.to_dict())
        restored.compiled_graph = _ResumeGraph(events=_success_events('must not run'))
        restored.async_save = _no_save
        with pytest.raises(RuntimeError, match='副作用'):
            await restored.resume_tools({'call-a': {'ok': True}})
        assert restored.compiled_graph.calls == 0
        assert restored.status == 'error'

    asyncio.run(scenario())


def test_accepted_results_must_be_durable_before_model_execution():
    async def scenario():
        session = _pending_session('call-a')
        session.compiled_graph = _ResumeGraph(events=_success_events('must not run'))

        async def failing_save(*, force=False, strict=False):
            if force and strict:
                raise OSError('injected disk failure')

        session.async_save = failing_save
        with pytest.raises(OSError, match='disk failure'):
            await session.resume_tools({'call-a': {'ok': True}})
        assert session.compiled_graph.calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize('next_approval', [False, True])
def test_lost_terminal_event_replays_durable_result(next_approval):
    async def scenario():
        session = _pending_session('call-a')
        graph = _ResumeGraph(events=(
            _next_pending_events('call-b') if next_approval else _success_events('saved reply')
        ))
        session.compiled_graph = graph
        session.async_save = _no_save

        async def lost(event):
            if event['type'] == 'stream_end':
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await session.resume_tools({'call-a': {'ok': True}}, event_callback=lost)
        restored = AgentSession.from_dict(session.to_dict())
        restored.compiled_graph = graph
        restored.async_save = _no_save
        events = []

        async def collect(event):
            events.append(event)

        result = await restored.resume_tools({'call-a': {'ok': True}}, event_callback=collect)
        assert graph.calls == 1
        assert _tool_contents(restored) == [('call-a', '{"ok":true}')]
        if next_approval:
            assert len(events) == 1 and events[0]['tool_call_id'] == 'call-b'
        else:
            assert result == 'saved reply'

    asyncio.run(scenario())


def test_unsafe_resume_is_not_deleted_by_ensure(detached_runtime):
    async def scenario():
        manager, runtime, graphs = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref='unsafe-session', agent_type='plugin-page-assistant', scope_hash='unsafe-scope',
        )
        session = manager.sessions[ref.session_id]
        _install_pending(session, 'call-a')
        graphs['current'] = _ResumeGraph(events=[{
            'event': 'on_tool_start', 'run_id': 'side-effect', 'name': 'write',
            'data': {'input': {}},
        }], error=RuntimeError('uncertain outcome'))
        session.compiled_graph = graphs['current']
        with pytest.raises(RuntimeError, match='uncertain outcome'):
            await runtime.resume_tools(ref.session_id, {'call-a': {'ok': True}})
        reused = await runtime.ensure_detached(
            external_ref='unsafe-session', agent_type='plugin-page-assistant', scope_hash='unsafe-scope',
        )
        assert reused.session_id == ref.session_id and not reused.created
        with pytest.raises(RuntimeError, match='error'):
            await runtime.resume_tools(ref.session_id, {'call-a': {'ok': True}})
        persisted = AgentSession.load(ref.session_id)
        assert persisted.accepted_tool_resume['phase'] == 'unsafe'

    asyncio.run(scenario())


@pytest.mark.parametrize('phase', ['filled', 'completed'])
def test_cancel_during_checkpoint_save_preserves_accepted_messages(phase):
    async def scenario():
        session = _pending_session('call-a')
        graph = _ResumeGraph(events=_success_events('saved'))
        session.compiled_graph = graph
        cancelled = False

        async def cancel_save(*, force=False, strict=False):
            nonlocal cancelled
            accepted = session.accepted_tool_resume or {}
            if force and strict and accepted.get('phase') == phase and not cancelled:
                cancelled = True
                raise asyncio.CancelledError()

        session.async_save = cancel_save
        with pytest.raises(asyncio.CancelledError):
            await session.resume_tools({'call-a': {'ok': True}})
        assert _tool_contents(session) == [('call-a', '{"ok":true}')]
        assert sum(isinstance(message, ToolMessage) for message in session.lc_messages) == 1
        assert await session.resume_tools({'call-a': {'ok': True}}) == 'saved'
        assert graph.calls == 1
        assert _tool_contents(session) == [('call-a', '{"ok":true}')]

    asyncio.run(scenario())
