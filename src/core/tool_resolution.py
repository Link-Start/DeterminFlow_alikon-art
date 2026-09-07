"""Generic durable suspension markers for externally resolved tools."""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import ToolMessage

_RESOLUTION_KEY = "determinflow_tool_resolution"
_PENDING = "pending"


def pending_tool_resolution(
    *,
    tool_call_id: str,
    name: str,
    metadata: dict[str, Any],
) -> ToolMessage:
    """Return an internal ToolMessage marker that must never reach the model."""
    return ToolMessage(
        content="",
        tool_call_id=tool_call_id,
        name=name,
        additional_kwargs={
            _RESOLUTION_KEY: {
                "status": _PENDING,
                "metadata": dict(metadata),
            }
        },
    )


def pending_tool_resolution_metadata(message: object) -> dict[str, Any] | None:
    if not isinstance(message, ToolMessage):
        return None
    resolution = message.additional_kwargs.get(_RESOLUTION_KEY)
    if not isinstance(resolution, dict) or resolution.get("status") != _PENDING:
        return None
    metadata = resolution.get("metadata")
    return dict(metadata) if isinstance(metadata, dict) else {}


def route_after_tools(state: dict[str, Any]) -> Literal["llm", "__end__"]:
    messages = state.get("messages") or []
    if any(pending_tool_resolution_metadata(message) is not None for message in messages):
        return "__end__"
    return "llm"
