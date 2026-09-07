from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.workflow.definition import WorkflowDef, WorkflowNode
from src.workflow.nodes.agent import AgentNode
from src.workflow.nodes.base import NodeContext
from src.workflow.runtime_models import NodeExecutionState


def _run_node(
    node: WorkflowNode,
    session_manager,
) -> tuple[object, NodeExecutionState]:
    state = NodeExecutionState(node_id=node.id)
    result = asyncio.run(
        AgentNode().execute(
            NodeContext(
                definition=WorkflowDef(
                    workflow_id="wf-output-recovery",
                    nodes=[node],
                ),
                node_def=node,
                node_state=state,
                session_manager=session_manager,
            )
        )
    )
    return result, state


def test_ungated_output_does_not_fall_back_to_older_assistant_message() -> None:
    class SessionManager:
        def __init__(self):
            self.sessions = {}

        async def create_sub_session(self, **kwargs):
            session_id = "latest-empty"
            self.sessions[session_id] = SimpleNamespace(
                record=[
                    {"type": "assistant", "content": "older result"},
                    {"type": "assistant", "content": ""},
                ],
                get_cumulative_token_usage=lambda: None,
            )
            kwargs["on_auto_complete"](session_id, "done", "success", "")
            return {"success": True, "session_id": session_id}

    result, _state = _run_node(
        WorkflowNode(
            id="writer",
            node_type="agent",
            first_message="write",
            output_variable="draft",
        ),
        SessionManager(),
    )

    assert result.status == "completed"
    assert result.outputs == {}


def test_empty_output_fails_attempt_without_original_session_repair() -> None:
    sends = 0

    class Session:
        record = [{"type": "assistant", "content": ""}]

        async def send_message(self, *_args, **_kwargs):
            nonlocal sends
            sends += 1

        def get_cumulative_token_usage(self):
            return {"provider:model": {"total_tokens": 10}}

    class SessionManager:
        def __init__(self):
            self.sessions = {}

        async def create_sub_session(self, **kwargs):
            session_id = "empty-output"
            self.sessions[session_id] = Session()
            kwargs["on_auto_complete"](session_id, "done", "success", "")
            return {"success": True, "session_id": session_id}

    result, state = _run_node(
        WorkflowNode(
            id="writer",
            node_type="agent",
            first_message="write",
            require_non_empty_output=True,
            retry_empty_output_in_session=True,
            output_repair_max_count=5,
        ),
        SessionManager(),
    )

    assert result.status == "failed"
    assert "[empty_output]" in result.error
    assert result.outputs == {}
    assert sends == 0
    assert state.output_repair_count == 0
    assert state.output_repair_history == []


def test_json_retry_policy_fails_attempt_without_calling_model() -> None:
    result = asyncio.run(
        AgentNode()._prepare_json_output(
            raw_output="{",
            node_params={"json_repair_policy": "retry_only"},
            output_file_path="result.json",
        )
    )

    assert result["success"] is False
    assert "[invalid_json]" in result["error"]
    assert result["meta"]["_json_retry_attempts"] == "0"


def test_json_safe_repair_remains_deterministic_and_local() -> None:
    result = asyncio.run(
        AgentNode()._prepare_json_output(
            raw_output='```json\n{"body":"ok"}\n```',
            node_params={"json_repair_policy": "safe_repair_then_retry"},
            output_file_path="result.json",
        )
    )

    assert result["success"] is True
    assert '"body": "ok"' in result["text"]
    assert result["meta"]["_json_retry_attempts"] == "0"
    assert result["meta"]["_json_repair_applied"]


def test_last_assistant_message_does_not_skip_latest_empty_message() -> None:
    from src.agent.session import AgentSession
    from src.agent.session_catalog import SessionMetadata

    session = AgentSession(session_id="latest-assistant")
    session.record = [
        {"type": "assistant", "content": "older result"},
        {"type": "assistant", "content": ""},
    ]

    assert session.get_last_assistant_message() == ""
    assert SessionMetadata.from_data({
        "session_id": "latest-assistant",
        "record": session.record,
    }).last_message == ""
