from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.extension_host.plugin_routes import require_plugin_write_access
from src.workspace.routes import router
from src.workspace.service import WorkspaceRuntimeService
from src.workspace.settings import WorkspaceSettingsStore


def test_settings_gate_and_durable_disable_during_outage(tmp_path):
    runtime = WorkspaceRuntimeService(settings_store=WorkspaceSettingsStore(tmp_path / "settings.json"))
    provider = SimpleNamespace(health=AsyncMock(return_value=True))
    runtime.attach(providers={"storage": provider}, owner_status=lambda _: {"status": "running"})
    app = FastAPI()
    app.include_router(router)
    app.state.workspace_runtime = runtime
    app.dependency_overrides[require_plugin_write_access] = lambda: None
    client = TestClient(app)
    assert client.get("/api/workspace/settings").json()["settings"]["enabled"] is False
    assert client.put("/api/workspace/settings", json={"settings": {"enabled": True}}).status_code == 400
    saved = client.put("/api/workspace/settings", json={"settings": {"enabled": True, "provider_id": "storage"}})
    assert saved.status_code == 200 and saved.json()["effective_enabled"] is True
    provider.health.return_value = False
    assert client.put("/api/workspace/settings", json={"settings": {"context_token_budget": 3000}}).status_code == 400
    assert runtime.settings().context_token_budget == 2000
    disabled = client.put("/api/workspace/settings", json={"settings": {"enabled": False}})
    assert disabled.status_code == 200
    assert WorkspaceSettingsStore(tmp_path / "settings.json").load().enabled is False
    assert client.put("/api/workspace/settings", json={"settings": {"scope": "bad"}}).status_code == 422


def test_settings_write_requires_administration():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.put("/api/workspace/settings", json={"settings": {"enabled": True}}).status_code == 403
