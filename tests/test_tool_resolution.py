from __future__ import annotations

from langchain_core.messages import ToolMessage

from src.core.tool_resolution import (
    pending_tool_resolution,
    pending_tool_resolution_metadata,
    route_after_tools,
)


def test_pending_tool_resolution_routes_graph_to_end_without_exposing_content():
    message = pending_tool_resolution(
        tool_call_id="call-write-1",
        name="novelbuilt_chapters",
        metadata={"action_id": "action-1"},
    )

    assert isinstance(message, ToolMessage)
    assert message.content == ""
    assert pending_tool_resolution_metadata(message) == {
        "action_id": "action-1"
    }
    assert route_after_tools({"messages": [message]}) == "__end__"


def test_normal_tool_result_routes_back_to_llm():
    message = ToolMessage(
        content='{"ok":true}',
        tool_call_id="call-read-1",
        name="novelbuilt_books",
    )

    assert pending_tool_resolution_metadata(message) is None
    assert route_after_tools({"messages": [message]}) == "llm"
