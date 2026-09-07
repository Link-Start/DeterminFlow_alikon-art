from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from desktop.scripts import official_plugin_lock as plugin_lock_module
from desktop.scripts import stage_defaults as defaults_module
from src.extension_host.source_config import PluginSourceConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_official_plugin_lock_fixture(
    repo_root: Path,
    *,
    desktop_version: str = "1.0.10",
) -> dict:
    tauri = repo_root / "desktop" / "src-tauri" / "tauri.conf.json"
    tauri.parent.mkdir(parents=True, exist_ok=True)
    tauri.write_text(json.dumps({"version": "1.0.10"}), encoding="utf-8")
    lock = {
        "schema_version": 1,
        "desktop_version": desktop_version,
        "source": {
            "id": "determinflow-official",
            "url": "https://github.com/alikon-art/DeterminFlow-Plugins.git",
            "ref": "main",
            "commit": "a" * 40,
        },
        "plugins": [
            {
                "id": "bishu-novel",
                "version": "0.2.2",
                "subdirectory": "plugins/bishu-novel",
            },
            {
                "id": "public-api",
                "version": "0.1.33",
                "subdirectory": "plugins/public-api",
            },
        ],
    }
    lock_path = repo_root / plugin_lock_module.LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return lock


def test_full_plugin_lock_is_bound_to_desktop_version(tmp_path: Path) -> None:
    expected = _write_official_plugin_lock_fixture(tmp_path)

    assert plugin_lock_module.load_official_plugin_lock(tmp_path) == expected

    _write_official_plugin_lock_fixture(tmp_path, desktop_version="1.0.9")
    with pytest.raises(RuntimeError, match="桌面版本与"):
        plugin_lock_module.load_official_plugin_lock(tmp_path)


def test_full_plugin_catalog_must_match_the_exact_build_lock(
    tmp_path: Path,
) -> None:
    lock = _write_official_plugin_lock_fixture(tmp_path)
    source = PluginSourceConfig(
        id="determinflow-official",
        name="DeterminFlow Official Plugins",
        url=lock["source"]["url"],
        ref="main",
        mirrors=("https://gitee.com/alikon/DeterminFlow-Plugins.git",),
    )
    pinned = plugin_lock_module.pin_official_sources((source,), lock)

    assert pinned[0].ref == "a" * 40
    assert pinned[0].url == source.url
    catalog = {
        "sources": [
            {
                "id": source.id,
                "name": source.name,
                "error": "",
                "ref": "a" * 40,
                "resolved_commit": "a" * 40,
            }
        ],
        "plugins": [
            {
                **plugin,
                "source_id": source.id,
                "source": source.url,
                "ref": "a" * 40,
                "resolved_commit": "a" * 40,
            }
            for plugin in lock["plugins"]
        ],
    }
    entries = plugin_lock_module.validate_locked_catalog(catalog, lock)
    assert [entry["id"] for entry in entries] == ["bishu-novel", "public-api"]

    catalog["plugins"][1]["version"] = "0.1.34"
    with pytest.raises(RuntimeError, match="条目与构建锁不一致"):
        plugin_lock_module.validate_locked_catalog(catalog, lock)

    catalog["plugins"][1]["version"] = "0.1.33"
    catalog["plugins"][1]["ref"] = "main"
    with pytest.raises(RuntimeError, match="未锁定到构建锁 Commit"):
        plugin_lock_module.validate_locked_catalog(catalog, lock)


def test_full_plugin_lock_refresh_captures_latest_public_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_official_plugin_lock_fixture(tmp_path)
    source_file = tmp_path / "config" / "plugin-sources.json"
    source_file.parent.mkdir()
    source_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "official_sources": [
                    {
                        "id": "determinflow-official",
                        "name": "DeterminFlow Official Plugins",
                        "url": "https://github.com/alikon-art/DeterminFlow-Plugins.git",
                        "ref": "main",
                        "mirrors": ["https://gitee.com/alikon/DeterminFlow-Plugins.git"],
                        "registry": {
                            "url": "https://downloads.determinflow.com/plugins/v1",
                            "public_key": "C4oDxekhIr8Czlx0zpkRx46k26KK3d1T3HIZGsIxIr0=",
                        },
                    }
                ],
                "custom_sources": [],
            }
        ),
        encoding="utf-8",
    )
    commit = "b" * 40

    def fake_catalog(sources: tuple[PluginSourceConfig, ...]) -> dict:
        source = sources[0]
        assert source.registry is None
        assert source.mirrors == ()
        return {
            "sources": [
                {
                    "id": source.id,
                    "name": source.name,
                    "error": "",
                    "resolved_commit": commit,
                }
            ],
            "plugins": [
                {
                    "id": "public-api",
                    "version": "0.1.33",
                    "subdirectory": "plugins/public-api",
                    "source_id": source.id,
                    "resolved_commit": commit,
                }
            ],
        }

    monkeypatch.setattr(plugin_lock_module, "fetch_plugin_catalog", fake_catalog)

    refreshed = plugin_lock_module.resolve_latest_official_plugin_lock(
        tmp_path, source_file
    )

    assert refreshed["desktop_version"] == "1.0.10"
    assert refreshed["source"]["commit"] == commit
    assert refreshed["plugins"] == [
        {
            "id": "public-api",
            "version": "0.1.33",
            "subdirectory": "plugins/public-api",
        }
    ]
