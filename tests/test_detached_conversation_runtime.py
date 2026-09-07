from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from httpx import Request, Response
from langchain_core.messages import AIMessage, HumanMessage
from openai import PermissionDeniedError

import src.agent.session as session_module
import src.agent.session_lifecycle as lifecycle_module
from src.agent.extension_sessions import ExtensionSessionRuntime
from src.agent.session import AgentSession, _persistence_manager
from src.agent.session_manager import SessionManager


class _FailingGraph:
    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    async def astream_events(self, _state, **_kwargs):
        self.calls += 1
        if False:  # pragma: no cover - keeps this an async generator
            yield {}
        raise self.error


class _HangGraph:
    def __init__(self, started: asyncio.Event):
        self.started = started
        self.calls = 0

    async def astream_events(self, _state, **_kwargs):
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        yield {}


def _quota_denied() -> PermissionDeniedError:
    body = {
        "error": {
            "code": "insufficient_user_quota",
            "message": "relay rejected secret-key-123",
        }
    }
    request = Request("POST", "https://example.com/v1/chat/completions")
    response = Response(403, request=request, json=body)
    return PermissionDeniedError(
        f"Error code: 403 - {body}",
        response=response,
        body=body,
    )


@pytest.fixture
def detached_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(lifecycle_module, "SESSIONS_DIR", tmp_path)
    agent_def = SimpleNamespace(
        model=None,
        model_params={},
        system_prompt_template="",
        max_turns=20,
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
        session.start_consumer()
        _persistence_manager.register(session)
        self._manager.register_runtime_session(session)

    monkeypatch.setattr(ExtensionSessionRuntime, "_configure_graph", configure)
    runtime = ExtensionSessionRuntime(manager).for_owner("example-plugin")
    return manager, runtime, graphs, agent_def


def test_detached_provider_failure_propagates_and_stays_failed(detached_runtime):
    async def scenario():
        manager, runtime, graphs, _ = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="portal-session-fail",
            agent_type="plugin-page-assistant",
            scope_hash="scope-fail",
        )
        session = manager.sessions[ref.session_id]
        session.record.append(
            {"id": "msg_00001", "type": "assistant", "content": "上一轮正常回复"}
        )
        session.lc_messages.append(AIMessage(content="上一轮正常回复"))
        error = _quota_denied()
        graphs["current"] = _FailingGraph(error)
        session.compiled_graph = graphs["current"]
        events: list[dict] = []

        async def callback(event):
            events.append(event)

        with pytest.raises(PermissionDeniedError):
            await runtime.invoke(
                ref.session_id,
                "继续",
                event_callback=callback,
            )

        assert ref.session_id not in manager.sessions
        persisted = AgentSession.load(ref.session_id)
        assert persisted is not None
        assert persisted.status == "error"
        assert persisted.last_error is not None
        assert persisted.last_error["code"] == "quota_exhausted"
        assert persisted.last_error["provider_error_code"] == "provider_quota_exhausted"
        assert "secret-key-123" not in persisted.last_error["message"]
        assert persisted.get_last_assistant_message() == "上一轮正常回复"
        error_events = [event for event in events if event.get("type") == "error"]
        assert len(error_events) == 1
        payload = json.dumps(error_events[0], ensure_ascii=False)
        assert error_events[0]["provider_error_code"] == "provider_quota_exhausted"
        assert error_events[0]["message"] != "上一轮正常回复"
        assert "secret-key-123" not in payload
        assert "insufficient_user_quota" not in payload
        assert session._consumer_task is None
        assert ref.session_id not in _persistence_manager._sessions

    asyncio.run(scenario())


def test_detached_invoke_does_not_override_agent_max_turns(detached_runtime, monkeypatch):
    async def scenario():
        _, runtime, _, agent_def = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="portal-session-turns",
            agent_type="plugin-page-assistant",
            scope_hash="scope-turns",
        )
        captured: dict[str, object] = {}

        async def send_message(self, content, **kwargs):
            captured["max_rounds"] = kwargs.get("max_rounds")
            captured["agent_max_turns"] = agent_def.max_turns
            return "ok"

        monkeypatch.setattr(AgentSession, "send_message", send_message)
        assert await runtime.invoke(ref.session_id, "hello") == "ok"
        assert captured["max_rounds"] is None
        assert captured["agent_max_turns"] == 20

    asyncio.run(scenario())


def test_cancelled_detached_invocation_settles_and_releases_listener(detached_runtime):
    async def scenario():
        manager, runtime, graphs, _ = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="portal-session-cancel",
            agent_type="plugin-page-assistant",
            scope_hash="scope-cancel",
        )
        session = manager.sessions[ref.session_id]
        session.record.append(
            {"id": "msg_00001", "type": "assistant", "content": "历史回复"}
        )
        session.lc_messages.append(AIMessage(content="历史回复"))
        started = asyncio.Event()
        graphs["current"] = _HangGraph(started)
        session.compiled_graph = graphs["current"]
        consumer = session._consumer_task
        assert consumer is not None and not consumer.done()

        task = asyncio.create_task(
            runtime.invoke(ref.session_id, "新问题"),
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert ref.session_id not in manager.sessions
        persisted = AgentSession.load(ref.session_id)
        assert persisted is not None
        assert persisted.status != "streaming"
        assert persisted.status in {"completed", "cancelled"}
        assert persisted.get_last_assistant_message() == "历史回复"
        assert not any(
            isinstance(message, HumanMessage) and message.content == "新问题"
            for message in persisted.lc_messages
        )
        assert session._consumer_task is None
        assert consumer.done()
        assert ref.session_id not in _persistence_manager._sessions

        reused = await runtime.ensure_detached(
            external_ref="portal-session-cancel",
            agent_type="plugin-page-assistant",
            scope_hash="scope-cancel",
        )
        assert reused.created is False
        assert reused.session_id == ref.session_id

    asyncio.run(scenario())


def test_cancelled_resume_releases_listener_without_stuck_streaming(
    detached_runtime,
    monkeypatch,
):
    async def scenario():
        manager, runtime, _, _ = detached_runtime
        ref = await runtime.ensure_detached(
            external_ref="portal-session-resume-cancel",
            agent_type="plugin-page-assistant",
            scope_hash="scope-resume-cancel",
        )
        session = manager.sessions[ref.session_id]
        started = asyncio.Event()

        async def hang_resume(self, resolutions, **kwargs):
            self.status = "streaming"
            started.set()
            await asyncio.Event().wait()
            return "should not complete"

        monkeypatch.setattr(AgentSession, "resume_tools", hang_resume)
        task = asyncio.create_task(
            runtime.resume_tools(ref.session_id, {"call-1": {"ok": True}}),
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        persisted = AgentSession.load(ref.session_id)
        assert persisted is not None
        assert persisted.status != "streaming"
        assert persisted.status == "cancelled"
        assert session._consumer_task is None
        assert ref.session_id not in manager.sessions

    asyncio.run(scenario())
