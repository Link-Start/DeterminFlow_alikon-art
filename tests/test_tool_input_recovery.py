import asyncio
import json
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, StrictInt, ValidationError

from src.agent.session import AgentSession
from src.core.graph_builder import build_graph
from src.core.tool_errors import repeats_invalid_call, validation_error_content
from src.core.tool_resolution import pending_tool_resolution
from src.core.tool_schema import parameter_summary


class QueryInput(BaseModel):
    limit: StrictInt = Field(default=10, ge=1, le=20)


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    position: int = 0
    offered_tools: list[bool] = Field(default_factory=list)
    received_messages: list[list] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "scripted-recovery-test"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools_offered=True)

    def _next(self, kwargs):
        self.offered_tools.append(kwargs.get("tools_offered", False))
        response = self.responses[self.position]
        self.position += 1
        return response

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.received_messages.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self._next(kwargs))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.received_messages.append(list(messages))
        response = self._next(kwargs)
        yield ChatGenerationChunk(message=AIMessageChunk(
            content=response.content,
            tool_call_chunks=[
                {"id": call["id"], "name": call["name"], "index": index,
                 "args": json.dumps(call["args"])}
                for index, call in enumerate(response.tool_calls)
            ],
        ))


def request(call_id, limit):
    return AIMessage(content="正在查询。", tool_calls=[
        {"id": call_id, "name": "query", "args": {"limit": limit}},
    ])


def run_session(responses, rounds=6, *, tool_result=None):
    invoked = []

    async def query(limit=10):
        invoked.append(limit)
        return tool_result if tool_result is not None else '{"ok":true,"count":3}'

    tool = StructuredTool.from_function(
        coroutine=query, name="query", description="Query items", args_schema=QueryInput,
    )
    model = ScriptedModel(responses=responses)

    async def scenario():
        session = AgentSession(session_type="sub", agent_type="test")
        session.tools = [tool]
        session.compiled_graph = build_graph(model, [tool]).compile()
        events = []

        async def no_op(*args, **kwargs):
            return None

        async def callback(event):
            events.append(event)

        session.async_save = no_op
        session._check_and_compress_messages = no_op
        await session.send_message("最近作品该先推进哪一本", callback, max_rounds=rounds)
        return session, events

    session, events = asyncio.run(scenario())
    return session, events, invoked, model


def test_real_graph_validation_feedback_allows_corrected_retry_and_matches_stream_ids():
    session, events, invoked, model = run_session([
        request("invalid", "private-invalid-value"), request("corrected", 10),
        AIMessage(content="查询完成，共 3 部作品。"),
    ])
    assert invoked == [10]
    ends = [event for event in events if event["type"] == "tool_end"]
    assert [(event["run_id"], event["status"]) for event in ends] == [
        ("invalid", "failed"), ("corrected", "completed"),
    ]
    error = json.loads(ends[0]["result"])["error"]
    assert error["code"] == "tool_arguments_invalid"
    assert error["fields"] == [{"field": "limit", "rule": "int_type"}]
    assert "private-invalid-value" not in ends[0]["result"]
    deltas = [event for event in events if event["type"] == "tool_call_delta"]
    assert [event["id"] for event in deltas] == ["invalid", "corrected"]
    assert deltas[0]["name"] == "query"
    assert json.loads(deltas[1]["args_delta"]) == {"limit": 10}
    assert session.get_last_assistant_message() == "查询完成，共 3 部作品。"
    assert len([entry for entry in session.record if entry["type"] == "tool"]) == 2


def test_repeated_invalid_batch_gets_a_final_answer_without_more_tools():
    session, events, invoked, model = run_session([
        request("first", "bad"), request("repeat", "bad"),
        AIMessage(content="查询未完成，参数无法修正。"),
    ])
    assert invoked == []
    assert model.position == 3
    assert model.offered_tools == [True, True, False]
    ends = [event for event in events if event["type"] == "tool_end"]
    assert [event["run_id"] for event in ends] == ["first", "repeat"]
    assert all(event["status"] == "failed" for event in ends)
    assert json.loads(ends[-1]["result"])["error"]["code"] == "tool_arguments_repeated"
    assert "未完成" in session.get_last_assistant_message()
    assert session.record[-1]["type"] == "assistant"
    assert len([entry for entry in session.record if entry["type"] == "tool"]) == 2
    calls = {call["id"] for message in session.lc_messages if isinstance(message, AIMessage)
             for call in message.tool_calls}
    assert calls == {message.tool_call_id for message in session.lc_messages
                     if isinstance(message, ToolMessage)}


def test_mixed_batch_blocks_only_repeated_invalid_call_and_keeps_successful_results():
    session, events, invoked, model = run_session([
        request("first", "bad"),
        AIMessage(content="", tool_calls=[
            *request("repeat", "bad").tool_calls,
            *request("new-a", 2).tool_calls,
            *request("new-b", 3).tool_calls,
        ]),
        request("corrected", 4),
        AIMessage(content="两次独立查询和修正后的查询均完成。"),
    ])
    assert sorted(invoked) == [2, 3, 4]
    assert model.offered_tools == [True, True, True, True]
    ends = {e["run_id"]: e for e in events if e["type"] == "tool_end"}
    assert set(ends) == {"first", "repeat", "new-a", "new-b", "corrected"}
    assert json.loads(ends["repeat"]["result"])["error"]["code"] == "tool_arguments_repeated"
    assert all(ends[call_id]["status"] == "completed" for call_id in ("new-a", "new-b", "corrected"))
    # The model can synthesize every successful result, with complete call/result pairs.
    results = [m for m in model.received_messages[-1] if isinstance(m, ToolMessage)]
    assert {m.tool_call_id for m in results if m.status != "error"} == {"new-a", "new-b", "corrected"}
    assert session.get_last_assistant_message() == "两次独立查询和修正后的查询均完成。"


def test_noncompliant_call_after_all_repeated_batch_still_terminates():
    session, events, invoked, model = run_session([
        request("first", "bad"), request("repeat", "bad"), request("ignored-final", 10),
    ])
    assert invoked == []
    assert model.offered_tools == [True, True, False]
    assert model.position == 3
    ends = [e for e in events if e["type"] == "tool_end"]
    assert len(ends) == 3
    assert json.loads(ends[-1]["result"])["error"]["code"] != "tool_arguments_repeated"
    assert session.record[-1]["type"] == "assistant"


def test_last_round_does_not_offer_tools_and_settles_noncompliant_model_call():
    session, events, invoked, model = run_session([request("exhausted", 10)], rounds=1)
    assert model.offered_tools == [False]
    assert invoked == []
    ends = [event for event in events if event["type"] == "tool_end"]
    assert len(ends) == 1
    assert ends[0]["run_id"] == "exhausted"
    assert json.loads(ends[0]["result"])["error"]["code"] == "tool_round_limit"
    assert "未执行" in session.get_last_assistant_message()


def test_pending_approval_is_not_failed_or_retried():
    pending = pending_tool_resolution(tool_call_id="approval", name="query", metadata={"id": "p"})
    session, events, invoked, model = run_session([request("approval", 10)], tool_result=pending)
    assert invoked == [10]
    assert model.position == 1
    assert session.status == "awaiting_tool_resolution"
    assert not any(event["type"] == "tool_end" for event in events)


def test_repeated_invalid_sibling_does_not_cancel_pending_confirmation():
    pending = pending_tool_resolution(tool_call_id="approval", name="query", metadata={"id": "p"})
    session, events, invoked, model = run_session([
        request("first", "bad"),
        AIMessage(content="", tool_calls=[
            *request("repeat", "bad").tool_calls, *request("approval", 10).tool_calls,
        ]),
    ], tool_result=pending)
    assert invoked == [10]
    assert model.position == 2
    assert session.status == "awaiting_tool_resolution"
    assert {e["run_id"] for e in events if e["type"] == "tool_end"} == {"first", "repeat"}


def test_business_error_is_not_treated_as_repeated_invalid_arguments():
    result = ToolMessage(
        content='{"ok":false,"error":{"code":"version_conflict"}}',
        tool_call_id="first", name="query", status="error",
    )
    assert not repeats_invalid_call([
        HumanMessage(content="query"), request("first", 10), result,
    ], request("retry", 10).tool_calls)


def test_repeat_detection_preserves_types_and_resets_at_new_user_turn():
    invalid = ToolMessage(
        content='{"ok":false,"error":{"code":"tool_arguments_invalid"}}',
        tool_call_id="old", status="error",
    )
    messages = [HumanMessage(content="query"), request("old", True), invalid]
    assert not repeats_invalid_call(messages, request("fixed", 1).tool_calls)
    assert repeats_invalid_call(messages, request("same", True).tool_calls)
    assert not repeats_invalid_call([*messages, HumanMessage(content="retry")], request("new", True).tool_calls)


def test_validation_error_exposes_constraints_without_input():
    with pytest.raises(ValidationError) as exc:
        QueryInput(limit=21)
    error = json.loads(validation_error_content(exc.value))["error"]
    assert error["fields"] == [{"field": "limit", "rule": "less_than_equal", "le": 20}]


def test_schema_summary_preserves_nullable_array_and_integer_constraints():
    schema = {"anyOf": [{"type": "array", "items": {"type": "integer", "minimum": 1}}, {"type": "null"}], "default": None}
    summary = parameter_summary(schema, False)
    assert summary["type"] == "array<integer> | null"
    assert summary["anyOf"] == schema["anyOf"]
    assert summary["default"] is None
    summary = parameter_summary({"anyOf": [{"type": "integer", "minimum": 1, "maximum": 20}, {"type": "null"}]}, False)
    assert summary["type"] == "integer | null"
    assert summary["anyOf"][0]["maximum"] == 20


def test_parallel_tool_chunks_keep_distinct_indices_and_terminal_ids():
    calls = [*request("a", 2).tool_calls, *request("b", 3).tool_calls]
    session, events, invoked, _ = run_session([
        AIMessage(content="", tool_calls=calls), AIMessage(content="done"),
    ])
    assert sorted(invoked) == [2, 3]
    deltas = [event for event in events if event["type"] == "tool_call_delta"]
    assert [(event["index"], event["id"]) for event in deltas] == [(0, "a"), (1, "b")]
    ends = [event for event in events if event["type"] == "tool_end"]
    assert {event["run_id"] for event in ends} == {"a", "b"}
    assert all(event["status"] == "completed" for event in ends)


@pytest.mark.parametrize("ending", ["missing", "cancel", "error"])
def test_incomplete_execution_is_closed_before_terminal_snapshot(ending):
    async def scenario():
        session = AgentSession(session_type="sub", agent_type="test")
        events = []

        class InterruptedGraph:
            async def astream_events(self, *args, **kwargs):
                yield {"event": "on_chat_model_end", "data": {"output": request("unfinished", 1)}}
                yield {"event": "on_tool_start", "name": "query", "run_id": "node", "data": {"input": {"limit": 1}}}
                if ending == "error":
                    raise RuntimeError("transport closed")
                yield {"event": "on_chain_start", "data": {}}

        async def no_op(*args, **kwargs):
            return None

        async def capture(event):
            events.append(event)
            if ending == "cancel" and event["type"] == "tool_start":
                session._abort_requested = True

        session.compiled_graph = InterruptedGraph()
        session.async_save = no_op
        session._check_and_compress_messages = no_op
        if ending == "error":
            with pytest.raises(RuntimeError, match="transport closed"):
                await session.send_message("query", capture)
        else:
            await session.send_message("query", capture)
        return session, events

    session, events = asyncio.run(scenario())
    ends = [event for event in events if event["type"] == "tool_end"]
    assert len(ends) == 1
    assert ends[0]["run_id"] == "unfinished"
    assert ends[0]["status"] == ("cancelled" if ending == "cancel" else "failed")
    assert len([entry for entry in session.record if entry["type"] == "tool"]) == 1
