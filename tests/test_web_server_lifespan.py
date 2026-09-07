from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src import web_server
from src.workflow.executor_pool import ExecutorLeaseGroup


class _LeaseAcquired(RuntimeError):
    pass


class _InlineLeases:
    def __init__(self) -> None:
        self.released = False

    def acquire(self, timeout_seconds: float) -> None:
        assert timeout_seconds == 60.0
        raise _LeaseAcquired

    def release(self) -> None:
        self.released = True


class _ExtensionManager:
    async def stop(self) -> None:
        pass


def test_inline_lifespan_acquires_executor_leases(monkeypatch: pytest.MonkeyPatch) -> None:
    leases = _InlineLeases()
    app = SimpleNamespace(
        state=SimpleNamespace(extension_manager=_ExtensionManager()),
    )

    monkeypatch.setattr(web_server, "setup_logging", lambda: None)
    monkeypatch.setattr(web_server, "ensure_dirs", lambda: None)
    monkeypatch.setattr(web_server, "WORKFLOW_EXECUTOR_MODE", "inline")
    monkeypatch.setattr(
        ExecutorLeaseGroup,
        "for_inline",
        classmethod(lambda cls, data_dir, configured_count: leases),
    )

    async def enter_lifespan() -> None:
        with pytest.raises(_LeaseAcquired):
            async with web_server.lifespan(app):
                pass

    asyncio.run(enter_lifespan())
    assert leases.released
