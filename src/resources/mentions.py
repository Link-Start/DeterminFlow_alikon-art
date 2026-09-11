"""Lightweight, live resource references for the conversation composer."""

from __future__ import annotations

import json
from urllib.parse import quote

from src.agent.definition import get_agent_definition, list_agent_types
from src.workspace.tools import filter_workspace_tools

READ_TOOLS = {
    "prompt": "get_system_prompt",
    "agent": "get_agent_definition",
    "skill": "get_skills",
    "rule": "get_rules",
    "workflow": "get_workflow",
    "session": "get_session_messages",
}
LABELS = {
    "prompt": "Prompt", "agent": "Agent", "skill": "Skill",
    "rule": "Rule", "workflow": "Workflow", "session": "会话",
}


def session_tool_names(session, session_manager) -> set[str]:
    """Use current tools, or the normal assembler for a cold conversation.

    This only constructs tool definitions; it never initializes an LLM graph or
    changes the session's tools. An intentionally empty active tool set stays empty.
    """
    tools = getattr(session, "tools", [])
    if tools or getattr(session, "compiled_graph", None) is not None:
        return {tool.name for tool in tools}
    assembler = getattr(session_manager, "_tool_assembler", None)
    if assembler is None:
        return set()
    tools = assembler.build(
        session.agent_type,
        agent_definition=get_agent_definition(session.agent_type),
        workspace_path=getattr(session, "workspace_path", "") or "",
        is_workflow_node=bool(getattr(session, "workflow_id", None)),
    )
    return {tool.name for tool in filter_workspace_tools(tools, session.agent_type)}


def _item(kind: str, resource_id: str, name: str, *, arguments: dict[str, str],
          source: str = "", description: str = "") -> dict:
    name = str(name or resource_id)[:255]
    args = ", ".join(
        f"{key}={json.dumps(value, ensure_ascii=False)}"
        for key, value in arguments.items()
    )
    return {
        "resource_type": kind,
        "resource_id": resource_id,
        "name": name,
        "source": str(source or ""),
        "description": str(description or "")[:240],
        "reference_text": f"{LABELS[kind]}「{name}」（{READ_TOOLS[kind]}({args})）",
        "available": True,
    }


def list_mention_resources(kind: str, state, session, *, query: str = "",
                           offset: int = 0, limit: int = 50) -> dict:
    """Use the same resolved managers as resource editors and runtime readers."""
    items = []
    if kind in {"skill", "rule"}:
        manager = getattr(state, f"{kind}_manager", None)
        resources = manager.list_all() if manager is not None else []
        for resource in resources:
            items.append(_item(
                kind, resource.id, resource.name,
                arguments={f"{kind}_id": resource.id},
                description=resource.description,
                source=str(resource.metadata.get("resource_owner", "")),
            ))
    elif kind == "prompt":
        manager = getattr(state, "prompt_manager", None)
        # Match the orchestration editor's template catalog, not its internal sections.
        templates = manager.list_agent_types() if manager is not None else []
        for template in templates:
            items.append(_item(
                kind, quote(template, safe=""), template,
                arguments={"agent_type": template}, source="完整提示词",
            ))
    elif kind == "agent":
        for agent in list_agent_types():
            agent_type = agent["agent_type"]
            items.append(_item(
                kind, agent_type, agent_type, arguments={"agent_type": agent_type},
                description=agent.get("description", ""),
            ))
    elif kind == "workflow":
        manager = getattr(state, "workflow_manager", None)
        for workflow in manager.list_workflows(include_task_status=False) if manager is not None else []:
            resource_id = workflow["workflow_id"]
            items.append(_item(
                kind, resource_id, workflow.get("name") or resource_id,
                arguments={"workflow_id": resource_id},
            ))
    elif kind == "session":
        for summary in state.session_manager.get_session_summaries():
            resource_id = summary["session_id"]
            if resource_id == session.session_id:
                continue
            items.append(_item(
                kind, resource_id, summary.get("task") or resource_id,
                arguments={"session_id": resource_id},
                source=summary.get("agent_type", ""),
                description=summary.get("updated_at", ""),
            ))

    terms = query.casefold().split()
    items = [
        item for item in items
        if len(item["resource_id"]) <= 1024 and len(item["reference_text"]) <= 4096
        and all(term in " ".join(
            str(item[key]) for key in ("name", "resource_id", "source", "description")
        ).casefold() for term in terms)
    ]
    # Session manager already orders by recency. Other types use stable name/ID order.
    if kind != "session":
        items.sort(key=lambda item: (item["name"].casefold(), item["resource_id"]))
    total = len(items)
    page = items[offset:offset + limit]
    tool_names = session_tool_names(session, state.session_manager)
    available = READ_TOOLS[kind] in tool_names
    if kind == "session" and session.session_type != "main":
        available = False
    if not available:
        for item in page:
            item.update(available=False, unavailable_reason="当前会话未开放此资源的读取工具")
    return {"items": page, "total": total, "has_more": offset + len(page) < total}
