from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from src.memory.contracts import ExtractParseError, MemoryUnavailableError, RETAIN_ACCEPTED
from src.memory.management import MemoryJobConflict
from src.memory.store import active_job
from tests.test_memory_jobs import _snapshot, patch_agents
from tests.test_memory_runtime import FakeProvider, FakeExtractRunner, _policy, _runtime, _session
from tests.test_memory_settings import _client


async def _healthy():
    return True, "ok"


async def _no_start():
    pass


class InvalidRunner:
    async def extract(self, request):
        raise ExtractParseError("extract output is not JSON: PRIVATE SOURCE TOKEN")


async def _failed(tmp_path, *, retain=False):
    provider = FakeProvider(_policy(consolidate_length_tokens=1, max_retries=1))
    provider.health = _healthy
    if retain:
        provider.retain_status = RETAIN_ACCEPTED
    runtime = _runtime(tmp_path, provider)
    runtime.start = _no_start
    if not retain:
        runtime._extract_runner = InvalidRunner()
    await _snapshot(runtime, _session(), "长期项目事实")
    await runtime.process_due_jobs(force=True)
    job = active_job(runtime.store.load("sess-1"))
    assert job["status"] == "failed"
    return runtime, provider, job


def test_retry_preserves_pending_range_and_recovers_invalid_output(tmp_path, patch_agents):
    async def scenario():
        runtime, provider, job = await _failed(tmp_path)
        before = runtime.store.load("sess-1")
        status = runtime.memory_job_status()
        assert status["counts"]["failed"] == 1
        assert status["jobs"][0]["error_code"] == "invalid_output"
        assert "PRIVATE" not in json.dumps(status)
        assert "长期项目事实" not in json.dumps(status, ensure_ascii=False)
        result = await runtime.retry_failed_memory_job("sess-1", job["id"])
        queued = runtime.store.load("sess-1")
        assert result["status"] == "retry_wait"
        assert result["error"] == ""
        assert result["error_code"] == ""
        assert queued["watermarks"] == before["watermarks"]
        assert queued["turns"] == before["turns"]
        assert queued["job"]["turn_ids"] == job["turn_ids"]
        assert queued["job"]["id"] != job["id"]
        assert runtime.store.mutate_job("sess-1", job["id"], job["worker_id"], lambda l,j:l) is None
        runtime._extract_runner = FakeExtractRunner()
        await runtime.process_due_jobs()
        done = runtime.store.load("sess-1")
        assert done["job"] is None
        assert done["turns"] == []
        assert done["last_completed"]["facts"] == 1
        assert len(provider.retains) == 1
    asyncio.run(scenario())


def test_duplicate_retry_is_fenced_and_new_turn_stays_for_next_batch(tmp_path, patch_agents):
    async def scenario():
        runtime, _, job = await _failed(tmp_path)
        await _snapshot(runtime, _session(), "另一个新事实")
        outcomes = await asyncio.gather(
            runtime.retry_failed_memory_job("sess-1", job["id"]),
            runtime.retry_failed_memory_job("sess-1", job["id"]), return_exceptions=True,
        )
        assert sum(isinstance(o, MemoryJobConflict) for o in outcomes) == 1
        assert len(runtime.store.load("sess-1")["turns"]) == 2
        assert runtime.store.load("sess-1")["job"]["turn_ids"] == job["turn_ids"]
    asyncio.run(scenario())


def test_retry_frozen_facts_does_not_extract_again(tmp_path, patch_agents):
    async def scenario():
        runtime, provider, job = await _failed(tmp_path, retain=True)
        assert job["frozen_facts"]
        runtime._extract_runner = InvalidRunner()
        provider.retain_status = "confirmed"
        first_id = provider.retains[0].document_id
        await runtime.retry_failed_memory_job("sess-1", job["id"])
        await runtime.process_due_jobs()
        assert runtime.store.load("sess-1")["job"] is None
        assert provider.retains[-1].document_id == first_id
    asyncio.run(scenario())


@pytest.mark.parametrize("gate", ["disabled", "unhealthy", "unauthorized", "missing"])
def test_retry_checks_gates_before_changing_job(tmp_path, patch_agents, gate):
    async def scenario():
        runtime, provider, job = await _failed(tmp_path)
        if gate == "disabled":
            provider.policy = replace(provider.policy, auto_consolidate_enabled=False)
        elif gate == "unhealthy":
            async def unhealthy(): return False, "bad"
            provider.health = unhealthy
        elif gate == "unauthorized":
            runtime._authorizers["product"].fail = True
        else:
            runtime._providers.clear()
        with pytest.raises(MemoryUnavailableError):
            await runtime.retry_failed_memory_job("sess-1", job["id"])
        assert runtime.store.load("sess-1")["job"] == job
    asyncio.run(scenario())


def test_jobs_api_requires_admin_and_returns_conflict(tmp_path, patch_agents, monkeypatch):
    runtime, _, job = asyncio.run(_failed(tmp_path))
    monkeypatch.delenv("DETERMINFLOW_PLUGIN_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("PLUGIN_ADMIN_TOKEN", raising=False)
    remote = _client(runtime, loopback=False)
    assert remote.get("/api/memory/jobs").status_code == 403
    assert remote.post("/api/memory/jobs/sess-1/retry", json={"job_id":job["id"]}).status_code == 403
    client = _client(runtime)
    assert client.get("/api/memory/jobs").json()["counts"]["failed"] == 1
    assert client.post("/api/memory/jobs/sess-1/retry", json={"job_id":"stale"}).status_code == 409
    assert client.post("/api/memory/jobs/sess-1/retry", json={"job_id":job["id"]}).status_code == 200
    assert client.post("/api/memory/jobs/sess-1/retry", json={"job_id":job["id"]}).status_code == 409


def test_recall_only_ledger_is_not_reported_as_completed():
    from src.memory.management import summarize_ledger
    assert summarize_ledger({"session_id": "new", "turns": []})["status"] == "idle"
