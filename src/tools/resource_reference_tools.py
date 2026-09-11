"""Read-only access to the resource types without an existing reader."""

from __future__ import annotations

import json
from dataclasses import asdict

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from src.agent.definition import get_agent_definition
from src.core.utils import is_visible_to_frontend
from src.session.context import get_session_context


class AgentDefinitionInput(BaseModel):
    agent_type: str = Field(min_length=1, max_length=1024, description="Agent 的唯一类型 ID")


class SessionMessagesInput(BaseModel):
    session_id: str = Field(min_length=1, max_length=1024, description="目标会话完整 ID")
    offset: int = Field(default=0, ge=0, description="从第几条可见消息开始")
    limit: int = Field(default=20, ge=1, le=100, description="本次读取的消息条数")
    content_offset: int = Field(default=0, ge=0, description="首条消息正文的字符偏移，用于继续读取长消息")


def read_session_messages(session_manager, session_id: str, offset: int = 0,
                          limit: int = 20, content_offset: int = 0) -> dict:
    """Read live/cold history without creating a graph, invoking or exporting."""
    context = get_session_context()
    caller = session_manager.get_session(context.get("session_id", ""))
    if caller is None or caller.session_type != "main":
        return {"error": "只有主会话可以读取其他会话的历史"}
    target = session_manager.get_session(session_id)
    if target is None:
        return {"error": f"未找到会话 {session_id}"}
    visible = [
        message for message in target.record
        if isinstance(message, dict) and is_visible_to_frontend(message)
    ]
    messages = []
    budget = 24000
    next_offset = offset
    next_content_offset = 0
    for index in range(offset, min(len(visible), offset + limit)):
        message = visible[index]
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        start = content_offset if index == offset else 0
        fragment = content[start:start + budget]
        # Deliberate allowlist: do not expose hidden model_context or runtime state.
        result = {
            key: message[key]
            for key in ("id", "type", "role", "name", "timestamp", "tool_call_id")
            if key in message
        }
        result.update(content=fragment, content_offset=start)
        messages.append(result)
        budget -= len(fragment)
        if start + len(fragment) < len(content):
            next_offset = index
            next_content_offset = start + len(fragment)
            break
        next_offset = index + 1
        if budget <= 0:
            break
    return {
        "session_id": session_id,
        "messages": messages,
        "total": len(visible),
        "has_more": next_offset < len(visible),
        "next_offset": next_offset,
        "next_content_offset": next_content_offset,
    }


def create_resource_reference_tools(session_manager) -> list[StructuredTool]:
    def read_agent(agent_type: str) -> str:
        definition = get_agent_definition(agent_type)
        result = asdict(definition) if definition else {"error": f"未找到 Agent {agent_type}"}
        return json.dumps(result, ensure_ascii=False)

    def read_messages(session_id: str, offset: int = 0, limit: int = 20,
                      content_offset: int = 0) -> str:
        return json.dumps(
            read_session_messages(session_manager, session_id, offset, limit, content_offset),
            ensure_ascii=False,
        )

    async def read_messages_async(session_id: str, offset: int = 0, limit: int = 20,
                                  content_offset: int = 0) -> str:
        # SessionManager owns mutable runtime/catalog state on the event loop.
        return read_messages(session_id, offset, limit, content_offset)

    return [
        StructuredTool(
            name="get_agent_definition",
            description="按 agent_type 读取当前 Agent 定义与工具配置，不创建或切换 Agent。",
            args_schema=AgentDefinitionInput,
            func=read_agent,
        ),
        StructuredTool(
            name="get_session_messages",
            description=(
                "按完整 session_id 分页读取会话可见历史，不续聊或执行。仅主会话可用。"
                "has_more 为 true 时使用 next_offset 和 next_content_offset 继续读取。"
            ),
            args_schema=SessionMessagesInput,
            func=read_messages,
            coroutine=read_messages_async,
        ),
    ]
