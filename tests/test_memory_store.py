from __future__ import annotations

import multiprocessing
from pathlib import Path

from src.memory.store import (
    MemoryLedgerConflict,
    MemoryLedgerStore,
    empty_ledger,
    new_job,
)


def _create_store(root: Path) -> MemoryLedgerStore:
    store = MemoryLedgerStore(root)
    store.create(
        session_id="sess-1",
        provider_id="mem",
        resource_owner="product",
        external_ref="ext-1",
        agent_type="page-assistant",
    )
    return store


def _save_race(root: str, session_id: str, queue, barrier) -> None:
    store = MemoryLedgerStore(Path(root))
    ledger = store.load(session_id)
    barrier.wait()
    try:
        store.save(ledger)
        queue.put("ok")
    except MemoryLedgerConflict:
        queue.put("conflict")


def _claim_install(root: str, worker_id: str, queue, barrier) -> None:
    store = MemoryLedgerStore(Path(root))
    barrier.wait()

    def mutator(current, conn):
        existing = current.get("job")
        if existing:
            return None
        active = store.count_active_jobs(conn=conn, exclude_session_id="sess-1")
        if active >= 1:
            return None
        current["job"] = new_job(
            job_id=f"job-{worker_id}",
            worker_id=worker_id,
            partition="aaaa",
            memory_scope="a" * 64,
            bank_id="a" * 64,
            turn_ids=["t1"],
            lease_seconds=30,
        )
        return current

    result = store.transact("sess-1", mutator)
    queue.put(bool(result and result.get("job")))


def test_cross_process_save_is_atomic(tmp_path: Path) -> None:
    store = _create_store(tmp_path)
    assert store.load("sess-1")["version"] == 0
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    procs = [
        ctx.Process(
            target=_save_race,
            args=(str(tmp_path), "sess-1", queue, barrier),
        )
        for _ in range(2)
    ]
    for proc in procs:
        proc.start()
    results = [queue.get(timeout=15) for _ in range(2)]
    for proc in procs:
        proc.join(timeout=15)
        assert proc.exitcode == 0
    assert results.count("ok") == 1
    assert results.count("conflict") == 1
    assert store.load("sess-1")["version"] == 1


def test_cross_process_claim_fences_one_winner(tmp_path: Path) -> None:
    _create_store(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    procs = [
        ctx.Process(
            target=_claim_install,
            args=(str(tmp_path), f"worker-{index}", queue, barrier),
        )
        for index in range(2)
    ]
    for proc in procs:
        proc.start()
    results = [queue.get(timeout=15) for _ in range(2)]
    for proc in procs:
        proc.join(timeout=15)
        assert proc.exitcode == 0
    assert results.count(True) == 1
    assert results.count(False) == 1
    ledger = MemoryLedgerStore(tmp_path).load("sess-1")
    assert ledger["job"]["id"].startswith("job-")


def test_job_mutate_requires_matching_worker(tmp_path: Path) -> None:
    store = _create_store(tmp_path)
    ledger = store.load("sess-1")
    ledger["job"] = new_job(
        job_id="job-1",
        worker_id="worker-1",
        partition="p",
        memory_scope="",
        bank_id="local-bank",
        turn_ids=["t1"],
        lease_seconds=30,
    )
    store.save(ledger)

    def freeze(current, job):
        job["frozen_facts"] = [{"text": "x"}]
        current["job"] = job
        return current

    assert store.mutate_job("sess-1", "job-1", "worker-2", freeze) is None
    assert store.mutate_job("sess-1", "job-1", "worker-1", freeze) is not None
    assert store.load("sess-1")["job"]["frozen_facts"][0]["text"] == "x"


def test_empty_ledger_has_seen_turn_ids() -> None:
    ledger = empty_ledger(
        session_id="s",
        provider_id="mem",
        resource_owner="",
        external_ref="",
        agent_type="main",
    )
    assert ledger["seen_turn_ids"] == []
    assert ledger["job"] is None
