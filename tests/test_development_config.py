import os
import subprocess

from src.development_config import prepare_development_config


def test_prepare_development_config_copies_only_missing_files(tmp_path, monkeypatch):
    project_root = tmp_path / "determinflow"
    defaults = project_root / "config"
    runtime = project_root / "data" / "dev-config"
    defaults.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (defaults / "agents_config.json").write_text("default", encoding="utf-8")
    (defaults / "models_config.json").write_text("local-secret", encoding="utf-8")
    (defaults / "extension-overrides").mkdir()
    (defaults / "extension-overrides" / "rules_config.json").write_text(
        "override",
        encoding="utf-8",
    )
    (runtime / "agents_config.json").write_text("custom", encoding="utf-8")
    monkeypatch.setenv("DETERMINFLOW_CONFIG_DIR", "./data/dev-config")
    monkeypatch.delenv(
        "DETERMINFLOW_DEVELOPMENT_MODEL_PROVIDER_SOURCE", raising=False,
    )

    created = prepare_development_config(project_root)

    assert (runtime / "agents_config.json").read_text(encoding="utf-8") == "custom"
    assert (runtime / "models_config.json").read_text(encoding="utf-8") == "local-secret"
    assert (
        runtime / "extension-overrides" / "rules_config.json"
    ).read_text(encoding="utf-8") == "override"
    assert created == [
        runtime / "extension-overrides" / "rules_config.json",
        runtime / "models_config.json",
    ]
    assert os.environ["DETERMINFLOW_CONFIG_DIR"] == str(runtime.resolve())


def test_prepare_development_config_does_nothing_without_override(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "determinflow"
    (project_root / "config").mkdir(parents=True)
    monkeypatch.delenv("DETERMINFLOW_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AI_COMPANY_CONFIG_DIR", raising=False)

    assert prepare_development_config(project_root) == []
    assert not (project_root / "data").exists()


def test_prepare_development_config_syncs_production_provider_catalog(
    tmp_path,
    monkeypatch,
):
    project_root = tmp_path / "determinflow"
    defaults = project_root / "config"
    runtime = project_root / "data" / "dev-config"
    defaults.mkdir(parents=True)
    (defaults / "models_config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DETERMINFLOW_CONFIG_DIR", str(runtime))
    monkeypatch.setenv(
        "DETERMINFLOW_DEVELOPMENT_MODEL_PROVIDER_SOURCE", "relay"
    )
    commands = []

    def record(command, *, check):
        commands.append((command, check))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("src.development_config.subprocess.run", record)

    prepare_development_config(project_root)

    generator = str(
        project_root
        / "scripts"
        / "production"
        / "production_model_providers.py"
    )
    config = str(runtime / "models_config.json")
    snapshot = str(runtime / "production-model-providers.json")
    assert commands == [
        (
            [
                os.sys.executable,
                generator,
                "sync-development",
                "--config",
                config,
                "--output",
                config,
                "--snapshot-output",
                snapshot,
                "--source-provider",
                "relay",
            ],
            True,
        ),
    ]
