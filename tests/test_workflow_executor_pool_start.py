"""Parallel start, lease order, and fail-closed cleanup for WorkflowExecutorPool."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

import src.workflow.executor_pool as executor_pool_module
from src.workflow.executor_client import (
    ExecutorUnavailable,
    WorkflowExecutorClient,
)
from src.workflow.executor_pool import (
    POOL_STATE_VERSION,
    WorkflowExecutorPool,
    executor_ids,
    executor_init_lease_path,
    executor_lease_path,
    load_recorded_executor_ids,
)
from src.workflow.executor_protocol import ExecutorIdentity
from src.workflow.executor_transport import LOOPBACK_HOST, LoopbackEndpoint


def _write_pool_state(data_dir: Path, count: int) -> None:
    path = data_dir / "system" / "workflow-executor-pool.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "version": POOL_STATE_VERSION,
            "executor_ids": [f"workflow-executor-{index}" for index in range(count)],
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    path.write_text(payload, encoding="utf-8")


async def _wait_until(predicate, *, timeout: float, message: str) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(message)


def _supervisor_double(*, fail_ids=(), delay: float = 0.0, hold: bool = False):
    state = {
        "created": [],
        "entered": [],
        "started": [],
        "stopped": [],
        "cancelled": [],
        "concurrent": 0,
        "max_concurrent": 0,
        "gate": asyncio.Event(),
    }
    if not hold:
        state["gate"].set()
    fail_ids = set(fail_ids)

    class Double:
        def __init__(self, *, executor_id, lease_path, **_kwargs):
            self.executor_id = executor_id
            self.lease_path = lease_path
            self.client = None
            self.is_ready = False
            self.pid = None
            state["created"].append(executor_id)

        async def start(self):
            state["entered"].append(self.executor_id)
            state["concurrent"] += 1
            state["max_concurrent"] = max(
                state["max_concurrent"], state["concurrent"],
            )
            try:
                await state["gate"].wait()
                if self.executor_id in fail_ids:
                    raise RuntimeError(f"{self.executor_id} failed to start")
                if delay:
                    await asyncio.sleep(delay)
                self.client = WorkflowExecutorClient(
                    LoopbackEndpoint(LOOPBACK_HOST, 1),
                    ExecutorIdentity(self.executor_id, f"{self.executor_id}-epoch"),
                    auth_token="test-auth-token",
                )
                self.is_ready = True
                state["started"].append(self.executor_id)
            except asyncio.CancelledError:
                state["cancelled"].append(self.executor_id)
                raise
            finally:
                state["concurrent"] -= 1

        async def stop(self):
            state["stopped"].append(self.executor_id)
            self.is_ready = False

    return Double, state


def _lease_double(*, fail_on: str | None = None, hold: bool = False):
    state = {
        "attempts": [],
        "acquired": [],
        "released": [],
        "concurrent": 0,
        "max_concurrent": 0,
        "gate": threading.Event(),
        "lock": threading.Lock(),
    }
    if not hold:
        state["gate"].set()

    class Double:
        def __init__(self, path):
            self.path = Path(path)

        def acquire(self, timeout):
            with state["lock"]:
                state["concurrent"] += 1
                state["max_concurrent"] = max(
                    state["max_concurrent"], state["concurrent"],
                )
                state["attempts"].append(self.path.name)
            try:
                if not state["gate"].wait(timeout):
                    raise TimeoutError(self.path.name)
                if fail_on is not None and self.path.name == fail_on:
                    raise RuntimeError(f"lease failed: {self.path.name}")
                state["acquired"].append(self.path.name)
            finally:
                with state["lock"]:
                    state["concurrent"] -= 1

        def release(self):
            state["released"].append(self.path.name)

    return Double, state


def test_init_lease_path_does_not_collide_with_member_leases(tmp_path):
    member_names = {
        executor_lease_path(tmp_path, executor_id).name
        for executor_id in executor_ids(32)
    }
    assert executor_init_lease_path(tmp_path).name not in member_names


def test_pool_starts_members_in_parallel_and_marks_started_only_after_all_succeed(
    tmp_path, monkeypatch,
):
    Supervisor, state = _supervisor_double(hold=True)
    monkeypatch.setattr(
        executor_pool_module, "WorkflowExecutorSupervisor", Supervisor,
    )

    async def scenario():
        pool = WorkflowExecutorPool(3, data_dir=tmp_path, startup_timeout=1.0)
        start_task = asyncio.create_task(pool.start())
        try:
            await _wait_until(
                lambda: len(state["entered"]) == 3,
                timeout=1.0,
                message="all supervisors to enter start together",
            )
            assert state["max_concurrent"] == 3
            assert state["started"] == []
            assert pool._started is False
            with pytest.raises(ExecutorUnavailable, match="has not started"):
                pool.select_client("task-new")
            assert not (tmp_path / "system" / "workflow-executor-pool.json").exists()

            state["gate"].set()
            await start_task
            assert pool._started is True
            assert set(state["started"]) == {
                "workflow-executor-0",
                "workflow-executor-1",
                "workflow-executor-2",
            }
            assert load_recorded_executor_ids(tmp_path) == pool.executor_ids
            assert [
                pool.select_client(f"task-{index}").identity.executor_id
                for index in range(3)
            ] == [
                "workflow-executor-0",
                "workflow-executor-1",
                "workflow-executor-2",
            ]
        finally:
            state["gate"].set()
            if not start_task.done():
                start_task.cancel()
                await asyncio.gather(start_task, return_exceptions=True)
            await pool.stop()

        assert pool._started is False
        assert pool._supervisors == {}

    asyncio.run(scenario())


def test_pool_start_failure_waits_for_siblings_then_stops_all(tmp_path, monkeypatch):
    Supervisor, state = _supervisor_double(
        fail_ids={"workflow-executor-1"},
        delay=0.05,
    )
    monkeypatch.setattr(
        executor_pool_module, "WorkflowExecutorSupervisor", Supervisor,
    )

    async def scenario():
        pool = WorkflowExecutorPool(3, data_dir=tmp_path, startup_timeout=1.0)
        with pytest.raises(RuntimeError, match="workflow-executor-1 failed to start"):
            await pool.start()

        assert pool._started is False
        assert pool._supervisors == {}
        assert state["cancelled"] == []
        assert set(state["started"]) == {
            "workflow-executor-0",
            "workflow-executor-2",
        }
        assert state["stopped"] == [
            "workflow-executor-2",
            "workflow-executor-1",
            "workflow-executor-0",
        ]
        assert not (tmp_path / "system" / "workflow-executor-pool.json").exists()

    asyncio.run(scenario())


def test_pool_acquires_retired_leases_serially_before_starting_members(
    tmp_path, monkeypatch,
):
    _write_pool_state(tmp_path, 4)
    Supervisor, supervisors = _supervisor_double(hold=True)
    Lease, leases = _lease_double(hold=True)
    monkeypatch.setattr(
        executor_pool_module, "WorkflowExecutorSupervisor", Supervisor,
    )
    monkeypatch.setattr(executor_pool_module, "ExecutorProcessLease", Lease)
    retired_names = [
        executor_lease_path(tmp_path, "workflow-executor-2").name,
        executor_lease_path(tmp_path, "workflow-executor-3").name,
    ]

    async def scenario():
        pool = WorkflowExecutorPool(2, data_dir=tmp_path, startup_timeout=1.0)
        start_task = asyncio.create_task(pool.start())
        try:
            await _wait_until(
                lambda: leases["attempts"] == [retired_names[0]],
                timeout=1.0,
                message="first retired lease acquire to start",
            )
            await asyncio.sleep(0.05)
            assert leases["attempts"] == [retired_names[0]]
            assert leases["max_concurrent"] == 1
            assert supervisors["entered"] == []
            assert pool._started is False

            leases["gate"].set()
            await _wait_until(
                lambda: len(supervisors["entered"]) == 2,
                timeout=1.0,
                message="member supervisors to start after retired leases",
            )
            assert leases["attempts"] == retired_names
            assert leases["acquired"] == retired_names
            assert leases["max_concurrent"] == 1
            assert supervisors["max_concurrent"] == 2
            assert pool._started is False

            supervisors["gate"].set()
            await start_task
            assert pool._started is True
            assert load_recorded_executor_ids(tmp_path) == pool.executor_ids
        finally:
            leases["gate"].set()
            supervisors["gate"].set()
            if not start_task.done():
                start_task.cancel()
                await asyncio.gather(start_task, return_exceptions=True)
            await pool.stop()

        assert leases["released"] == list(reversed(retired_names))

    asyncio.run(scenario())


def test_pool_releases_retired_leases_and_skips_supervisors_when_lease_acquire_fails(
    tmp_path, monkeypatch,
):
    _write_pool_state(tmp_path, 4)
    Supervisor, supervisors = _supervisor_double()
    fail_on = executor_lease_path(tmp_path, "workflow-executor-3").name
    first_retired = executor_lease_path(tmp_path, "workflow-executor-2").name
    Lease, leases = _lease_double(fail_on=fail_on)
    monkeypatch.setattr(
        executor_pool_module, "WorkflowExecutorSupervisor", Supervisor,
    )
    monkeypatch.setattr(executor_pool_module, "ExecutorProcessLease", Lease)

    async def scenario():
        pool = WorkflowExecutorPool(2, data_dir=tmp_path, startup_timeout=1.0)
        with pytest.raises(RuntimeError, match="lease failed"):
            await pool.start()

        assert pool._started is False
        assert pool._supervisors == {}
        assert supervisors["created"] == []
        assert supervisors["entered"] == []
        assert leases["attempts"] == [first_retired, fail_on]
        assert leases["acquired"] == [first_retired]
        assert leases["released"] == [first_retired]
        assert load_recorded_executor_ids(tmp_path) == (
            "workflow-executor-0",
            "workflow-executor-1",
            "workflow-executor-2",
            "workflow-executor-3",
        )

    asyncio.run(scenario())
