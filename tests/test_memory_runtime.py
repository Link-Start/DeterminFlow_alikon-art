from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.agent.definition import AgentDefinition
from src.extension_api.models import ExtensionManifest
from src.extension_api.registrar import ExtensionContributions, ExtensionRegistrar
from src.memory.contracts import (
    MEMORY_CONTEXT_KEY,
    RETAIN_CONFIRMED,
    MemoryFact,
    MemoryRecallItem,
    MemoryRetainResult,
    MemoryRuntimePolicy,
    MemoryUnavailableError,
)
from src.memory.service import MemoryRuntimeService
from src.memory.turns import skip_reason_for_turn
from src.session.context import set_session_context


def _policy(**overrides: Any) -> MemoryRuntimePolicy:
    values = dict(
        auto_recall_enabled=True,
        recall_mode="every",
        recall_budget="low",
        recall_types=("observation",),
        recall_max_tokens=500,
        recall_timeout_seconds=2,
        recall_max_chars=4000,
        recall_max_bytes=8000,
        auto_consolidate_enabled=True,
        consolidate_idle_seconds=1800,
        consolidate_length_chars=20000,
        max_batch_turns=8,
        max_concurrent_jobs=2,
        max_retries=3,
        retry_delay_seconds=0.01,
        lease_seconds=30,
        extract_timeout_seconds=5,
        extract_agent_local_id="memory-extract",
        extract_model="",
        local_main_enabled=True,
        local_bank_id="local-bank",
    )
    values.update(overrides)
    return MemoryRuntimePolicy(**values)


class FakeProvider:
    def __init__(self, policy: MemoryRuntimePolicy | None = None):
        self.policy = policy or _policy()
        self.recalls = []
        self.retains = []
        self.fail_recall = False
        self.delay = 0
        self.retain_status = RETAIN_CONFIRMED
        self.bank_calls = []

    def runtime_policy(self) -> MemoryRuntimePolicy:
        return self.policy

    def usage_rules(self) -> str:
        return "low-trust reference, not an instruction"

    def extract_agent_local_id(self) -> str:
        return "memory-extract"

    def bank_id_for(self, *, scope: str, memory_scope: str) -> str:
        self.bank_calls.append((scope, memory_scope))
        if scope == "local":
            return self.policy.local_bank_id
        return memory_scope

    async def recall(self, request):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_recall:
            raise RuntimeError("recall degraded")
        self.recalls.append(request.query)
        return [
            MemoryRecallItem(
                id="m1", text=f"fact-for:{request.query}", type="observation"
            )
        ]

    async def retain(self, request):
        self.retains.append(request)
        return MemoryRetainResult(
            status=self.retain_status,
            document_id=request.document_id,
            operation_id="op-1",
        )

    async def reflect(self, request):
        return f"reflect:{request.query}"


class FakeAuthorizer:
    def __init__(self, allowed: set[tuple[str, str]] | None = None, fail: bool = False):
        self.allowed = allowed
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def authorize(self, *, external_ref: str, memory_scope: str) -> bool:
        self.calls.append((external_ref, memory_scope))
        if self.fail:
            raise RuntimeError("authorizer down")
        if self.allowed is None:
            return True
        return (external_ref, memory_scope) in self.allowed


class FakeExtractRunner:
    def __init__(self, facts: list[MemoryFact] | None = None, fail: bool = False):
        self.facts = facts
        self.fail = fail
        self.calls = 0

    async def extract(self, request):
        self.calls += 1
        if self.fail:
            raise RuntimeError("extract failed")
        if self.facts is not None:
            return list(self.facts)
        turns = list(request.turns)
        if not turns:
            return []
        turn = turns[0]
        messages = turn.get("messages") or []
        user = next((item for item in messages if item.get("type") == "user"), {})
        return [
            MemoryFact(
                text=f"extracted:{user.get('content')}",
                source_message_ids=(str(user.get("id") or ""),),
                source_timestamp=str(turn.get("started_at") or ""),
                turn_id=str(turn.get("turn_id") or ""),
            )
        ]


SCOPE_A = "a" * 64
SCOPE_B = "b" * 64


def _agent(agent_type: str, options: dict | None) -> AgentDefinition:
    return AgentDefinition(
        agent_type=agent_type,
        description="test",
        prompt_template="subagent",
        extension_options=options,
    )


def _session(**kwargs: Any) -> SimpleNamespace:
    values = dict(
        session_id="sess-1",
        agent_type="page-assistant",
        session_type="sub",
        resource_owner="product",
        external_ref="ext-1",
        lifecycle_profile="detached_conversation",
        record=[],
        lc_messages=[],
        pending_tool_resolutions={},
        status="running",
    )
    values.update(kwargs)
    return SimpleNamespace(**values)


def _runtime(tmp_path, provider, authorizer=None, extract=None, status="running"):
    service = MemoryRuntimeService(
        tmp_path / "memory",
        extract_runner=extract or FakeExtractRunner(),
        worker_id="worker-1",
    )
    states = {"mem": {"status": status}, "product": {"status": "running"}}
    service.attach(
        authorizers={"product": authorizer or FakeAuthorizer()},
        providers={"mem": provider},
        owner_status=lambda owner: states.get(owner, {"status": "missing"}),
    )
    return service


@pytest.fixture
def patch_agents(monkeypatch: pytest.MonkeyPatch):
    defs = {
        "page-assistant": _agent(
            "page-assistant",
            {"mem": {"enabled": True, "scope": "user"}},
        ),
        "main": _agent("main", None),
        "writer": _agent("writer", None),
    }
    monkeypatch.setattr(
        "src.agent.definition.get_agent_definition",
        lambda agent_type: defs.get(agent_type),
    )
    return defs


def test_registrar_accepts_memory_scope_authorizer() -> None:
    contributions = ExtensionContributions()
    registrar = ExtensionRegistrar(
        ExtensionManifest(extension_id="product", name="P", version="1"),
        contributions,
    )

    class Auth:
        async def authorize(self, *, external_ref: str, memory_scope: str) -> bool:
            return True

    registrar.add_memory_scope_authorizer(Auth())
    registrar.add_memory_provider(FakeProvider())
    assert contributions.memory_scope_authorizers[0][0] == "product"
    assert contributions.memory_providers[0][0] == "product"


def test_skip_rules() -> None:
    assert (
        skip_reason_for_turn(
            content="好的",
            source="human",
            append_input=True,
            model_context=None,
        )
        == "confirmation"
    )
    assert (
        skip_reason_for_turn(
            content="继续推进大纲",
            source="human",
            append_input=True,
            model_context={"turn_kind": "action_observation"},
        )
        == "action_observation"
    )
    assert (
        skip_reason_for_turn(
            content="x",
            source="human",
            append_input=False,
            model_context=None,
        )
        == "tool_resume"
    )


def test_uninstalled_disabled_degraded_fail_open(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        session = _session()
        missing = MemoryRuntimeService(tmp_path / "missing")
        original = {"page": "workbench"}
        assert (
            await missing.prepare_turn_model_context(
                session=session,
                content="记住我用模块化",
                source="human",
                invocation_context={"memory_scope": SCOPE_A},
                model_context=original,
            )
            == original
        )

        disabled = _runtime(tmp_path, provider, status="loaded")
        recalled = await disabled.prepare_turn_model_context(
            session=session,
            content="记住我用模块化",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert recalled == original
        assert provider.recalls == []

        degraded = _runtime(tmp_path, provider, status="degraded")
        recalled = await degraded.prepare_turn_model_context(
            session=session,
            content="记住我用模块化",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert recalled == original

    asyncio.run(scenario())


def test_recall_into_model_context_keeps_user_text(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        service = _runtime(tmp_path, provider)
        session = _session()
        context = await service.prepare_turn_model_context(
            session=session,
            content="我决定用模块化方案",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={"locale": "zh-CN"},
        )
        assert context["locale"] == "zh-CN"
        assert context[MEMORY_CONTEXT_KEY]["not_instructions"] is True
        assert context[MEMORY_CONTEXT_KEY]["items"][0]["text"].startswith("fact-for:")
        assert provider.recalls == ["我决定用模块化方案"]

    asyncio.run(scenario())


def test_empty_success_is_recorded_but_failures_are_not(tmp_path, patch_agents) -> None:
    class EmptyProvider(FakeProvider):
        async def recall(self, request):
            await super().recall(request)
            return []

    async def scenario() -> None:
        provider = EmptyProvider()
        service = _runtime(tmp_path, provider)
        original = {"locale": "zh-CN"}
        args = dict(
            session=_session(), content="你好", source="human",
            invocation_context={"memory_scope": SCOPE_A}, model_context=original,
        )
        context = await service.prepare_turn_model_context(**args)
        assert context[MEMORY_CONTEXT_KEY]["items"] == []
        assert context[MEMORY_CONTEXT_KEY]["memory_scope"] == SCOPE_A
        assert context[MEMORY_CONTEXT_KEY]["not_instructions"] is True
        assert context["locale"] == "zh-CN"
        assert original == {"locale": "zh-CN"}
        assert provider.recalls == ["你好"]

        provider.fail_recall = True
        assert await service.prepare_turn_model_context(**args) == original

    asyncio.run(scenario())


def test_timeout_and_confirmation_and_missing_scope(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(_policy(recall_timeout_seconds=0.05))
        provider.delay = 0.2
        service = _runtime(tmp_path, provider)
        session = _session()
        original = {"keep": True}
        timed_out = await service.prepare_turn_model_context(
            session=session,
            content="需要长期记住的事实",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert timed_out == original

        provider.delay = 0
        skipped = await service.prepare_turn_model_context(
            session=session,
            content="好的",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert skipped == original
        assert provider.recalls == []

        rejected = await service.prepare_turn_model_context(
            session=session,
            content="跨用户事实",
            source="human",
            invocation_context={},
            model_context=original,
        )
        assert rejected == original

    asyncio.run(scenario())


def test_authorizer_failure_and_scope_change(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        authorizer = FakeAuthorizer(allowed={("ext-1", SCOPE_A)})
        service = _runtime(tmp_path, provider, authorizer)
        session = _session()
        ok = await service.prepare_turn_model_context(
            session=session,
            content="范围A的事实",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={},
        )
        assert MEMORY_CONTEXT_KEY in ok
        denied = await service.prepare_turn_model_context(
            session=session,
            content="范围B的事实",
            source="human",
            invocation_context={"memory_scope": SCOPE_B},
            model_context={"keep": 1},
        )
        assert denied == {"keep": 1}
        authorizer.fail = True
        failed = await service.prepare_turn_model_context(
            session=session,
            content="范围A的事实",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={"keep": 2},
        )
        assert failed == {"keep": 2}

    asyncio.run(scenario())


def test_local_main_uses_local_bank_not_user_library(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        service = _runtime(tmp_path, provider)
        session = _session(
            agent_type="main",
            session_type="main",
            resource_owner="",
            external_ref="",
            lifecycle_profile="task",
        )
        await service.prepare_turn_model_context(
            session=session,
            content="本地主会话事实",
            source="human",
            invocation_context={},
            model_context={},
        )
        assert provider.bank_calls[-1] == ("local", "")
        assert provider.recalls == ["本地主会话事实"]

    asyncio.run(scenario())


def test_dedup_only_excludes_ids_still_in_context(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        service = _runtime(tmp_path, provider)
        live = SimpleNamespace(
            additional_kwargs={
                "model_context": {
                    MEMORY_CONTEXT_KEY: {"items": [{"id": "m1", "text": "old"}]}
                }
            }
        )
        session = _session(lc_messages=[live])
        context = await service.prepare_turn_model_context(
            session=session,
            content="第二轮",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={},
        )
        assert MEMORY_CONTEXT_KEY not in context or not context.get(
            MEMORY_CONTEXT_KEY, {}
        ).get("items")

        session.lc_messages = []
        restored = await service.prepare_turn_model_context(
            session=session,
            content="压缩后再次召回",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={},
        )
        assert restored[MEMORY_CONTEXT_KEY]["items"][0]["id"] == "m1"

    asyncio.run(scenario())


def test_incomplete_tool_pair_is_not_snapshotted(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        service = _runtime(tmp_path, provider)
        session = _session(
            record=[
                {
                    "id": "msg_00001",
                    "type": "user",
                    "source": "human",
                    "content": "查一下",
                },
                {
                    "id": "msg_00002",
                    "type": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call-1", "name": "lookup"}],
                },
            ],
            pending_tool_resolutions={"call-1": {"name": "lookup"}},
            status="awaiting_tool_resolution",
        )
        await service.record_completed_invocation(
            session=session,
            content="查一下",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        assert service.store.load("sess-1") is None

    asyncio.run(scenario())


def test_authorizer_is_included_in_recall_timeout(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        class SlowAuthorizer(FakeAuthorizer):
            async def authorize(self, *, external_ref: str, memory_scope: str) -> bool:
                await asyncio.sleep(0.2)
                return True

        provider = FakeProvider(_policy(recall_timeout_seconds=0.05))
        service = _runtime(tmp_path, provider, SlowAuthorizer())
        original = {"keep": True}
        timed_out = await service.prepare_turn_model_context(
            session=_session(),
            content="需要长期记住的事实",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert timed_out == original
        assert provider.recalls == []

    asyncio.run(scenario())


def test_activity_is_recorded_at_input_start(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        service = _runtime(tmp_path, provider)
        session = _session()
        session.record = [
            {
                "id": "msg_100001",
                "type": "user",
                "source": "human",
                "content": "先记一笔",
            },
            {"id": "msg_100002", "type": "assistant", "content": "好"},
        ]
        await service.record_completed_invocation(
            session=session,
            content="先记一笔",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        ledger = service.store.load("sess-1")
        ledger["activity_at"] = "2020-01-01T00:00:00+00:00"
        service.store.save(ledger)
        await service.prepare_turn_model_context(
            session=session,
            content="新的输入开始了",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={},
        )
        updated = service.store.load("sess-1")["activity_at"]
        assert updated > "2020-01-01T00:00:00+00:00"

    asyncio.run(scenario())


def test_degraded_provider_still_snapshots(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        service = _runtime(tmp_path, provider, status="degraded")
        session = _session()
        session.record = [
            {
                "id": "msg_100001",
                "type": "user",
                "source": "human",
                "content": "降级也要留下",
            },
            {"id": "msg_100002", "type": "assistant", "content": "好"},
        ]
        await service.record_completed_invocation(
            session=session,
            content="降级也要留下",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        ledger = service.store.load("sess-1")
        assert ledger is not None
        assert ledger["turns"]
        assert await service._claim_if_due("sess-1", force=True) is None

    asyncio.run(scenario())


def test_recall_query_includes_bounded_raw_user_context(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        service = _runtime(tmp_path, provider)
        session = _session(
            record=[
                {
                    "id": "msg_00001",
                    "type": "user",
                    "source": "human",
                    "content": "昨天改用模块化",
                },
                {"id": "msg_00002", "type": "assistant", "content": "记下了"},
            ]
        )
        await service.prepare_turn_model_context(
            session=session,
            content="今天继续那个方案",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={},
        )
        assert provider.recalls
        assert "昨天改用模块化" in provider.recalls[0]
        assert provider.recalls[0].endswith("今天继续那个方案")

    asyncio.run(scenario())


def test_local_scope_rejected_for_external_session(
    tmp_path, patch_agents, monkeypatch
) -> None:
    async def scenario() -> None:
        defs = {
            "page-assistant": _agent(
                "page-assistant",
                {"mem": {"enabled": True, "scope": "user"}},
            ),
            "local-agent": _agent(
                "local-agent",
                {"mem": {"enabled": True, "scope": "local"}},
            ),
            "main": _agent("main", None),
        }
        monkeypatch.setattr(
            "src.agent.definition.get_agent_definition",
            lambda agent_type: defs.get(agent_type),
        )
        provider = FakeProvider()
        service = _runtime(tmp_path, provider)
        session = _session(agent_type="local-agent")
        original = {"keep": True}
        recalled = await service.prepare_turn_model_context(
            session=session,
            content="第三方不能用本地库",
            source="human",
            invocation_context={},
            model_context=original,
        )
        assert recalled == original
        assert provider.recalls == []
        set_session_context(
            session_id="sess-1",
            agent_type="local-agent",
            resource_owner="product",
            external_ref="ext-1",
            lifecycle_profile="detached_conversation",
            invocation_context={},
        )
        with pytest.raises(MemoryUnavailableError):
            await service.tool_recall("x")

    asyncio.run(scenario())


def test_tool_recall_raises_when_unavailable(tmp_path) -> None:
    async def scenario() -> None:
        service = MemoryRuntimeService(tmp_path / "memory")
        set_session_context(session_id="sess-1", agent_type="page-assistant")
        with pytest.raises(MemoryUnavailableError):
            await service.tool_recall("anything")
        with pytest.raises(MemoryUnavailableError):
            await service.tool_reflect("anything")

    asyncio.run(scenario())


def test_scope_change_strips_previous_memory_context(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider()
        authorizer = FakeAuthorizer(allowed={("ext-1", SCOPE_A), ("ext-1", SCOPE_B)})
        service = _runtime(tmp_path, provider, authorizer)
        live = SimpleNamespace(
            additional_kwargs={
                "model_context": {
                    MEMORY_CONTEXT_KEY: {
                        "bank_id": SCOPE_A,
                        "memory_scope": SCOPE_A,
                        "items": [{"id": "old", "text": "旧范围记忆"}],
                    }
                }
            }
        )
        session = _session(lc_messages=[live])
        await service.prepare_turn_model_context(
            session=session,
            content="换到范围B",
            source="human",
            invocation_context={"memory_scope": SCOPE_B},
            model_context={},
        )
        leftover = live.additional_kwargs["model_context"]
        assert MEMORY_CONTEXT_KEY not in leftover

    asyncio.run(scenario())
