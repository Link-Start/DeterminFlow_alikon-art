import asyncio
import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphBubbleUp, NodeCancelledError
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError
from pydantic import BaseModel, Field, StrictInt, ValidationError

from src.agent.session import AgentSession
from src.core.graph_builder import build_graph
from src.core.state import AgentState
from src.core.tool_errors import (
    handle_tool_validation_error,
    validation_error_content,
)
from src.core.tool_guard import RoundsGuard, make_guarded_wrapper

GATEWAY_ERROR = "Portal Gateway 拒绝工具调用: HTTP 429"
SECRET = "sk-live-secret-value"


class QueryInput(BaseModel):
    limit: StrictInt = Field(default=10, ge=1, le=20)


class ScriptedModel(BaseChatModel):
    responses: list[AIMessage]
    position: int = 0
    offered_tools: list[bool] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return "scripted-tool-node-guard-test"

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools_offered=True)

    def _next(self, kwargs):
        self.offered_tools.append(kwargs.get("tools_offered", False))
        response = self.responses[self.position]
        self.position += 1
        return response

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._next(kwargs))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
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


def production_tool_node(tools):
    return ToolNode(
        tools,
        awrap_tool_call=make_guarded_wrapper([RoundsGuard()]),
        handle_tool_errors=handle_tool_validation_error,
    )


def tool_state(tool_calls, remaining=5):
    return {
        "messages": [AIMessage(content="", tool_calls=tool_calls)],
        "remaining_rounds": remaining,
        "session_id": "tool-node-guard",
        "agent_type": "test",
        "status": "running",
        "metadata": {"max_rounds": remaining},
    }


def query_tool(coroutine):
    return StructuredTool.from_function(
        coroutine=coroutine, name="query", description="Query items",
        args_schema=QueryInput,
    )


def invoke_tool_node(node, tool_calls, remaining=5):
    graph = StateGraph(AgentState)
    graph.add_node("tools", node)
    graph.set_entry_point("tools")
    graph.add_edge("tools", END)
    compiled = graph.compile()

    async def run():
        return await compiled.ainvoke(tool_state(tool_calls, remaining=remaining))

    return asyncio.run(run())


def run_session(responses, coroutine, rounds=6):
    tool = query_tool(coroutine)
    model = ScriptedModel(responses=responses)
    events = []
    session = AgentSession(session_type="sub", agent_type="test")

    async def scenario():
        session.tools = [tool]
        session.compiled_graph = build_graph(model, [tool]).compile()

        async def no_op(*args, **kwargs):
            return None

        async def callback(event):
            events.append(event)

        session.async_save = no_op
        session._check_and_compress_messages = no_op
        await session.send_message("最近作品该先推进哪一本", callback, max_rounds=rounds)
        return session

    return asyncio.run(scenario()), events, model


def test_handler_rethrows_runtime_and_control_errors():
    runtime = RuntimeError(f"{GATEWAY_ERROR} token={SECRET}")
    with pytest.raises(RuntimeError) as runtime_exc:
        handle_tool_validation_error(runtime)
    assert runtime_exc.value is runtime

    cancelled = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError) as cancelled_exc:
        handle_tool_validation_error(cancelled)
    assert cancelled_exc.value is cancelled

    interrupt = GraphBubbleUp()
    with pytest.raises(GraphBubbleUp) as interrupt_exc:
        handle_tool_validation_error(interrupt)
    assert interrupt_exc.value is interrupt


def test_handler_returns_validation_fields_without_input():
    with pytest.raises(ValidationError) as exc:
        QueryInput(limit=SECRET)
    content = handle_tool_validation_error(
        ToolInvocationError("query", exc.value, {"limit": SECRET}),
    )
    error = json.loads(content)["error"]
    assert error["code"] == "tool_arguments_invalid"
    assert error["fields"] == [{"field": "limit", "rule": "int_type"}]
    assert SECRET not in content


def test_validation_content_rejects_runtime_errors_without_attribute_error():
    with pytest.raises(TypeError, match="validation feedback"):
        validation_error_content(RuntimeError(GATEWAY_ERROR))


def test_tool_node_runtime_error_is_not_masked_by_validation_handler():
    invoked = []

    async def query(limit=10):
        invoked.append(limit)
        raise RuntimeError(f"{GATEWAY_ERROR} token={SECRET}")

    node = production_tool_node([query_tool(query)])
    with pytest.raises(RuntimeError, match="HTTP 429") as exc:
        invoke_tool_node(node, request("runtime", 10).tool_calls)
    assert invoked == [10]
    assert SECRET in str(exc.value)
    assert "AttributeError" not in type(exc.value).__name__
    assert not isinstance(exc.value.__cause__, AttributeError)
    assert not isinstance(exc.value.__context__, AttributeError)


def test_tool_node_validation_error_returns_field_feedback():
    invoked = []

    async def query(limit=10):
        invoked.append(limit)
        return '{"ok":true}'

    node = production_tool_node([query_tool(query)])
    result = invoke_tool_node(node, request("invalid", SECRET).tool_calls)
    messages = [item for item in result["messages"] if isinstance(item, ToolMessage)]
    assert len(messages) == 1
    message = messages[0]
    assert message.status == "error"
    error = json.loads(message.content)["error"]
    assert error["code"] == "tool_arguments_invalid"
    assert error["fields"] == [{"field": "limit", "rule": "int_type"}]
    assert SECRET not in message.content
    assert invoked == []


def test_tool_node_success_returns_completed_result():
    invoked = []

    async def query(limit=10):
        invoked.append(limit)
        return '{"ok":true,"count":3}'

    node = production_tool_node([query_tool(query)])
    result = invoke_tool_node(node, request("ok", 10).tool_calls)
    messages = [item for item in result["messages"] if isinstance(item, ToolMessage)]
    assert len(messages) == 1
    message = messages[0]
    assert message.status != "error"
    assert message.content == '{"ok":true,"count":3}'
    assert invoked == [10]


def test_tool_node_does_not_swallow_cancellation():
    async def query(limit=10):
        raise asyncio.CancelledError()

    node = production_tool_node([query_tool(query)])
    with pytest.raises((asyncio.CancelledError, NodeCancelledError)):
        invoke_tool_node(node, request("cancel", 10).tool_calls)


def test_session_runtime_error_safe_fails_without_validation_misclassification():
    async def query(limit=10):
        raise RuntimeError(f"{GATEWAY_ERROR} token={SECRET}")

    events = []
    session = AgentSession(session_type="sub", agent_type="test")
    model = ScriptedModel(responses=[
        request("runtime", 10), AIMessage(content="must not continue"),
    ])

    async def scenario():
        tool = query_tool(query)
        session.tools = [tool]
        session.compiled_graph = build_graph(model, [tool]).compile()

        async def no_op(*args, **kwargs):
            return None

        async def callback(event):
            events.append(event)

        session.async_save = no_op
        session._check_and_compress_messages = no_op
        await session.send_message("最近作品该先推进哪一本", callback, max_rounds=6)

    with pytest.raises(RuntimeError, match="HTTP 429") as exc:
        asyncio.run(scenario())
    assert SECRET in str(exc.value)
    assert model.position == 1
    assert session.last_error is not None
    assert session.last_error["code"] == "session_failed"
    assert SECRET not in session.last_error["message"]
    assert "HTTP 429" not in session.last_error["message"]
    assert "tool_arguments_invalid" not in session.last_error["message"]
    ends = [event for event in events if event["type"] == "tool_end"]
    assert ends
    assert all(event["status"] == "failed" for event in ends)
    assert all(
        "tool_arguments_invalid" not in str(event.get("result", ""))
        for event in ends
    )


def test_session_validation_then_corrected_tool_continues_with_status():
    invoked = []

    async def query(limit=10):
        invoked.append(limit)
        return '{"ok":true,"count":3}'

    session, events, model = run_session([
        request("invalid", SECRET), request("corrected", 10),
        AIMessage(content="查询完成，共 3 部作品。"),
    ], query)
    assert invoked == [10]
    assert model.position == 3
    ends = [event for event in events if event["type"] == "tool_end"]
    assert [(event["run_id"], event["status"]) for event in ends] == [
        ("invalid", "failed"), ("corrected", "completed"),
    ]
    error = json.loads(ends[0]["result"])["error"]
    assert error["code"] == "tool_arguments_invalid"
    assert SECRET not in ends[0]["result"]
    assert json.loads(ends[1]["result"]) == {"ok": True, "count": 3}
    assert session.get_last_assistant_message() == "查询完成，共 3 部作品。"


def test_raw_validation_error_is_not_invocation_feedback():
    with pytest.raises(ValidationError) as exc:
        QueryInput(limit=SECRET)
    with pytest.raises(ValidationError) as propagated:
        handle_tool_validation_error(exc.value)
    assert propagated.value is exc.value
