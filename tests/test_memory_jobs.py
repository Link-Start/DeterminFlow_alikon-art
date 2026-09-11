from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.memory.contracts import RETAIN_ACCEPTED, RETAIN_CONFIRMED, MemoryFact
from src.memory.service import MemoryRuntimeService
from src.memory.store import utc_now_iso, watermark_for
from tests.test_memory_runtime import (
    SCOPE_A,
    SCOPE_B,
    FakeAuthorizer,
    FakeExtractRunner,
    FakeProvider,
    _agent,
    _policy,
    _runtime,
    _session,
)


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


def _complete_record(content: str, prefix: str = "1") -> list[dict]:
    return [
        {
            "id": f"msg_{prefix}0001",
            "type": "user",
            "source": "human",
            "content": content,
        },
        {
            "id": f"msg_{prefix}0002",
            "type": "assistant",
            "content": f"ack:{content}",
        },
    ]


async def _snapshot(service, session, content, scope=SCOPE_A):
    session.record = _complete_record(content, prefix=content[:1] or "1")
    session.pending_tool_resolutions = {}
    session.status = "running"
    await service.record_completed_invocation(
        session=session,
        content=content,
        source="human",
        append_input=True,
        invocation_context={"memory_scope": scope},
        model_context=None,
    )


def test_cross_user_and_same_user_cross_session(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _runtime(tmp_path, provider)
        user_a = _session(session_id="sess-a", external_ref="user-a")
        user_b = _session(session_id="sess-b", external_ref="user-b")
        await _snapshot(service, user_a, "用户A的长期事实", SCOPE_A)
        await _snapshot(service, user_b, "用户B的长期事实", SCOPE_B)
        same_user = _session(session_id="sess-a2", external_ref="user-a")
        await _snapshot(service, same_user, "用户A另一会话", SCOPE_A)
        await service.process_due_jobs(force=True)
        banks = {item.bank_id for item in provider.retains}
        assert SCOPE_A in banks
        assert SCOPE_B in banks
        texts = {item.content for item in provider.retains}
        assert any("用户A" in text for text in texts)
        assert any("用户B" in text for text in texts)

    asyncio.run(scenario())


def test_concurrent_claim_does_not_duplicate(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _runtime(tmp_path, provider)
        session = _session()
        await _snapshot(service, session, "只应抽取一次的事实")
        other = MemoryRuntimeService(
            service.store.root,
            extract_runner=service._extract_runner,
            worker_id="worker-2",
        )
        other.attach(
            authorizers=service._authorizers,
            providers=service._providers,
            owner_status=service._owner_status,
        )
        claimed = await asyncio.gather(
            service._claim_if_due("sess-1", force=True),
            other._claim_if_due("sess-1", force=True),
        )
        success = [item for item in claimed if item is not None]
        assert len(success) == 1
        assert success[0]["job"]["id"]

    asyncio.run(scenario())


def test_watermark_stays_when_retain_only_accepted(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        provider.retain_status = RETAIN_ACCEPTED
        service = _runtime(tmp_path, provider)
        session = _session()
        await _snapshot(service, session, "不能把 accepted 当 confirmed")
        await service.process_due_jobs(force=True)
        ledger = service.store.load("sess-1")
        assert ledger is not None
        assert ledger.get("watermarks") in ({}, None) or not any(
            ledger.get("watermarks", {}).values()
        )
        assert ledger["job"]["frozen_facts"]
        assert ledger["job"]["status"] == "retry_wait"
        first_calls = provider.retains[:]
        extract = service._extract_runner
        assert extract.calls == 1
        provider.retain_status = RETAIN_CONFIRMED
        ledger["job"]["lease_until"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        service.store.save(ledger)
        await service.process_due_jobs(force=True)
        assert extract.calls == 1
        assert len(provider.retains) > len(first_calls)
        ledger = service.store.load("sess-1")
        assert ledger["job"] is None
        assert any(ledger.get("watermarks", {}).values())

    asyncio.run(scenario())


def test_extract_failure_retries_without_moving_watermark(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        extract = FakeExtractRunner(fail=True)
        service = _runtime(tmp_path, provider, extract=extract)
        session = _session()
        await _snapshot(service, session, "抽取失败也要保留水位")
        await service.process_due_jobs(force=True)
        ledger = service.store.load("sess-1")
        assert not watermark_for(ledger, SCOPE_A)
        assert ledger["job"]["status"] == "retry_wait"
        extract.fail = False
        source_id = str(ledger["turns"][0]["messages"][0]["id"])
        extract.facts = [
            MemoryFact(
                text="frozen later",
                source_message_ids=(source_id,),
                source_timestamp=utc_now_iso(),
                turn_id=ledger["turns"][0]["turn_id"],
            )
        ]
        ledger["job"]["lease_until"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        service.store.save(ledger)
        await service.process_due_jobs(force=True)
        ledger = service.store.load("sess-1")
        assert ledger["job"] is None
        assert watermark_for(ledger, SCOPE_A)

    asyncio.run(scenario())


def test_new_messages_go_to_next_batch(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(_policy(consolidate_length_chars=1, max_batch_turns=1))
        service = _runtime(tmp_path, provider)
        session = _session()
        session.record = _complete_record("第一批", "1")
        await service.record_completed_invocation(
            session=session,
            content="第一批",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        claimed = await service._claim_if_due("sess-1", force=True)
        assert claimed is not None
        first_turn = claimed["job"]["turn_ids"][0]
        session.record = _complete_record("第一批", "1") + _complete_record(
            "下一批", "2"
        )
        await service.record_completed_invocation(
            session=session,
            content="下一批",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        await service._run_claimed_job("sess-1")
        ledger = service.store.load("sess-1")
        assert watermark_for(ledger, SCOPE_A) == first_turn
        remaining = [item["turn_id"] for item in ledger["turns"]]
        assert remaining
        assert first_turn not in remaining

    asyncio.run(scenario())


def test_scope_change_does_not_mix_banks(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _runtime(
            tmp_path,
            provider,
            authorizer=FakeAuthorizer(allowed={("ext-1", SCOPE_A), ("ext-1", SCOPE_B)}),
        )
        session = _session()
        session.record = _complete_record("旧范围", "1")
        await service.record_completed_invocation(
            session=session,
            content="旧范围",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        session.record = _complete_record("旧范围", "1") + _complete_record(
            "新范围", "2"
        )
        await service.record_completed_invocation(
            session=session,
            content="新范围",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_B},
            model_context=None,
        )
        await service.process_due_jobs(force=True)
        await service.process_due_jobs(force=True)
        banks = [item.bank_id for item in provider.retains]
        assert SCOPE_A in banks
        assert SCOPE_B in banks

    asyncio.run(scenario())


def test_closed_session_still_extracts_when_authorized(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _runtime(tmp_path, provider)
        session = _session()
        await _snapshot(service, session, "关闭后仍可整理")
        await service.mark_session_closed(session)
        await service.process_due_jobs(force=True)
        assert provider.retains
        assert provider.retains[0].content.startswith("extracted:")

    asyncio.run(scenario())


def test_config_off_and_degraded_do_not_claim(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(auto_consolidate_enabled=False, consolidate_length_chars=1)
        )
        service = _runtime(tmp_path, provider)
        session = _session()
        await _snapshot(service, session, "配置关闭后停止")
        assert await service._claim_if_due("sess-1") is None

        provider.policy = _policy(
            consolidate_length_chars=1, consolidate_idle_seconds=0
        )
        degraded = _runtime(tmp_path, provider, status="degraded")
        await _snapshot(degraded, session, "降级时不建新任务")
        assert await degraded._claim_if_due("sess-1") is None
        recovered = _runtime(tmp_path, provider, status="running")
        recovered._store = degraded.store
        claimed = await recovered._claim_if_due("sess-1", force=True)
        assert claimed is not None

    asyncio.run(scenario())


class SlowExtractRunner(FakeExtractRunner):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def extract(self, request):
        self.started.set()
        await self.release.wait()
        return await super().extract(request)


def test_foreground_snapshot_during_extract_goes_to_next_batch(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        provider = FakeProvider(_policy(consolidate_length_chars=1, max_batch_turns=1))
        extract = SlowExtractRunner()
        service = _runtime(tmp_path, provider, extract=extract)
        session = _session()
        session.record = _complete_record("第一批", "1")
        await service.record_completed_invocation(
            session=session,
            content="第一批",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        claimed = await service._claim_if_due("sess-1", force=True)
        assert claimed is not None
        first_turn = claimed["job"]["turn_ids"][0]
        running = asyncio.create_task(service._run_claimed_job("sess-1"))
        await asyncio.wait_for(extract.started.wait(), timeout=1)
        session.record = _complete_record("第一批", "1") + _complete_record(
            "下一批", "2"
        )
        await asyncio.wait_for(
            service.record_completed_invocation(
                session=session,
                content="下一批",
                source="human",
                append_input=True,
                invocation_context={"memory_scope": SCOPE_A},
                model_context=None,
            ),
            timeout=0.5,
        )
        extract.release.set()
        await asyncio.wait_for(running, timeout=2)
        ledger = service.store.load("sess-1")
        assert watermark_for(ledger, SCOPE_A) == first_turn
        remaining = [item["turn_id"] for item in ledger["turns"]]
        assert remaining
        assert first_turn not in remaining
        assert extract.calls == 1

    asyncio.run(scenario())


def test_two_batches_user_and_local_keep_cursor(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(_policy(consolidate_length_chars=1, max_batch_turns=1))
        service = _runtime(tmp_path, provider)
        session = _session()
        session.record = _complete_record("用户一批", "1")
        await service.record_completed_invocation(
            session=session,
            content="用户一批",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        session.record = _complete_record("用户一批", "1") + _complete_record(
            "用户二批", "2"
        )
        await service.record_completed_invocation(
            session=session,
            content="用户二批",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        await service.process_due_jobs(force=True)
        await service.process_due_jobs(force=True)
        assert len(provider.retains) == 2
        texts = {item.content for item in provider.retains}
        assert any("用户一批" in text for text in texts)
        assert any("用户二批" in text for text in texts)

        local_provider = FakeProvider(
            _policy(
                consolidate_length_chars=1,
                max_batch_turns=1,
                local_bank_id="local-bank",
            )
        )
        local = _runtime(tmp_path / "local", local_provider)
        local_session = _session(
            session_id="local-1",
            agent_type="main",
            session_type="main",
            resource_owner="",
            external_ref="",
            lifecycle_profile="task",
        )
        local_session.record = _complete_record("本地一批", "1")
        await local.record_completed_invocation(
            session=local_session,
            content="本地一批",
            source="human",
            append_input=True,
            invocation_context={},
            model_context=None,
        )
        local_session.record = _complete_record("本地一批", "1") + _complete_record(
            "本地二批", "2"
        )
        await local.record_completed_invocation(
            session=local_session,
            content="本地二批",
            source="human",
            append_input=True,
            invocation_context={},
            model_context=None,
        )
        await local.process_due_jobs(force=True)
        await local.process_due_jobs(force=True)
        assert len(local_provider.retains) == 2
        ledger = local.store.load("local-1")
        assert watermark_for(ledger, "local:local-bank")
        assert not ledger["turns"] or all(
            item.get("partition") != "local:local-bank" or item.get("skip_reason")
            for item in ledger["turns"]
        )

    asyncio.run(scenario())


def test_max_concurrent_jobs_and_retries(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(
                consolidate_length_chars=1,
                max_concurrent_jobs=1,
                max_retries=1,
                retry_delay_seconds=30,
            )
        )
        service = _runtime(tmp_path, provider)
        first = _session(session_id="sess-a")
        second = _session(session_id="sess-b", external_ref="user-b")
        await _snapshot(service, first, "会话A", SCOPE_A)
        await _snapshot(service, second, "会话B", SCOPE_A)
        claimed_a = await service._claim_if_due("sess-a", force=True)
        claimed_b = await service._claim_if_due("sess-b", force=True)
        assert claimed_a is not None
        assert claimed_b is None

        failing = FakeExtractRunner(fail=True)
        delayed = _runtime(
            tmp_path / "retry",
            FakeProvider(
                _policy(
                    consolidate_length_chars=1,
                    max_retries=1,
                    retry_delay_seconds=30,
                )
            ),
            extract=failing,
        )
        session = _session(session_id="sess-retry")
        session.record = _complete_record("失败重试", "1")
        await delayed.record_completed_invocation(
            session=session,
            content="失败重试",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        await delayed.process_due_jobs(force=True)
        ledger = delayed.store.load("sess-retry")
        assert ledger["job"]["status"] == "failed"
        assert not watermark_for(ledger, SCOPE_A)
        assert failing.calls == 1
        assert await delayed._claim_if_due("sess-retry", force=True) is None

        waiting = FakeExtractRunner(fail=True)
        wait_service = _runtime(
            tmp_path / "wait",
            FakeProvider(
                _policy(
                    consolidate_length_chars=1,
                    max_retries=3,
                    retry_delay_seconds=30,
                )
            ),
            extract=waiting,
        )
        wait_session = _session(session_id="sess-wait")
        wait_session.record = _complete_record("等待重试", "1")
        await wait_service.record_completed_invocation(
            session=wait_session,
            content="等待重试",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        await wait_service.process_due_jobs(force=True)
        assert wait_service.store.load("sess-wait")["job"]["status"] == "retry_wait"
        assert await wait_service._claim_if_due("sess-wait", force=True) is None
        assert waiting.calls == 1

    asyncio.run(scenario())


def test_recheck_auth_and_disable_after_extract(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        authorizer = FakeAuthorizer(allowed={("ext-1", SCOPE_A)})

        class RevokeAfterExtract(FakeExtractRunner):
            async def extract(self, request):
                facts = await super().extract(request)
                authorizer.allowed.clear()
                return facts

        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _runtime(
            tmp_path, provider, authorizer=authorizer, extract=RevokeAfterExtract()
        )
        session = _session()
        await _snapshot(service, session, "授权撤销后不能写")
        await service.process_due_jobs(force=True)
        ledger = service.store.load("sess-1")
        assert ledger["job"]["frozen_facts"]
        assert not watermark_for(ledger, SCOPE_A)
        assert provider.retains == []

        states = {"mem": {"status": "running"}, "product": {"status": "running"}}

        class DisableAfterExtract(FakeExtractRunner):
            async def extract(self, request):
                result = await super().extract(request)
                states["mem"] = {"status": "loaded"}
                return result

        disabled = MemoryRuntimeService(
            tmp_path / "disable",
            extract_runner=DisableAfterExtract(),
            worker_id="worker-1",
        )
        disabled.attach(
            authorizers={"product": FakeAuthorizer()},
            providers={"mem": FakeProvider(_policy(consolidate_length_chars=1))},
            owner_status=lambda owner: states.get(owner, {"status": "missing"}),
        )
        session = _session(session_id="sess-disable")
        session.record = _complete_record("停用后不写", "1")
        await disabled.record_completed_invocation(
            session=session,
            content="停用后不写",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        await disabled.process_due_jobs(force=True)
        ledger = disabled.store.load("sess-disable")
        assert ledger["job"]["frozen_facts"]
        assert not any((ledger.get("watermarks") or {}).values())

    asyncio.run(scenario())


def test_confirmation_is_snapshotted_and_tool_resume_completes(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _runtime(tmp_path, provider)
        session = _session()
        skipped = await service.prepare_turn_model_context(
            session=session,
            content="好的",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={"keep": True},
        )
        assert skipped == {"keep": True}
        assert provider.recalls == []
        session.record = _complete_record("好的", "1")
        await service.record_completed_invocation(
            session=session,
            content="好的",
            source="human",
            append_input=True,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        ledger = service.store.load("sess-1")
        assert ledger["turns"][0]["skip_reason"] == "confirmation"
        await service.process_due_jobs(force=True)
        assert provider.retains

        resume_session = _session(session_id="sess-resume")
        resume_session.record = [
            {
                "id": "msg_100001",
                "type": "user",
                "source": "human",
                "content": "查一下",
            },
            {
                "id": "msg_100002",
                "type": "assistant",
                "content": "",
                "tool_calls": [{"id": "call-1", "name": "lookup"}],
            },
            {
                "id": "msg_100003",
                "type": "tool",
                "tool_call_id": "call-1",
                "content": "结果已批准",
            },
            {
                "id": "msg_100004",
                "type": "assistant",
                "content": "已完成",
            },
        ]
        resume_session.pending_tool_resolutions = {}
        resume_session.status = "running"
        await service.record_completed_invocation(
            session=resume_session,
            content="",
            source="human",
            append_input=False,
            invocation_context={"memory_scope": SCOPE_A},
            model_context=None,
        )
        resume_ledger = service.store.load("sess-resume")
        assert resume_ledger["turns"]
        assert resume_ledger["turns"][0]["skip_reason"] is None
        tool_ids = [
            message["id"]
            for message in resume_ledger["turns"][0]["messages"]
            if message["type"] == "tool"
        ]
        assert tool_ids == ["msg_100003"]

    asyncio.run(scenario())
