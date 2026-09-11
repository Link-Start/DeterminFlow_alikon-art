from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.config_manager import AgentConfigManager
from src.agent.definition import set_agent_config_manager
from src.extension_api.models import ExtensionManifest
from src.extension_api.registrar import OwnedPath
from src.extension_host.resource_ids import ResourceIdResolver
from src.extension_host.resource_preparation import prepare_plugin_resources
from src.extension_host.resources import LayeredJsonConfig
from src.memory.contracts import (
    ExtractParseError,
    MemoryExtractRequest,
    MemoryUnavailableError,
)
from src.memory.extract import DefaultExtractRunner, parse_extract_facts
from src.memory.extract_output import JSON_OBJECT_RESPONSE_FORMAT
from src.memory.turns import bound_extract_turns
from src.prompts.manager import PromptManager
from src.session.prompt_builder import PromptBuilder
from tests.test_memory_runtime import FakeProvider, _runtime


def _turn(turn_id: str = "turn-1", message_id: str = "msg_00001") -> dict:
    return {
        "turn_id": turn_id,
        "started_at": "2026-09-08T00:00:00+00:00",
        "messages": [
            {"id": message_id, "type": "user", "source": "human", "content": "事实"},
            {"id": "msg_00002", "type": "assistant", "content": "好"},
        ],
    }


def test_parse_extract_facts_empty_object_is_success() -> None:
    assert parse_extract_facts({"facts": []}, turns=[_turn()]) == []


def test_parse_extract_facts_rejects_bad_json_and_unknown_sources() -> None:
    turns = [_turn()]
    with pytest.raises(ExtractParseError):
        parse_extract_facts("not-json", turns=turns)
    with pytest.raises(ExtractParseError):
        parse_extract_facts("{}", turns=turns)
    with pytest.raises(ExtractParseError):
        parse_extract_facts({"facts": [{"text": "x"}]}, turns=turns)
    with pytest.raises(ExtractParseError):
        parse_extract_facts(
            {
                "facts": [
                    {
                        "text": "x",
                        "source_message_ids": ["missing"],
                        "turn_id": "turn-1",
                    }
                ]
            },
            turns=turns,
        )
    with pytest.raises(ExtractParseError):
        parse_extract_facts(
            {
                "facts": [
                    {
                        "text": "x",
                        "source_message_ids": ["msg_00001"],
                        "turn_id": "other-turn",
                    }
                ]
            },
            turns=turns,
        )


def test_parse_extract_facts_uses_source_turn_timestamp_and_drops_preference() -> None:
    facts = parse_extract_facts(
        {
            "facts": [
                {
                    "text": "用户用模块化",
                    "source_message_ids": ["msg_00001"],
                    "source_timestamp": "1999-01-01T00:00:00+00:00",
                    "turn_id": "turn-1",
                    "kind": "fact",
                },
                {
                    "text": "喜欢短句",
                    "source_message_ids": ["msg_00001"],
                    "turn_id": "turn-1",
                    "kind": "preference",
                },
            ]
        },
        turns=[_turn()],
    )
    assert len(facts) == 1
    assert facts[0].source_timestamp == "2026-09-08T00:00:00+00:00"
    assert facts[0].source_message_ids == ("msg_00001",)


def test_bound_extract_turns_preserves_long_messages_and_tool_pairs() -> None:
    huge = "x" * 6000
    turns = bound_extract_turns(
        [
            {
                "turn_id": "t1",
                "messages": [
                    {"id": "u1", "type": "user", "content": "问"},
                    {
                        "id": "a1",
                        "type": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "call-1", "name": "lookup"}],
                    },
                    {
                        "id": "tool-1",
                        "type": "tool",
                        "tool_call_id": "call-1",
                        "content": huge,
                    },
                ],
            }
        ],
        max_turns=1,
    )
    messages = turns[0]["messages"]
    assert [item["type"] for item in messages] == ["user", "assistant", "tool"]
    assert messages[2]["id"] == "tool-1"
    assert messages[2]["tool_call_id"] == "call-1"
    assert messages[2]["content"] == huge
    with pytest.raises(ExtractParseError):
        bound_extract_turns(turns, max_turns=1, max_bytes=1000)


def test_default_extract_runner_requires_injected_builder() -> None:
    runner = DefaultExtractRunner()
    request = MemoryExtractRequest(
        session_id="s",
        bank_id="b",
        memory_scope="",
        extract_agent_type="memory-extract",
        turns=(_turn(),),
        timeout_seconds=1,
    )
    with pytest.raises(MemoryUnavailableError):
        asyncio.run(runner.extract(request))


def test_extract_agent_type_uses_agents_and_does_not_swallow(tmp_path) -> None:
    provider = FakeProvider()
    service = _runtime(tmp_path, provider)
    seen: list[str] = []

    def resolve(owner: str, resource_type: str, local_id: str) -> str:
        seen.append(resource_type)
        raise KeyError("missing mapping")

    service.attach(resolve_resource=resolve)
    with pytest.raises(KeyError):
        service._extract_agent_type("mem", provider)
    assert seen == ["agents"]


def test_extract_runner_uses_layered_plugin_prompt(tmp_path: Path) -> None:
    plugin_root = tmp_path / "demo-plugin"
    resources = plugin_root / "resources"
    resources.mkdir(parents=True)
    (resources / "agents.json").write_text(json.dumps({"agents": {
        "memory-extract": {"description": "extract facts", "prompt_template": "memory-extract",
            "tools": [], "max_turns": 1, "include_skills": False, "include_rules": False}
    }}))
    (resources / "prompts.json").write_text(json.dumps({"agents": {
        "memory-extract": {"description": "extract facts", "sections": [
            {"name": "contract", "enabled": True, "order": 0,
             "content": '没有可保留事实时返回 {"facts":[]}。'}
        ]}
    }}))
    manifest = ExtensionManifest(
        extension_id="demo-memory",
        name="Demo Memory",
        version="1.2.0",
        resource_prefix="demo",
        base_path=plugin_root,
    )
    resource_paths = {
        "agents": [
            OwnedPath(
                owner="demo-memory", path=plugin_root / "resources" / "agents.json"
            )
        ],
        "prompts": [
            OwnedPath(
                owner="demo-memory",
                path=plugin_root / "resources" / "prompts.json",
            )
        ],
    }
    resolver = ResourceIdResolver()
    prepared = prepare_plugin_resources(
        manifest,
        resource_paths,
        runtime_root=tmp_path / "runtime-resources",
        resolver=resolver,
    )
    agents_file = tmp_path / "agents_config.json"
    agents_file.write_text(json.dumps({"agents": {}}), encoding="utf-8")
    prompts_file = tmp_path / "prompts_config.json"
    prompts_file.write_text(
        json.dumps(
            {
                "agents": {
                    "main": {
                        "description": "main",
                        "sections": [
                            {
                                "name": "core",
                                "enabled": True,
                                "order": 0,
                                "content": "core-only",
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    agent_store = LayeredJsonConfig(
        agents_file,
        prepared.paths["agents"],
        dict_sections=("agents",),
    )
    prompt_store = LayeredJsonConfig(
        prompts_file,
        prepared.paths["prompts"],
        dict_sections=("agents",),
    )
    agent_mgr = AgentConfigManager(agents_file, config_store=agent_store)
    import src.agent.definition as definition_mod

    previous = definition_mod._agent_config_manager
    set_agent_config_manager(agent_mgr)
    capture = SimpleNamespace(messages=None)

    class _LLM:
        async def ainvoke(self, messages):
            capture.messages = messages
            return SimpleNamespace(content='{"facts":[]}')

    try:
        prompt_mgr = PromptManager(
            config_file=prompts_file,
            cache_file=tmp_path / "system_prompt.json",
            history_file=tmp_path / "prompt_history.json",
            config_store=prompt_store,
        )
        builder = PromptBuilder(prompt_mgr)
        effective_id = resolver.resolve("demo-memory", "agents", "memory-extract")
        assert effective_id == "demo-memory-extract"
        runner = DefaultExtractRunner(
            prompt_builder=builder,
            llm_factory=lambda model, params: _LLM(),
        )
        facts = asyncio.run(
            runner.extract(
                MemoryExtractRequest(
                    session_id="s",
                    bank_id="b",
                    memory_scope="",
                    extract_agent_type=effective_id,
                    turns=(_turn(),),
                    timeout_seconds=1,
                )
            )
        )
        assert facts == []
        system = capture.messages[0].content
        assert "没有可保留事实时返回" in system
        assert "core-only" not in system
        user_payload = json.loads(capture.messages[1].content)
        assert user_payload["turns"][0]["messages"][0]["id"] == "msg_00001"
    finally:
        definition_mod._agent_config_manager = previous


def test_parse_extract_facts_accepts_wrapped_empty_facts() -> None:
    turns = [_turn()]
    wrapped = (
        "<think>consider braces { and } in notes</think>\n"
        "说明：没有可保留事实。\n"
        '```json\n{"facts": []}\n```\n'
    )
    assert parse_extract_facts(wrapped, turns=turns) == []


def test_parse_extract_facts_rejects_multiple_objects_instead_of_guessing() -> None:
    raw = 'analysis { "debug": true }\n{"facts":[]}'
    with pytest.raises(ExtractParseError, match="ambiguous"):
        parse_extract_facts(raw, turns=[_turn()])


def test_parse_extract_facts_rejects_truncated_and_ambiguous_output() -> None:
    turns = [_turn()]
    with pytest.raises(ExtractParseError, match="truncated|not JSON"):
        parse_extract_facts('{"facts": [{"text": "未闭合"', turns=turns)
    with pytest.raises(ExtractParseError, match="ambiguous"):
        parse_extract_facts(
            '{"facts": []}\n{"facts": [{"text": "x", "source_message_ids": ["msg_00001"]}]}',
            turns=turns,
        )
    with pytest.raises(ExtractParseError, match="not JSON"):
        parse_extract_facts("模型认为没有值得保留的事实", turns=turns)


def _stub_agent(monkeypatch: pytest.MonkeyPatch, model_params: dict | None = None):
    agent = SimpleNamespace(model="stub-model", model_params=model_params)
    monkeypatch.setattr(
        "src.agent.definition.get_agent_definition",
        lambda _name: agent,
    )
    return agent


def _request(**overrides: object) -> MemoryExtractRequest:
    values: dict[str, object] = {
        "session_id": "s",
        "bank_id": "b",
        "memory_scope": "",
        "extract_agent_type": "memory-extract",
        "turns": (_turn(),),
        "timeout_seconds": 1,
    }
    values.update(overrides)
    return MemoryExtractRequest(**values)  # type: ignore[arg-type]


def test_extract_runner_uses_json_object_format_and_skips_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _LLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(
                content=[
                    {"type": "thinking", "text": '{"facts": [{"text": "思考污染"}]}'},
                    {"type": "output_text", "text": '{"facts": []}'},
                ]
            )

        def bind(self, **kwargs):
            captured["bound"] = kwargs
            return self

    def factory(model, params):
        captured["model"] = model
        captured["params"] = params
        return _LLM()

    _stub_agent(monkeypatch, {"temperature": 0.2})
    runner = DefaultExtractRunner(
        prompt_builder=SimpleNamespace(build=lambda *args, **kwargs: "sys"),
        llm_factory=factory,
    )
    facts = asyncio.run(runner.extract(_request()))
    assert facts == []
    assert captured["params"]["response_format"] == JSON_OBJECT_RESPONSE_FORMAT
    assert captured["params"]["temperature"] == 0.2
    assert "bound" not in captured  # Core adapters own protocol-specific kwargs.
    assert len(captured["messages"]) == 2


def test_extract_runner_format_correction_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _LLM:
        async def ainvoke(self, messages):
            if not calls:
                calls.append("invalid")
                return SimpleNamespace(content="先分析 { 再解释，不是 JSON")
            calls.append("json")
            assert "不是合法的提炼 JSON" in messages[-1].content
            return SimpleNamespace(content='{"facts": []}')

    _stub_agent(monkeypatch)
    runner = DefaultExtractRunner(
        prompt_builder=SimpleNamespace(build=lambda *args, **kwargs: "sys"),
        llm_factory=lambda model, params: _LLM(),
    )
    facts = asyncio.run(runner.extract(_request()))
    assert facts == []
    assert calls == ["invalid", "json"]


def test_extract_runner_does_not_retry_source_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class _LLM:
        async def ainvoke(self, messages):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "facts": [
                            {
                                "text": "x",
                                "source_message_ids": ["missing"],
                            }
                        ]
                    }
                )
            )

    _stub_agent(monkeypatch)
    runner = DefaultExtractRunner(
        prompt_builder=SimpleNamespace(build=lambda *args, **kwargs: "sys"),
        llm_factory=lambda model, params: _LLM(),
    )
    with pytest.raises(ExtractParseError, match="unknown"):
        asyncio.run(runner.extract(_request()))
    assert calls == 1


def test_extract_runner_invalid_correction_stays_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class _LLM:
        async def ainvoke(self, messages):
            nonlocal calls
            calls += 1
            return SimpleNamespace(content="still not json {")

    _stub_agent(monkeypatch)
    runner = DefaultExtractRunner(
        prompt_builder=SimpleNamespace(build=lambda *args, **kwargs: "sys"),
        llm_factory=lambda model, params: _LLM(),
    )
    with pytest.raises(ExtractParseError):
        asyncio.run(runner.extract(_request()))
    assert calls == 2


def test_extract_runner_timeout_is_not_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LLM:
        async def ainvoke(self, messages):
            await asyncio.sleep(0.05)
            return SimpleNamespace(content='{"facts": []}')

    _stub_agent(monkeypatch)
    runner = DefaultExtractRunner(
        prompt_builder=SimpleNamespace(build=lambda *args, **kwargs: "sys"),
        llm_factory=lambda model, params: _LLM(),
    )
    with pytest.raises(TimeoutError):
        asyncio.run(runner.extract(_request(timeout_seconds=0.01)))



def test_format_correction_shares_one_timeout_budget(monkeypatch):
    calls = []
    class LLM:
        async def ainvoke(self, messages):
            calls.append(1)
            await asyncio.sleep(0.03)
            return SimpleNamespace(content="not json" if len(calls) == 1 else '{"facts":[]}')
    _stub_agent(monkeypatch)
    runner = DefaultExtractRunner(
        prompt_builder=SimpleNamespace(build=lambda *args, **kwargs: "sys"),
        llm_factory=lambda model, params: LLM(),
    )
    with pytest.raises(TimeoutError):
        asyncio.run(runner.extract(_request(timeout_seconds=0.05)))
    assert len(calls) == 2
