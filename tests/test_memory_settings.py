from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.memory.contracts import MEMORY_CONTEXT_KEY, MemoryUnavailableError
from src.memory.service import MemoryRuntimeService
from src.memory.settings import (
    MemorySettingsStore,
    default_memory_settings,
    parse_memory_settings,
    read_legacy_runtime_settings,
)
from src.session.context import set_session_context
from src.settings.routes import router
from tests.test_memory_jobs import _snapshot
from tests.test_memory_runtime import (
    SCOPE_A,
    FakeAuthorizer,
    FakeExtractRunner,
    FakeProvider,
    _agent,
    _policy,
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


class _HealthProvider(FakeProvider):
    def __init__(
        self,
        policy=None,
        *,
        healthy: bool = True,
        reason: str = "ok",
        legacy: dict | None = None,
        expose_health: bool = True,
    ):
        super().__init__(policy)
        self._healthy = healthy
        self._reason = reason
        self._legacy = legacy or {}
        if expose_health:
            self.health = self._health

    async def _health(self):
        return self._healthy, self._reason

    def legacy_runtime_settings(self):
        return dict(self._legacy)


class _FakeManagement:
    def __init__(self, record=None):
        self.record = record

    def get_record(self, plugin_id):
        if self.record and self.record.get("id") == plugin_id:
            return self.record
        raise KeyError(plugin_id)

    def iter_settings_section_manifests(self):
        return []


def _running_record(plugin_id: str = "mem") -> dict:
    return {
        "id": plugin_id,
        "name": "Demo Memory",
        "runtime_status": "running",
        "active_enabled": True,
        "desired_enabled": True,
        "pending_action": None,
    }


def _store(tmp_path) -> MemorySettingsStore:
    return MemorySettingsStore(tmp_path / "memory_settings.json")


def _service(tmp_path, provider, store=None, status="running"):
    service = MemoryRuntimeService(
        tmp_path / "memory",
        extract_runner=FakeExtractRunner(),
        worker_id="worker-1",
        settings_store=store or MemorySettingsStore(),
    )
    states = {"mem": {"status": status}, "product": {"status": "running"}}
    service.attach(
        authorizers={"product": FakeAuthorizer()},
        providers={"mem": provider},
        owner_status=lambda owner: states.get(owner, {"status": "missing"}),
    )
    return service


def _persist(service: MemoryRuntimeService, **overrides):
    values = default_memory_settings().to_dict()
    values.update(
        enabled=True,
        external_enabled=True,
        provider_id="mem",
    )
    values.update(overrides)
    return service._settings_store.save(parse_memory_settings(values))


def _app(runtime, management=None) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.state.extension_manager = SimpleNamespace(
        plugin_management=management,
    )
    application.state.memory_runtime = runtime
    return application


def _client(runtime, management=None, *, loopback: bool = True) -> TestClient:
    app = _app(runtime, management)
    if loopback:
        return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    return TestClient(app)


def test_memory_settings_validate_ranges_and_reject_unknown_keys() -> None:
    with pytest.raises(ValueError, match="recall_timeout_seconds"):
        parse_memory_settings({"recall_timeout_seconds": 0})
    with pytest.raises(ValueError, match="max_concurrent_jobs"):
        parse_memory_settings({"max_concurrent_jobs": 9})
    with pytest.raises(ValueError, match="未知字段"):
        parse_memory_settings({"auto_recall_enabled": True, "secret": 1})
    parsed = parse_memory_settings({"recall_mode": "first", "extract_model": ""})
    assert parsed.recall_mode == "first"
    assert parsed.extract_model == ""


def test_legacy_runtime_settings_copies_only_generic_keys() -> None:
    provider = _HealthProvider(
        legacy={
            "auto_recall_enabled": False,
            "max_batch_turns": 4,
            "enabled": False,
            "provider_id": "should-ignore",
            "recall_timeout_seconds": 0,
        }
    )

    copied = read_legacy_runtime_settings(provider)

    assert copied == {
        "auto_recall_enabled": False,
        "max_batch_turns": 4,
    }


def test_one_time_legacy_migration_is_authoritative(tmp_path) -> None:
    store = _store(tmp_path)
    provider = _HealthProvider(
        legacy={"recall_timeout_seconds": 1.5, "max_batch_turns": 4}
    )

    first = store.migrate_from_providers({"mem": provider})
    assert first is not None
    assert first.provider_id == "mem"
    assert first.external_enabled is True
    assert first.recall_timeout_seconds == 1.5
    assert first.max_batch_turns == 4

    provider._legacy = {"recall_timeout_seconds": 9, "max_batch_turns": 1}
    second = store.migrate_from_providers({"mem": provider})
    assert second == first
    document = json.loads(
        (tmp_path / "memory_settings.json").read_text(encoding="utf-8")
    )
    on_disk = parse_memory_settings(document["settings"], unknown="ignore")
    assert on_disk.recall_timeout_seconds == 1.5
    assert on_disk.max_batch_turns == 4


def test_unpersisted_runtime_keeps_provider_policy(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(_policy(recall_timeout_seconds=0.05))
        provider.delay = 0.2
        service = _service(tmp_path, provider)
        original = {"keep": True}
        timed_out = await service.prepare_turn_model_context(
            session=_session(),
            content="需要长期记住的事实",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert timed_out == original

    asyncio.run(scenario())


def test_persisted_core_settings_gate_recall_tools_and_jobs(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _service(tmp_path, provider, store=_store(tmp_path))
        _persist(service, enabled=False, external_enabled=True, provider_id="mem")
        session = _session()
        original = {"keep": True}
        recalled = await service.prepare_turn_model_context(
            session=session,
            content="我决定用模块化方案",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert recalled == original
        assert provider.recalls == []

        set_session_context(
            session_id="sess-1",
            agent_type="page-assistant",
            resource_owner="product",
            external_ref="ext-1",
            lifecycle_profile="detached_conversation",
            invocation_context={"memory_scope": SCOPE_A},
        )
        with pytest.raises(MemoryUnavailableError):
            await service.tool_recall("x")

        await _snapshot(service, session, "关闭后不能整理")
        await service.process_due_jobs(force=True)
        assert provider.retains == []
        assert service.store.load("sess-1") is None

        _persist(service, enabled=True, external_enabled=True, provider_id="mem")
        recalled = await service.prepare_turn_model_context(
            session=session,
            content="我决定用模块化方案",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context={"locale": "zh-CN"},
        )
        assert recalled[MEMORY_CONTEXT_KEY]["items"][0]["text"].startswith("fact-for:")

    asyncio.run(scenario())


def test_persisted_core_timeout_overlays_provider_policy(
    tmp_path, patch_agents
) -> None:
    async def scenario() -> None:
        provider = FakeProvider(_policy(recall_timeout_seconds=30))
        provider.delay = 0.3
        service = _service(tmp_path, provider, store=_store(tmp_path))
        _persist(service, recall_timeout_seconds=0.1)
        original = {"keep": True}
        timed_out = await service.prepare_turn_model_context(
            session=_session(),
            content="需要长期记住的事实",
            source="human",
            invocation_context={"memory_scope": SCOPE_A},
            model_context=original,
        )
        assert timed_out == original

    asyncio.run(scenario())


def test_auto_consolidate_off_does_not_claim_jobs(tmp_path, patch_agents) -> None:
    async def scenario() -> None:
        provider = FakeProvider(
            _policy(consolidate_length_chars=1, consolidate_idle_seconds=0)
        )
        service = _service(tmp_path, provider, store=_store(tmp_path))
        _persist(service, auto_consolidate_enabled=False)
        session = _session()
        await _snapshot(service, session, "不应抽取")
        processed = await service.process_due_jobs(force=False)
        assert processed == 0
        assert provider.retains == []
        ledger = service.store.load("sess-1")
        assert ledger is not None
        assert not ledger.get("job")

    asyncio.run(scenario())


def test_memory_settings_http_get_put_health_gate_and_write_access(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _HealthProvider()
    service = _service(tmp_path, provider, store=_store(tmp_path))
    management = _FakeManagement(_running_record())
    loopback = _client(service, management, loopback=True)

    fetched = loopback.get("/api/memory/settings")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["settings"]["provider_id"] == "mem"
    assert body["settings"]["external_enabled"] is True
    assert body["providers"][0]["id"] == "mem"
    assert body["providers"][0]["healthy"] is True
    assert "enabled" in body["schema"]["properties"]

    closed = loopback.put(
        "/api/memory/settings",
        json={"settings": {"enabled": False}},
    )
    assert closed.status_code == 200
    assert closed.json()["settings"]["enabled"] is False
    assert closed.json()["effective_enabled"] is False

    monkeypatch.delenv("DETERMINFLOW_PLUGIN_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("AI_COMPANY_PLUGIN_ADMIN_TOKEN", raising=False)
    remote = _client(service, management, loopback=False)
    denied = remote.put(
        "/api/memory/settings",
        json={"settings": {"enabled": True}},
    )
    assert denied.status_code == 403

    unhealthy = _HealthProvider(healthy=False, reason="upstream down")
    failed = _service(tmp_path / "failed", unhealthy, store=_store(tmp_path / "failed"))
    failed_client = _client(
        failed,
        _FakeManagement({**_running_record(), "runtime_status": "degraded"}),
        loopback=True,
    )
    still_closeable = failed_client.put(
        "/api/memory/settings",
        json={"settings": {"enabled": False, "external_enabled": False}},
    )
    assert still_closeable.status_code == 200
    blocked = failed_client.put(
        "/api/memory/settings",
        json={
            "settings": {
                "enabled": True,
                "external_enabled": True,
                "provider_id": "mem",
            }
        },
    )
    assert blocked.status_code == 400
    assert "未运行" in blocked.json()["detail"] or "health" in blocked.json()["detail"]

    missing_health = FakeProvider()
    missing = _service(
        tmp_path / "no-health",
        missing_health,
        store=_store(tmp_path / "no-health"),
    )
    missing_client = _client(missing, _FakeManagement(_running_record()), loopback=True)
    cannot_enable = missing_client.put(
        "/api/memory/settings",
        json={
            "settings": {
                "enabled": True,
                "external_enabled": True,
                "provider_id": "mem",
            }
        },
    )
    assert cannot_enable.status_code == 400
    assert "health()" in cannot_enable.json()["detail"]

    staged = _client(
        service,
        _FakeManagement({**_running_record(), "desired_enabled": False}),
        loopback=True,
    )
    staged_disable = staged.put(
        "/api/memory/settings",
        json={
            "settings": {
                "enabled": True,
                "external_enabled": True,
                "provider_id": "mem",
            }
        },
    )
    assert staged_disable.status_code == 400
    assert "停用" in staged_disable.json()["detail"]

    enabled = loopback.put(
        "/api/memory/settings",
        json={
            "settings": {
                "enabled": True,
                "external_enabled": True,
                "provider_id": "mem",
                "recall_mode": "first",
            }
        },
    )
    assert enabled.status_code == 200
    assert enabled.json()["settings"]["recall_mode"] == "first"
    assert enabled.json()["effective_enabled"] is True
