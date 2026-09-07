from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

import src.workflow.executor_client as executor_client_module
from src.workflow.executor_client import WorkflowExecutorClient


REPO_ROOT = Path(__file__).parents[1]


def test_executor_recovery_timeout_config_is_strict_and_prefixed() -> None:
    environment = os.environ.copy()
    environment["DETERMINFLOW_WORKFLOW_EXECUTOR_RECOVERY_TIMEOUT_SECONDS"] = "240"
    valid = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from src.config import "
                "WORKFLOW_EXECUTOR_RECOVERY_TIMEOUT_SECONDS; "
                "print(WORKFLOW_EXECUTOR_RECOVERY_TIMEOUT_SECONDS)"
            ),
        ],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert valid.returncode == 0
    assert valid.stdout.strip() == "240"

    environment["DETERMINFLOW_WORKFLOW_EXECUTOR_RECOVERY_TIMEOUT_SECONDS"] = "10"
    invalid = subprocess.run(
        [sys.executable, "-c", "import src.config"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert invalid.returncode != 0
    assert "必须在 30 到 900 秒之间" in invalid.stderr


def test_client_can_extend_only_one_recovery_request_timeout(monkeypatch) -> None:
    client = WorkflowExecutorClient.__new__(WorkflowExecutorClient)

    async def delayed_call(_operation, _arguments):
        await asyncio.sleep(0.03)
        return {"result": "ok"}

    monkeypatch.setattr(executor_client_module, "RPC_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(client, "_call", delayed_call)

    with pytest.raises(
        executor_client_module.ExecutorUnavailable,
        match="timed out",
    ):
        asyncio.run(client.call("recover_owned_tasks"))

    assert asyncio.run(
        client.call(
            "recover_owned_tasks",
            request_timeout_seconds=0.1,
        )
    ) == {"result": "ok"}
