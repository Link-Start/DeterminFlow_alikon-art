from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from src.memory.service import MemoryRuntimeService
from src.memory.store import watermark_for
from tests.test_memory_jobs import _snapshot, patch_agents  # noqa: F401
from tests.test_memory_runtime import (
    SCOPE_A,
    FakeAuthorizer,
    FakeExtractRunner,
    FakeProvider,
    _policy,
    _runtime,
    _session,
)

pytestmark = pytest.mark.usefixtures("patch_agents")


def test_same_worker_cannot_claim_the_same_live_job_twice(tmp_path):
    async def scenario():
        service = _runtime(tmp_path, FakeProvider(_policy(consolidate_length_chars=1)))
        await _snapshot(service, _session(), "same worker")
        claims = await asyncio.gather(
            *(service._claim_if_due("sess-1", force=True) for _ in range(2))
        )
        assert sum(item is not None for item in claims) == 1

    asyncio.run(scenario())


def test_scope_is_checked_before_every_fact_write(tmp_path):
    async def scenario():
        authorizer = FakeAuthorizer(allowed={("ext-1", SCOPE_A)})

        class RevokeAfterWrite(FakeProvider):
            async def retain(self, request):
                result = await super().retain(request)
                authorizer.allowed.clear()
                return result

        class TwoFacts(FakeExtractRunner):
            async def extract(self, request):
                first = list(await super().extract(request))[0]
                return [first, replace(first, text="second confirmed fact")]

        provider = RevokeAfterWrite(_policy(consolidate_length_chars=1))
        service = _runtime(
            tmp_path, provider, authorizer=authorizer, extract=TwoFacts()
        )
        await _snapshot(service, _session(), "authorized fact")
        await service.process_due_jobs(force=True)
        assert len(provider.retains) == 1
        assert not watermark_for(service.store.load("sess-1"), SCOPE_A)

    asyncio.run(scenario())


def test_token_trigger_counts_all_pending_turns(tmp_path):
    async def scenario():
        provider = FakeProvider(
            _policy(
                consolidate_length_tokens=80,
                max_batch_turns=1,
                consolidate_idle_seconds=3600,
            )
        )
        service = _runtime(tmp_path, provider)
        session = _session()
        for prefix in "abc":
            await _snapshot(service, session, prefix + "x" * 60)
        assert await service.process_due_jobs() == 1
        assert len(provider.retains) == 1
        assert len(service.store.load("sess-1")["turns"]) == 2

    asyncio.run(scenario())


def test_no_provider_does_not_start_memory_scheduler(tmp_path):
    async def scenario():
        service = MemoryRuntimeService(tmp_path)
        await service.start()
        try:
            assert service._scheduler_task is None
        finally:
            await service.stop()

    asyncio.run(scenario())


def test_snapshot_keeps_fact_at_end_of_a_long_message(tmp_path):
    async def scenario():
        service = _runtime(tmp_path, FakeProvider(_policy()))
        content = "背景" * 3000 + "最终确认项目负责人为孟青。"
        await _snapshot(service, _session(), content)
        messages = service.store.load("sess-1")["turns"][0]["messages"]
        assert messages[0]["content"] == content

    asyncio.run(scenario())


def test_binding_uses_optional_agent_policy(tmp_path):
    async def scenario():
        class PerAgentProvider(FakeProvider):
            def runtime_policy_for_agent(self, agent_type):
                assert agent_type == "page-assistant"
                return replace(self.policy, recall_max_tokens=1234)

        service = _runtime(tmp_path, PerAgentProvider())
        binding = await service._binding_for_session(
            _session(), invocation_context={"memory_scope": SCOPE_A}, require_scope=True
        )
        assert binding.policy.recall_max_tokens == 1234

    asyncio.run(scenario())


def test_scheduler_runs_up_to_configured_parallelism(tmp_path):
    async def scenario():
        both = asyncio.Event()

        class ParallelExtract(FakeExtractRunner):
            def __init__(self):
                super().__init__()
                self.started = 0

            async def extract(self, request):
                self.started += 1
                if self.started == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 1)
                return await super().extract(request)

        runner = ParallelExtract()
        service = _runtime(
            tmp_path,
            FakeProvider(_policy(consolidate_length_chars=1, max_concurrent_jobs=2)),
            extract=runner,
        )
        await _snapshot(service, _session(session_id="s-a"), "fact a")
        await _snapshot(service, _session(session_id="s-b"), "fact b")
        assert await service.process_due_jobs(force=True) == 2
        assert both.is_set()
        assert watermark_for(service.store.load("s-a"), SCOPE_A)
        assert watermark_for(service.store.load("s-b"), SCOPE_A)

    asyncio.run(scenario())


def test_oversized_turn_does_not_advance_progress(tmp_path):
    async def scenario():
        provider = FakeProvider(_policy(consolidate_length_chars=1))
        service = _runtime(tmp_path, provider)
        await _snapshot(service, _session(), "x" * 130_000)
        await service.process_due_jobs(force=True)
        ledger = service.store.load("sess-1")
        assert ledger["job"]["status"] == "retry_wait"
        assert not watermark_for(ledger, SCOPE_A)
        assert provider.retains == []

    asyncio.run(scenario())


def test_batch_budget_leaves_complete_remaining_turns(tmp_path):
    async def scenario():
        provider = FakeProvider(_policy(consolidate_length_chars=1, max_batch_turns=8))
        service = _runtime(tmp_path, provider)
        session = _session()
        for prefix in "ab":
            await _snapshot(service, session, prefix + "x" * 40_000)
        assert await service.process_due_jobs(force=True) == 1
        assert len(service.store.load("sess-1")["turns"]) == 1
        assert await service.process_due_jobs(force=True) == 1
        assert service.store.load("sess-1")["turns"] == []

    asyncio.run(scenario())


def test_model_render_does_not_expose_memory_routing_markers():
    from src.agent.message_context import compose_user_model_content

    context = {
        "long_term_memory": {
            "bank_id": "private-bank",
            "memory_scope": SCOPE_A,
            "items": [{"id": "m1", "text": "confirmed fact"}],
        }
    }
    rendered = compose_user_model_content("original", model_context=context)
    assert SCOPE_A not in rendered and "private-bank" not in rendered
    assert "confirmed fact" in rendered and "original" in rendered
    assert context["long_term_memory"]["memory_scope"] == SCOPE_A
