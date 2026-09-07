from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

from src.agent.definition import AgentDefinition
from src.agent.session import AgentSession
from src.agent.session_manager import SessionManager
from src.core.llm_client import REQUEST_FINGERPRINT_HEADER, create_llm
from src.core.model_manager import ModelManager
from src.workflow.definition import WorkflowDef, WorkflowNode
from src.workflow.nodes.agent import AgentNode
from src.workflow.nodes.base import NodeContext
from src.workflow.request_fingerprint import build_workflow_llm_request_fingerprint
from src.workflow.runtime_models import NodeExecutionState

_IDENTITY = {
    "workflow_id": "wf-retry-identity",
    "task_id": "task-retry-identity",
    "node_id": "writer",
    "model": "openai:gpt-test",
    "agent_type": "writer",
    "input_snapshot": {"topic": "frozen-topic"},
    "model_params": {"temperature": 0.2},
}


def _fingerprint(**overrides) -> str:
    payload = dict(_IDENTITY)
    payload.update(overrides)
    digest = build_workflow_llm_request_fingerprint(**payload)
    assert digest is not None
    return digest


def _write_models_config(path, *, api_format: str, model_name: str) -> ModelManager:
    providers = {
        "openai": {
            "name": "OpenAI Compatible",
            "provider_type": "openai_compatible",
            "api_format": "openai",
            "base_url": "https://relay.example.test/v1",
            "api_key": "test-key",
            "models": [model_name],
            "hyperparameter_values": {},
        },
        "anthropic": {
            "name": "Anthropic",
            "category": "anthropic",
            "api_format": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "test-key",
            "models": [model_name],
            "hyperparameter_values": {"max_completion_tokens": 8192},
        },
    }
    provider_id = "anthropic" if api_format == "anthropic" else "openai"
    path.write_text(
        json.dumps({
            "default_params": {"temperature": 0.7},
            "retry": {"max_retries": 0, "delays": []},
            "providers": {provider_id: providers[provider_id]},
        }),
        encoding="utf-8",
    )
    return ModelManager(str(path))


def _header_map(llm) -> dict:
    headers = dict(llm.default_headers or {})
    if hasattr(llm, "root_client"):
        headers.update(dict(llm.root_client.default_headers or {}))
    client = getattr(llm, "_client", None)
    if client is not None:
        headers.update(dict(getattr(client, "default_headers", None) or {}))
    return headers


def test_fingerprint_is_stable_across_frozen_node_retry():
    first = _fingerprint()
    retried = _fingerprint()

    assert first == retried
    assert len(first) == 64
    assert first.isalnum()
    assert first.islower()
    for secret in (
        _IDENTITY["workflow_id"],
        _IDENTITY["task_id"],
        "frozen-topic",
        "custom prompt must not leak",
        "Write the chapter now",
    ):
        assert secret not in first


def test_fingerprint_separates_distinct_task_node_input_and_model():
    baseline = _fingerprint()

    assert _fingerprint(workflow_id="wf-other") != baseline
    assert _fingerprint(task_id="task-other") != baseline
    assert _fingerprint(node_id="reviewer") != baseline
    assert _fingerprint(input_snapshot={"topic": "other-topic"}) != baseline
    assert _fingerprint(model="anthropic:claude-sonnet-4-6") != baseline
    assert _fingerprint(model_params={"temperature": 0.9}) != baseline


def test_fingerprint_ignores_key_order_in_frozen_input():
    left = _fingerprint(input_snapshot={"b": 2, "a": 1}, model_params={"y": 1, "x": 0})
    right = _fingerprint(input_snapshot={"a": 1, "b": 2}, model_params={"x": 0, "y": 1})
    assert left == right


def test_fingerprint_requires_workflow_attempt_identity():
    assert build_workflow_llm_request_fingerprint(
        workflow_id="",
        task_id=_IDENTITY["task_id"],
        node_id=_IDENTITY["node_id"],
    ) is None
    assert build_workflow_llm_request_fingerprint(
        workflow_id=_IDENTITY["workflow_id"],
        task_id="",
        node_id=_IDENTITY["node_id"],
    ) is None
    assert build_workflow_llm_request_fingerprint(
        workflow_id=_IDENTITY["workflow_id"],
        task_id=_IDENTITY["task_id"],
        node_id="",
    ) is None


def test_create_llm_injects_fingerprint_header_on_openai_and_anthropic(
    tmp_path,
    monkeypatch,
):
    digest = _fingerprint()
    cases = (
        ("openai", "gpt-test", ChatOpenAI),
        ("anthropic", "claude-sonnet-4-6", ChatAnthropic),
    )
    for api_format, model_name, llm_cls in cases:
        manager = _write_models_config(
            tmp_path / f"{api_format}-models.json",
            api_format=api_format,
            model_name=model_name,
        )
        monkeypatch.setattr(
            "src.core.model_manager.get_model_manager",
            lambda current=manager: current,
        )
        llm = create_llm(
            model_override=f"{'anthropic' if api_format == 'anthropic' else 'openai'}:{model_name}",
            request_fingerprint=digest,
            default_headers={"X-Existing": "keep"},
        )
        headers = _header_map(llm)
        assert isinstance(llm, llm_cls)
        assert headers[REQUEST_FINGERPRINT_HEADER] == digest
        assert headers["X-Existing"] == "keep"
        assert _IDENTITY["workflow_id"] not in headers[REQUEST_FINGERPRINT_HEADER]
        assert "frozen-topic" not in headers[REQUEST_FINGERPRINT_HEADER]


def test_create_llm_omits_fingerprint_header_without_workflow_identity(
    tmp_path,
    monkeypatch,
):
    manager = _write_models_config(
        tmp_path / "models_config.json",
        api_format="openai",
        model_name="gpt-test",
    )
    monkeypatch.setattr("src.core.model_manager.get_model_manager", lambda: manager)

    llm = create_llm(model_override="openai:gpt-test")
    headers = _header_map(llm)
    assert REQUEST_FINGERPRINT_HEADER not in headers


def test_create_llm_rejects_raw_identity_as_fingerprint(tmp_path, monkeypatch):
    manager = _write_models_config(
        tmp_path / "models_config.json",
        api_format="openai",
        model_name="gpt-test",
    )
    monkeypatch.setattr("src.core.model_manager.get_model_manager", lambda: manager)

    with pytest.raises(ValueError, match="SHA-256 hex digest"):
        create_llm(
            model_override="openai:gpt-test",
            request_fingerprint="wf-retry-identity",
        )


def _stub_sub_session_runtime(monkeypatch) -> list[dict]:
    captured: list[dict] = []

    def fake_create_llm(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(name="llm")

    def fake_setup_graph(self, *, llm, tools):
        self.tools = tools
        self.compiled_graph = object()

    async def fake_send_message(self, content, **_kwargs):
        self.status = "completed"
        return content

    async def fake_async_save(self, **_kwargs):
        return None

    monkeypatch.setattr("src.core.llm_client.create_llm", fake_create_llm)
    monkeypatch.setattr(AgentSession, "setup_graph", fake_setup_graph)
    monkeypatch.setattr(AgentSession, "start_consumer", lambda self: None)
    monkeypatch.setattr(AgentSession, "send_message", fake_send_message)
    monkeypatch.setattr(AgentSession, "async_save", fake_async_save)
    return captured


def _agent_definition() -> AgentDefinition:
    return AgentDefinition(
        agent_type="writer",
        description="fingerprint test writer",
        tools=[],
        model="openai:gpt-test",
        model_params={"temperature": 0.2},
        system_prompt_template="",
    )


async def _create_and_drain_sub_session(manager: SessionManager, **kwargs) -> dict:
    result = await manager.create_sub_session(**kwargs)
    assert result["success"] is True
    task = manager._sub_tasks.get(result["session_id"])
    if task is not None:
        await asyncio.wait_for(task, timeout=1)
    return result


def test_workflow_sub_session_sends_stable_fingerprint_and_chat_does_not(
    monkeypatch,
):
    captured = _stub_sub_session_runtime(monkeypatch)
    agent_def = _agent_definition()
    monkeypatch.setattr(
        "src.agent.definition.get_agent_definition",
        lambda agent_type: agent_def if agent_type == "writer" else None,
    )
    monkeypatch.setattr(
        "src.agent.definition.get_default_agent_definition",
        lambda: agent_def,
    )

    async def scenario():
        manager = SessionManager()
        manager._prompt_builder = SimpleNamespace(
            build=lambda _agent_type, **_kwargs: "system-prompt",
        )
        manager._tool_assembler = SimpleNamespace(build=lambda *_args, **_kwargs: [])

        first = await _create_and_drain_sub_session(
            manager,
            task_description="Write the chapter now",
            custom_prompt="custom prompt must not leak",
            agent_type="writer",
            is_workflow_node=True,
            workflow_id=_IDENTITY["workflow_id"],
            task_id=_IDENTITY["task_id"],
            node_id=_IDENTITY["node_id"],
            input_snapshot=_IDENTITY["input_snapshot"],
            model_params_override=_IDENTITY["model_params"],
        )
        retried = await _create_and_drain_sub_session(
            manager,
            task_description="Write the chapter now",
            custom_prompt="custom prompt must not leak",
            agent_type="writer",
            is_workflow_node=True,
            workflow_id=_IDENTITY["workflow_id"],
            task_id=_IDENTITY["task_id"],
            node_id=_IDENTITY["node_id"],
            input_snapshot=_IDENTITY["input_snapshot"],
            model_params_override=_IDENTITY["model_params"],
        )
        chat = await _create_and_drain_sub_session(
            manager,
            task_description="Write the chapter now",
            custom_prompt="custom prompt must not leak",
            agent_type="writer",
        )
        other_node = await _create_and_drain_sub_session(
            manager,
            task_description="Write the chapter now",
            custom_prompt="custom prompt must not leak",
            agent_type="writer",
            is_workflow_node=True,
            workflow_id=_IDENTITY["workflow_id"],
            task_id=_IDENTITY["task_id"],
            node_id="reviewer",
            input_snapshot=_IDENTITY["input_snapshot"],
            model_params_override=_IDENTITY["model_params"],
        )
        other_input = await _create_and_drain_sub_session(
            manager,
            task_description="Write the chapter now",
            custom_prompt="custom prompt must not leak",
            agent_type="writer",
            is_workflow_node=True,
            workflow_id=_IDENTITY["workflow_id"],
            task_id=_IDENTITY["task_id"],
            node_id=_IDENTITY["node_id"],
            input_snapshot={"topic": "other-topic"},
            model_params_override=_IDENTITY["model_params"],
        )
        return first, retried, chat, other_node, other_input

    asyncio.run(scenario())

    expected = _fingerprint()
    assert captured[0]["request_fingerprint"] == expected
    assert captured[1]["request_fingerprint"] == expected
    assert "request_fingerprint" not in captured[2]
    assert captured[3]["request_fingerprint"] != expected
    assert captured[4]["request_fingerprint"] != expected
    for call in captured[:2]:
        assert _IDENTITY["workflow_id"] not in call["request_fingerprint"]
        assert "Write the chapter now" not in call["request_fingerprint"]
        assert "custom prompt must not leak" not in call["request_fingerprint"]


def test_agent_node_passes_frozen_input_snapshot_not_prompt_text():
    captured: dict[str, object] = {}

    class FakeSessionManager:
        sessions: dict = {}

        async def create_sub_session(self, **kwargs):
            captured.update(kwargs)
            session_id = "node-session"
            self.sessions[session_id] = SimpleNamespace(
                record=[{"type": "assistant", "content": "ok"}],
                get_cumulative_token_usage=lambda: None,
            )
            kwargs["on_auto_complete"](session_id, "ok", "success", "")
            return {"success": True, "session_id": session_id}

    node = WorkflowNode(
        id="writer",
        node_type="agent",
        agent_type="writer",
        first_message="Write {{topic}}",
        system_prompt_template="Stay in character",
    )
    state = NodeExecutionState(
        node_id="writer",
        input_snapshot={"topic": "frozen-topic"},
    )
    asyncio.run(
        AgentNode().execute(
            NodeContext(
                definition=WorkflowDef(workflow_id="wf-retry-identity", nodes=[node]),
                node_def=node,
                node_state=state,
                session_manager=FakeSessionManager(),
                workflow_id="wf-retry-identity",
                task_id="task-retry-identity",
                parameter_values={"topic": "frozen-topic"},
            )
        )
    )

    assert captured["is_workflow_node"] is True
    assert captured["input_snapshot"] == {"topic": "frozen-topic"}
    assert captured["task_description"] == "Write frozen-topic"
    assert captured["custom_prompt"] == "Stay in character"
    assert "input_snapshot" in captured
    assert captured["custom_prompt"] not in json.dumps(captured["input_snapshot"])
