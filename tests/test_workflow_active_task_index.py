from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import src.workflow.manager as workflow_manager_module
from src.workflow.active_task_index import (
    ACTIVE_TASK_STATUSES,
    ActiveTaskIndex,
    ActiveTaskIndexError,
)
from src.workflow.definition import WorkflowTask
from src.workflow.executor_protocol import ExecutorIdentity
from src.workflow.manager import WorkflowManager
from src.workflow.task_persistence import write_task_state_file


class _Sessions:
    sessions = {}


class _Delegate:
    def __init__(self, identity: ExecutorIdentity):
        self.identity = identity


class _Pool:
    def __init__(self, *delegates: _Delegate):
        self._delegates = {
            delegate.identity.executor_id: delegate for delegate in delegates
        }
        self._ordered = list(delegates)

    @property
    def identities(self):
        return tuple(delegate.identity for delegate in self._ordered)

    def client_for(self, executor_id: str):
        return self._delegates[executor_id]

    def select_client(self, task_id: str):
        return self._ordered[sum(task_id.encode("utf-8")) % len(self._ordered)]


def _manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkflowManager:
    data_dir = tmp_path / "data"
    workflows_dir = data_dir / "workflows"
    monkeypatch.setattr(workflow_manager_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(workflow_manager_module, "WORKFLOWS_DIR", workflows_dir)
    return WorkflowManager(_Sessions())


def test_active_task_markers_follow_non_terminal_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    task = WorkflowTask(
        workflow_id="wf-1",
        task_id="task-1",
        status="pending",
    )

    manager._save_task(task)
    manager._active_task_index.ensure_ready()

    refs = manager._active_task_index.refs()
    assert [(ref.workflow_id, ref.task_id) for ref in refs] == [
        ("wf-1", "task-1")
    ]

    for status in sorted(ACTIVE_TASK_STATUSES - {"pending"}):
        task.status = status
        manager._save_task(task)
        assert len(manager._active_task_index.refs()) == 1

    task.status = "failed"
    manager._save_task(task)

    assert manager._active_task_index.refs() == []


def test_discarding_pending_task_removes_active_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    task = WorkflowTask(
        workflow_id="wf-1",
        task_id="task-pending",
        status="pending",
    )
    manager._save_task(task)

    result = asyncio.run(manager.stop_task("wf-1", "task-pending"))

    assert result["success"] is True
    assert manager._active_task_index.refs() == []
    assert not manager._get_task_path("wf-1", "task-pending").exists()


def test_first_rebuild_scans_history_once_and_keeps_only_active_tasks(
    tmp_path: Path,
) -> None:
    workflows_dir = tmp_path / "data" / "workflows"
    tasks_dir = workflows_dir / "wf-1" / "tasks"
    active = WorkflowTask(
        workflow_id="wf-1", task_id="task-running", status="running",
    )
    terminal = WorkflowTask(
        workflow_id="wf-1", task_id="task-completed", status="completed",
    )
    write_task_state_file(tasks_dir / "task-running.json", active.to_dict())
    write_task_state_file(tasks_dir / "task-completed.json", terminal.to_dict())
    index = ActiveTaskIndex(workflows_dir)

    refs = index.refs()

    assert [(ref.workflow_id, ref.task_id) for ref in refs] == [
        ("wf-1", "task-running")
    ]
    assert json.loads(index.manifest_path.read_text(encoding="utf-8")) == {
        "ready": True,
        "schema_version": 1,
    }


def test_ready_index_does_not_read_terminal_history_during_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    manager._active_task_index.ensure_ready()
    running = WorkflowTask(
        workflow_id="wf-1",
        task_id="task-running",
        status="running",
        executor_id="workflow-executor-0",
        executor_epoch="old",
    )
    completed = WorkflowTask(
        workflow_id="wf-1",
        task_id="task-completed",
        status="completed",
    )
    manager._save_task(running)
    manager._save_task(completed)
    manager._get_task_path("wf-1", "task-completed").write_text(
        "not-json", encoding="utf-8",
    )
    pool = _Pool(_Delegate(ExecutorIdentity("workflow-executor-0", "new")))

    reassigned = manager.reconcile_executor_pool(pool)

    assert reassigned == 1
    persisted = manager._load_task("wf-1", "task-running")
    assert persisted.executor_epoch == "new"


def test_index_rebuild_fails_closed_on_unreadable_history(tmp_path: Path) -> None:
    workflows_dir = tmp_path / "data" / "workflows"
    task_path = workflows_dir / "wf-1" / "tasks" / "broken.json"
    task_path.parent.mkdir(parents=True)
    task_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ActiveTaskIndexError, match="unreadable Workflow Task"):
        ActiveTaskIndex(workflows_dir).ensure_ready()


def test_failed_task_is_reassigned_lazily_for_manual_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path, monkeypatch)
    failed = WorkflowTask(
        workflow_id="wf-1",
        task_id="task-failed",
        status="failed",
        executor_id="workflow-executor-9",
        executor_epoch="retired",
    )
    manager._save_task(failed)
    delegate = _Delegate(ExecutorIdentity("workflow-executor-0", "current"))
    manager.attach_execution_delegate(_Pool(delegate))

    selected = manager._assign_delegate(failed)

    assert selected is delegate
    persisted = manager._load_task("wf-1", "task-failed")
    assert (persisted.executor_id, persisted.executor_epoch) == (
        "workflow-executor-0", "current",
    )
