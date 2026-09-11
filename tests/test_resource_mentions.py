import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent.definition import ALL_AGENT_DISALLOWED_TOOLS, AgentDefinition
from src.agent.session import AgentSession
from src.core.message_attachments import (
    retain_message_attachments,
    validate_message_attachments,
)
from src.resources import mentions
from src.session.context import get_session_context, set_session_context
from src.tools.prompt_tools import create_prompt_tools
from src.tools.resource_reference_tools import create_resource_reference_tools
from src.web.mention_routes import router


def _reference(kind="skill", resource_id="review"):
    return {
        "name": "代码审查",
        "resource_type": kind,
        "resource_id": resource_id,
        "reference_text": f'Skill「代码审查」（get_skills(skill_id="{resource_id}")）',
    }


@pytest.fixture
def resources(monkeypatch):
    tools = [SimpleNamespace(name=name) for name in mentions.READ_TOOLS.values()]
    current = SimpleNamespace(
        session_id="current", session_type="main", agent_type="main",
        tools=tools, compiled_graph=object(), workspace_path=None,
    )
    target = SimpleNamespace(
        session_id="other", session_type="main",
        record=[{"type": "user", "content": "历史内容"}],
    )
    session_map = {"current": current, "other": target}
    sessions = SimpleNamespace(
        get_session=lambda identity: session_map.get(identity),
        get_session_summaries=lambda: [
            {"session_id": "current", "task": "当前会话"},
            {"session_id": "other", "task": "架构讨论", "agent_type": "main"},
        ],
    )
    skills = [
        SimpleNamespace(id="core.review", name="代码审查", description="审查修改",
                        metadata={"resource_owner": "core"}),
        SimpleNamespace(id="plugin.review", name="代码审查", description="审查插件",
                        metadata={"resource_owner": "plugin"}),
    ]
    rules = [SimpleNamespace(id="format", name="编码规范", description="", metadata={})]
    config = {"agents": {
        "main": {"sections": [{"name": "intro", "content": "main intro"}]},
        "subagent": {"sections": [{"name": "intro", "content": "subagent intro"}]},
        "compressor": {"sections": [{"name": "compressor_identity", "content": "compressor intro"}]},
    }}
    prompts = SimpleNamespace(
        get_config=lambda: config,
        list_agent_types=lambda: sorted(config["agents"]),
        get_sections=lambda template: config["agents"][template]["sections"],
        get_preambles=lambda template: {"prefix": template},
    )
    app = FastAPI()
    app.state.session_manager = sessions
    app.state.skill_manager = SimpleNamespace(list_all=lambda: skills)
    app.state.rule_manager = SimpleNamespace(list_all=lambda: rules)
    app.state.prompt_manager = prompts
    app.state.workflow_manager = SimpleNamespace(list_workflows=lambda **_: [
        {"workflow_id": "flow-1", "name": "发布检查"},
    ])
    app.include_router(router)
    monkeypatch.setattr(mentions, "list_agent_types", lambda: [
        {"agent_type": "reviewer", "description": "代码审查助手"},
    ])
    old_context = get_session_context()
    set_session_context(session_id="current")
    yield SimpleNamespace(
        client=TestClient(app), app=app, current=current, target=target,
        sessions=sessions, skills=skills, prompts=prompts, config=config,
    )
    set_session_context(**old_context)


@pytest.mark.parametrize("kind", ["prompt", "agent", "skill", "rule", "workflow", "session"])
def test_each_resource_type_has_a_readable_reference(resources, kind):
    result = resources.client.get(
        "/api/sessions/current/mention-resources", params={"resource_type": kind},
    )
    assert result.status_code == 200
    page = result.json()
    assert page["items"]
    for item in page["items"]:
        assert item["resource_type"] == kind
        assert mentions.READ_TOOLS[kind] in item["reference_text"]
        assert item["available"]
        assert "content" not in item
        assert "absolute_path" not in item
        attachment = {key: item[key] for key in (
            "name", "resource_type", "resource_id", "reference_text",
        )}
        assert validate_message_attachments([attachment], item["reference_text"]) == [attachment]


def test_catalog_search_pagination_and_duplicate_names(resources):
    url = "/api/sessions/current/mention-resources"
    first = resources.client.get(url, params={"resource_type": "skill", "limit": 1}).json()
    second = resources.client.get(url, params={
        "resource_type": "skill", "limit": 1, "offset": 1,
    }).json()
    assert first["total"] == 2 and first["has_more"]
    assert second["total"] == 2 and not second["has_more"]
    assert first["items"][0]["name"] == second["items"][0]["name"]
    assert first["items"][0]["resource_id"] != second["items"][0]["resource_id"]
    assert first["items"][0]["reference_text"] != second["items"][0]["reference_text"]
    filtered = resources.client.get(url, params={
        "resource_type": "skill", "q": "PLUGIN 审查",
    }).json()
    assert [item["resource_id"] for item in filtered["items"]] == ["plugin.review"]
    assert resources.client.get(url, params={
        "resource_type": "skill", "q": "no-match",
    }).json() == {"items": [], "total": 0, "has_more": False}


def test_prompt_catalog_lists_only_whole_templates(resources):
    page = resources.client.get(
        "/api/sessions/current/mention-resources",
        params={"resource_type": "prompt"},
    ).json()
    assert page["total"] == 3
    assert [item["name"] for item in page["items"]] == ["compressor", "main", "subagent"]
    for item in page["items"]:
        assert item["resource_id"] == item["name"]
        assert item["reference_text"] == (
            f'Prompt「{item["name"]}」（get_system_prompt(agent_type="{item["name"]}")）'
        )


def test_prompt_search_matches_templates_without_exposing_sections(resources):
    url = "/api/sessions/current/mention-resources"
    page = resources.client.get(url, params={"resource_type": "prompt", "q": "compressor"}).json()
    assert [item["name"] for item in page["items"]] == ["compressor"]
    assert resources.client.get(url, params={
        "resource_type": "prompt", "q": "intro",
    }).json() == {"items": [], "total": 0, "has_more": False}


def test_prompt_catalog_tracks_added_and_removed_templates(resources):
    url = "/api/sessions/current/mention-resources"
    resources.config["agents"]["plugin.writer"] = {"sections": [{"name": "intro"}]}
    page = resources.client.get(url, params={"resource_type": "prompt", "q": "plugin"}).json()
    assert [item["resource_id"] for item in page["items"]] == ["plugin.writer"]
    del resources.config["agents"]["plugin.writer"]
    assert resources.client.get(url, params={
        "resource_type": "prompt", "q": "plugin",
    }).json() == {"items": [], "total": 0, "has_more": False}


def test_catalog_is_live_and_never_loads_other_sessions(resources):
    resources.sessions.get_session = Mock(side_effect=resources.sessions.get_session)
    url = "/api/sessions/current/mention-resources"
    page = resources.client.get(url, params={"resource_type": "session"}).json()
    assert [item["resource_id"] for item in page["items"]] == ["other"]
    resources.sessions.get_session.assert_called_once_with("current")
    resources.skills.pop()
    page = resources.client.get(url, params={"resource_type": "skill"}).json()
    assert page["total"] == 1


def test_missing_tool_disables_insertion_without_granting_access(resources):
    resources.current.tools = []
    result = resources.client.get(
        "/api/sessions/current/mention-resources", params={"resource_type": "skill"},
    ).json()
    assert all(not item["available"] and item["unavailable_reason"] for item in result["items"])
    assert resources.current.tools == []


def test_cold_session_uses_assembler_without_starting_a_graph(resources):
    resources.current.tools = []
    resources.current.compiled_graph = None
    assembler = Mock()
    assembler.build.return_value = [SimpleNamespace(name="get_skills")]
    resources.sessions._tool_assembler = assembler
    result = resources.client.get(
        "/api/sessions/current/mention-resources", params={"resource_type": "skill"},
    ).json()
    assert all(item["available"] for item in result["items"])
    assembler.build.assert_called_once()
    assert resources.current.tools == [] and resources.current.compiled_graph is None


def test_catalog_rejects_bad_type_page_and_unknown_session(resources):
    url = "/api/sessions/current/mention-resources"
    for params in (
        {"resource_type": "secret"}, {"resource_type": "skill", "limit": 101},
        {"resource_type": "skill", "offset": -1},
    ):
        assert resources.client.get(url, params=params).status_code == 422
    assert resources.client.get(
        "/api/sessions/missing/mention-resources", params={"resource_type": "skill"},
    ).status_code == 404


def test_mixed_attachments_validate_and_survive_editing():
    resource = _reference()
    file = {"name": "report.md", "absolute_path": "/tmp/report.md"}
    content = f'用 {resource["reference_text"]} 检查 /tmp/report.md'
    assert validate_message_attachments([resource, file], content) == [resource, file]
    assert retain_message_attachments([resource, file], "检查 /tmp/report.md") == [file]
    assert retain_message_attachments([resource, file], resource["reference_text"]) == [resource]


@pytest.mark.parametrize("update", [
    {"resource_type": "unknown"}, {"resource_type": []}, {"resource_id": ""},
    {"reference_text": ""}, {"reference_text": "不在正文"}, {"name": ""},
    {"absolute_path": "/tmp/a"}, {"resource_id": "a" * 1025},
])
def test_reject_invalid_resource_attachment_metadata(update):
    resource = _reference()
    with pytest.raises(ValueError):
        validate_message_attachments([{**resource, **update}], resource["reference_text"])


def test_reference_count_limit_and_legacy_restore():
    resource = _reference()
    with pytest.raises(ValueError):
        validate_message_attachments([resource] * 65, resource["reference_text"])
    legacy = {"name": "a.txt", "absolute_path": "/tmp/a.txt"}
    assert retain_message_attachments([legacy, resource, {}]) == [legacy, resource]


def test_prompt_reader_selects_live_section_and_keeps_whole_prompt_compatible(resources):
    tool = {tool.name: tool for tool in create_prompt_tools(resources.prompts)}["get_system_prompt"]
    whole = json.loads(tool.invoke({"agent_type": "main"}))
    assert whole["data"]["preambles"] == {"prefix": "main"}
    resources.config["agents"]["main"]["sections"][0]["content"] = "updated"
    section = json.loads(tool.invoke({"agent_type": "main", "section_name": "intro"}))
    assert section["data"]["sections"] == [{"name": "intro", "content": "updated"}]
    assert section["data"]["preambles"] == {}
    missing = json.loads(tool.invoke({"agent_type": "main", "section_name": "missing"}))
    assert "error" in missing


def test_agent_reader_uses_effective_definition(monkeypatch, resources):
    from src.tools import resource_reference_tools
    monkeypatch.setattr(resource_reference_tools, "get_agent_definition", lambda identity:
                        AgentDefinition(identity, "plugin definition") if identity == "plugin.writer" else None)
    tools = {tool.name: tool for tool in create_resource_reference_tools(resources.sessions)}
    result = json.loads(tools["get_agent_definition"].invoke({"agent_type": "plugin.writer"}))
    assert result["agent_type"] == "plugin.writer"
    assert result["description"] == "plugin definition"
    assert "error" in json.loads(tools["get_agent_definition"].invoke({"agent_type": "missing"}))


def test_session_reader_paginates_long_content_without_exposing_hidden_context(resources):
    body = "长" * 30000
    resources.target.record = [
        {"type": "system_prompt", "content": "hidden system"},
        {"type": "user", "content": body, "model_context": {"secret": "hidden"}},
        {"type": "assistant", "content": "结论"},
    ]
    tool = {tool.name: tool for tool in create_resource_reference_tools(resources.sessions)}["get_session_messages"]
    first = json.loads(tool.invoke({"session_id": "other"}))
    assert first["total"] == 2 and first["has_more"]
    assert first["next_offset"] == 0 and first["next_content_offset"] == 24000
    assert "model_context" not in first["messages"][0]
    second = json.loads(tool.invoke({
        "session_id": "other", "offset": first["next_offset"],
        "content_offset": first["next_content_offset"],
    }))
    assert first["messages"][0]["content"] + second["messages"][0]["content"] == body
    assert second["messages"][1]["content"] == "结论"
    assert not second["has_more"]
    resources.target.record.append({"type": "user", "content": "新消息"})
    assert json.loads(tool.invoke({"session_id": "other", "offset": 2}))["total"] == 3


def test_session_reader_preserves_sub_agent_boundary(resources):
    tool = {tool.name: tool for tool in create_resource_reference_tools(resources.sessions)}["get_session_messages"]
    resources.current.session_type = "sub"
    assert "error" in json.loads(tool.invoke({"session_id": "other"}))
    assert "get_session_messages" in ALL_AGENT_DISALLOWED_TOOLS
    page = resources.client.get(
        "/api/sessions/current/mention-resources", params={"resource_type": "session"},
    ).json()
    assert not page["items"][0]["available"]
    set_session_context()
    assert "error" in json.loads(tool.invoke({"session_id": "other"}))


def test_async_session_reader_keeps_catalog_access_on_the_event_loop(resources):
    async def scenario():
        loop = asyncio.get_running_loop()
        get_session = resources.sessions.get_session

        def on_loop(identity):
            assert asyncio.get_running_loop() is loop
            return get_session(identity)

        resources.sessions.get_session = on_loop
        tool = {tool.name: tool for tool in create_resource_reference_tools(resources.sessions)}["get_session_messages"]
        return json.loads(await tool.ainvoke({"session_id": "other"}))

    assert asyncio.run(scenario())["messages"][0]["content"] == "历史内容"


def test_reference_readers_are_registered_and_sub_agent_filter_is_preserved(resources):
    from src.agent.definition import resolve_agent_tools
    from src.tools.registry import ToolRegistry, register_all_tool_factories

    registry = ToolRegistry("config/tool_groups_config.json")
    register_all_tool_factories(
        registry, mcp_client=SimpleNamespace(get_tools=lambda: []),
        session_manager=resources.sessions, prompt_manager=resources.prompts,
    )
    tools = [
        registry.instantiate(name)
        for name in ("get_system_prompt", "get_agent_definition", "get_session_messages")
    ]
    assert [tool.name for tool in tools] == [
        "get_system_prompt", "get_agent_definition", "get_session_messages",
    ]
    assert registry.get_tool_group_id("get_agent_definition") == "config"
    assert registry.get_tool_group_id("get_session_messages") == "session_main"
    definition = AgentDefinition(agent_type="sub", description="", tools=["*"])
    resolved = resolve_agent_tools(definition, tools, [])
    assert {tool.name for tool in resolved} == {"get_system_prompt", "get_agent_definition"}


def test_workflow_catalog_skips_task_history_without_changing_default_status(tmp_path, monkeypatch):
    from src.workflow import manager

    monkeypatch.setattr(manager, "WORKFLOWS_DIR", tmp_path)
    workflow = tmp_path / "flow"
    workflow.mkdir()
    (workflow / "definition.json").write_text('{"workflow_id":"flow","name":"Flow"}')
    (workflow / "tasks").mkdir()
    (workflow / "tasks" / "task.json").write_text("{}")
    fake = SimpleNamespace(
        is_workflow_owner_enabled=lambda _: True,
        _load_task=Mock(return_value=SimpleNamespace(status="running")),
    )
    lightweight = manager.WorkflowManager.list_workflows(fake, include_task_status=False)
    assert lightweight[0]["workflow_id"] == "flow" and "status" not in lightweight[0]
    fake._load_task.assert_not_called()
    full = manager.WorkflowManager.list_workflows(fake)
    assert full[0]["status"] == "running" and full[0]["running_tasks"] == 1
    fake._load_task.assert_called_once_with("flow", "task")


class _EmptyGraph:
    async def astream_events(self, *_args, **_kwargs):
        for event in []:
            yield event


def test_reference_metadata_survives_send_edit_and_failed_turn_restore(monkeypatch):
    import src.config as config

    monkeypatch.setattr(config, "USER_MESSAGE_INJECTION_ENABLED", False)
    resource = _reference()
    content = f'用 {resource["reference_text"]} 检查代码'

    async def scenario():
        session = AgentSession(session_type="sub", agent_type="test")
        session.compiled_graph = _EmptyGraph()

        async def no_op(*_args, **_kwargs):
            return None

        session.async_save = no_op
        session._check_and_compress_messages = no_op
        await session.send_message(content, max_rounds=1, attachments=[resource])
        assert session.record[0]["attachments"] == [resource]
        assert session.lc_messages[0].content == content
        assert "attachments" not in session.lc_messages[0].additional_kwargs
        session.failed_turn = {
            "failure_id": "failure", "content": content, "attachments": [resource],
            "retryable": True, "tool_started": False, "attempt_count": 1,
        }
        restored = AgentSession.from_dict(session.to_dict())
        assert restored.failed_turn["attachments"] == [resource]
        session.failed_turn = None
        await session.edit_message_and_resend(
            session.record[0]["id"], content + "，关注性能",
        )
        assert session.record[0]["attachments"] == [resource]
        await session.edit_message_and_resend(session.record[0]["id"], "不再引用资源")
        assert session.record[0].get("attachments", []) == []

    asyncio.run(scenario())
