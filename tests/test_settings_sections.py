from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.extension_api.models import ExtensionManifest
from src.settings.catalog import (
    CORE_SECTION_IDS,
    list_settings_sections,
    plugin_settings_section,
)
from src.settings.routes import router


class _FakeManagement:
    def __init__(self, manifests=()):
        self._manifests = list(manifests)

    def iter_settings_section_manifests(self):
        return self._manifests

    def get_record(self, plugin_id):
        raise KeyError(plugin_id)


def _app(management=None) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.state.extension_manager = SimpleNamespace(
        plugin_management=management,
    )
    application.state.memory_runtime = None
    return application


def test_core_settings_sections_are_registered_in_contract_order() -> None:
    sections = list_settings_sections()
    assert [item["id"] for item in sections] == list(CORE_SECTION_IDS)
    assert {item["kind"] for item in sections} == {"core"}
    assert {item["owner"] for item in sections} == {"core"}
    for item in sections:
        assert item["title"]
        assert isinstance(item["order"], int)
        assert "plugin_id" not in item


def test_plugin_settings_section_uses_manifest_metadata_and_prefix() -> None:
    manifest = ExtensionManifest(
        extension_id="demo-memory",
        name="Demo Memory",
        version="1.0.0",
        description="Fallback",
        settings_schema="settings.schema.json",
        settings_title="Demo",
        settings_description="Connection and retrieval parameters",
        settings_order=90,
        settings_section_id="memory",
    )

    section = plugin_settings_section("demo-memory", manifest)

    assert section == {
        "id": "plugin:demo-memory:memory",
        "title": "Demo",
        "owner": "demo-memory",
        "kind": "plugin",
        "order": 90,
        "description": "Connection and retrieval parameters",
        "plugin_id": "demo-memory",
    }


def test_plugin_without_schema_does_not_register_a_section() -> None:
    manifest = ExtensionManifest(
        extension_id="demo",
        name="Demo",
        version="1.0.0",
        settings_title="Ignored",
    )
    assert plugin_settings_section("demo", manifest) is None


def test_disabled_plugin_section_is_listed_and_does_not_collide_with_core() -> None:
    manifest = ExtensionManifest(
        extension_id="demo-memory",
        name="Demo Memory",
        version="1.0.0",
        settings_schema="settings.schema.json",
        settings_section_id="memory",
        settings_order=90,
    )
    sections = list_settings_sections(
        [plugin_settings_section("demo-memory", manifest)]
    )
    ids = [item["id"] for item in sections]
    assert "memory" in ids
    assert "plugin:demo-memory:memory" in ids
    plugin = next(item for item in sections if item["kind"] == "plugin")
    assert plugin["id"] != "memory"
    assert plugin["plugin_id"] == "demo-memory"


def test_settings_sections_http_includes_installed_plugin_descriptors() -> None:
    manifest = ExtensionManifest(
        extension_id="demo-plugin",
        name="Demo Plugin",
        version="1.0.0",
        description="Plugin fallback",
        settings_schema="settings.schema.json",
        settings_title="Demo",
        settings_order=90,
        settings_section_id="memory",
    )
    client = TestClient(
        _app(_FakeManagement([("demo-plugin", manifest)])),
        base_url="http://127.0.0.1",
        client=("127.0.0.1", 50000),
    )

    response = client.get("/api/settings/sections")

    assert response.status_code == 200
    payload = response.json()
    plugin = next(item for item in payload["sections"] if item["kind"] == "plugin")
    assert plugin["id"] == "plugin:demo-plugin:memory"
    assert plugin["title"] == "Demo"
    assert plugin["owner"] == "demo-plugin"
    assert plugin["plugin_id"] == "demo-plugin"
    assert [item["id"] for item in payload["sections"] if item["kind"] == "core"] == (
        list(CORE_SECTION_IDS)
    )
