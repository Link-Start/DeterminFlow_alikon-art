from __future__ import annotations

import asyncio
from dataclasses import replace
import pytest

from src.memory.provider_status import probe_provider_health
from src.memory.settings import MemorySettingsStore
from tests.test_memory_settings import (
    patch_agents, _HealthProvider, _FakeManagement, _running_record,
    _service, _store, _persist, _client,
)
from tests.test_memory_jobs import _snapshot
from tests.test_memory_runtime import FakeExtractRunner, FakeProvider, SCOPE_A, _session


def test_health_is_bounded_and_rejects_non_boolean_success():
    class Slow:
        async def health(self):
            await asyncio.sleep(1)
            return True, ""
    class Bad:
        async def health(self):
            return "false", ""
    class Sync:
        def health(self):
            raise AssertionError("sync health must never block the event loop")
    async def scenario():
        assert (await probe_provider_health(Slow(), timeout=0.01))[0] is False
        assert (await probe_provider_health(Bad()))[0] is False
        assert (await probe_provider_health(Sync()))[0] is False
    asyncio.run(scenario())


def test_pending_config_rejects_enable_and_health_is_truthful(tmp_path):
    provider = _HealthProvider()
    service = _service(tmp_path, provider, store=_store(tmp_path))
    management = _FakeManagement({**_running_record(), "restart_required": True})
    client = _client(service, management)
    response = client.put("/api/memory/settings", json={"settings": {"enabled": True, "external_enabled": True}})
    assert response.status_code == 400
    assert "重启" in response.json()["detail"]
    assert client.put("/api/memory/settings", json={"settings": {"enabled": False}}).status_code == 200
    management.record["restart_required"] = False
    _persist(service)
    provider._healthy = False
    payload = client.get("/api/memory/settings").json()
    assert payload["effective_enabled"] is False
    assert payload["providers"][0]["healthy"] is False
    from src.extension_host.plugin_config import _validate_schema
    _validate_schema(payload["schema"])


def test_invalid_settings_do_not_allow_default_overwrite(tmp_path):
    path = tmp_path / "memory_settings.json"
    path.write_text("broken-json")
    service = _service(tmp_path, _HealthProvider(), store=MemorySettingsStore(path))
    client = _client(service, _FakeManagement(_running_record()))
    assert client.get("/api/memory/settings").status_code == 503
    assert client.put("/api/memory/settings", json={"settings": {"enabled": False}}).status_code == 503
    assert path.read_text() == "broken-json"
    assert service.running_providers() == {}


@pytest.mark.parametrize("disabled_field", ["enabled", "external_enabled", "auto_consolidate_enabled"])
def test_disable_during_extract_preserves_facts_without_new_writes(tmp_path, patch_agents, disabled_field):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class PausedExtract(FakeExtractRunner):
            async def extract(self, request):
                started.set()
                await release.wait()
                return await super().extract(request)
        provider = FakeProvider()
        service = _service(tmp_path, provider, store=_store(tmp_path))
        service.attach(extract_runner=PausedExtract())
        _persist(service)
        await _snapshot(service, _session(), "已确认的事实")
        task = asyncio.create_task(service.process_due_jobs(force=True))
        await asyncio.wait_for(started.wait(), 2)
        service._settings_store.save(replace(service.resolved_memory_settings(), **{disabled_field: False}))
        release.set()
        await asyncio.wait_for(task, 2)
        assert provider.retains == []
        ledger = service.store.load("sess-1")
        assert ledger["turns"]
        assert ledger["job"]["frozen_facts"]
        assert ledger["job"]["status"] != "completed"
    asyncio.run(scenario())


def test_disable_during_auto_recall_drops_late_injection(tmp_path, patch_agents):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class PausedRecall(FakeProvider):
            async def recall(self, request):
                started.set()
                await release.wait()
                return await super().recall(request)
        provider = PausedRecall()
        service = _service(tmp_path, provider, store=_store(tmp_path))
        _persist(service)
        task = asyncio.create_task(service.prepare_turn_model_context(session=_session(), content="回忆事实", source="human",
            invocation_context={"memory_scope": SCOPE_A}, model_context={"locale": "zh-CN"}))
        await asyncio.wait_for(started.wait(), 2)
        _persist(service, enabled=False)
        release.set()
        assert await asyncio.wait_for(task, 2) == {"locale": "zh-CN"}
    asyncio.run(scenario())


def test_migration_waits_until_plugin_loaded_saved_configuration(tmp_path):
    store = _store(tmp_path)
    provider = _HealthProvider(legacy={"extract_model": "constructor-default"})
    service = _service(tmp_path, provider, store=store, status="loaded")
    assert not store.path.exists()
    provider._legacy = {"extract_model": "saved-model", "recall_mode": "first"}
    service.attach(owner_status=lambda owner: {"status": "running"})
    settings = service.resolved_memory_settings()
    assert settings.extract_model == "saved-model"
    assert settings.recall_mode == "first"


def test_upgrade_from_adapter_without_migration_method_preserves_policy(tmp_path):
    from tests.test_memory_runtime import _policy
    provider = FakeProvider(_policy(extract_model="existing-model", recall_mode="first", auto_recall_enabled=False))
    service = _service(tmp_path, provider, store=_store(tmp_path))
    settings = service.resolved_memory_settings()
    assert settings.extract_model == "existing-model"
    assert settings.recall_mode == "first"
    assert settings.auto_recall_enabled is False
