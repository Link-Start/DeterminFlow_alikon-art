import json
from pathlib import Path
import os
import subprocess
import sys

import pytest

from src.core import default_resources
from src.core.default_resources import DEFAULT_RESOURCES_DIR, provision_core_skills


def _write_minimal_workflow_definition(directory: Path) -> Path:
    workflow_dir = directory / "core-validator-fixture"
    workflow_dir.mkdir(parents=True)
    definition = workflow_dir / "definition.json"
    definition.write_text(
        (
            '{"workflow_id":"core-validator-fixture","name":"Core Validator Fixture",'
            '"nodes":[],"edges":[]}'
        ),
        encoding="utf-8",
    )
    return definition


def test_provision_core_skills_copies_bundled_skill(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"

    created = provision_core_skills(skills_dir)

    target = skills_dir / "workflow-guide" / "SKILL.md"
    source = DEFAULT_RESOURCES_DIR / "skills" / "workflow-guide" / "SKILL.md"
    assert target in created
    assert target.read_bytes() == source.read_bytes()


def test_provision_flushes_through_a_writable_descriptor(tmp_path, monkeypatch):
    original_fsync = os.fsync
    flushed = []

    def require_writable_descriptor(fd):
        # Windows FlushFileBuffers requires write access. A zero-byte write
        # checks that property on every platform without changing the file.
        os.write(fd, b"")
        original_fsync(fd)
        flushed.append(fd)

    monkeypatch.setattr(default_resources.os, "fsync", require_writable_descriptor)
    created = provision_core_skills(tmp_path / "skills")
    assert created
    assert len(flushed) == len(created)


def test_provision_core_skills_overwrites_managed_runtime_copy(tmp_path: Path) -> None:
    target = tmp_path / "skills" / "workflow-guide" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("customized", encoding="utf-8")

    created = provision_core_skills(tmp_path / "skills")

    helper = tmp_path / "skills" / "workflow-guide" / "scripts" / "validate_definition.py"
    helper_source = (
        DEFAULT_RESOURCES_DIR
        / "skills"
        / "workflow-guide"
        / "scripts"
        / "validate_definition.py"
    )
    assert target in created
    assert helper in created
    assert helper.read_bytes() == helper_source.read_bytes()
    assert target.read_bytes() == (
        DEFAULT_RESOURCES_DIR / "skills" / "workflow-guide" / "SKILL.md"
    ).read_bytes()


def test_provision_core_skills_updates_unmodified_owned_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults_dir = tmp_path / "defaults"
    source = defaults_dir / "skills" / "example" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("version two", encoding="utf-8")
    target_dir = tmp_path / "installed-skills"
    target = target_dir / "example" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("version one", encoding="utf-8")
    old_hash = default_resources._file_hash(target)
    (target_dir / default_resources.CORE_RESOURCE_MARKER).write_text(
        '{"files":{"example/SKILL.md":{"installed_hash":"' + old_hash + '"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(default_resources, "DEFAULT_RESOURCES_DIR", defaults_dir)

    synchronized = provision_core_skills(target_dir)

    assert synchronized == [target]
    assert target.read_text(encoding="utf-8") == "version two"


def test_provision_core_skills_replaces_drift_and_records_current_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults_dir = tmp_path / "defaults"
    source = defaults_dir / "skills" / "example" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("version two", encoding="utf-8")
    target_dir = tmp_path / "installed-skills"
    target = target_dir / "example" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("local customization", encoding="utf-8")
    old_hash = "a" * 64
    marker = target_dir / default_resources.CORE_RESOURCE_MARKER
    marker.write_text(
        '{"files":{"example/SKILL.md":{"installed_hash":"' + old_hash + '"}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(default_resources, "DEFAULT_RESOURCES_DIR", defaults_dir)

    synchronized = provision_core_skills(target_dir)

    saved_marker = json.loads(marker.read_text(encoding="utf-8"))
    assert synchronized == [target]
    assert target.read_text(encoding="utf-8") == "version two"
    assert saved_marker["files"]["example/SKILL.md"]["installed_hash"] == (
        default_resources._file_hash(source)
    )


def test_provision_core_skills_removes_unmanaged_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults_dir = tmp_path / "defaults"
    source = defaults_dir / "skills" / "example" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("new bundled version", encoding="utf-8")
    target_dir = tmp_path / "installed-skills"
    target = target_dir / "example" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("new bundled version", encoding="utf-8")
    unmanaged = target_dir / "example" / "notes.txt"
    unmanaged.write_text("not part of Core", encoding="utf-8")
    monkeypatch.setattr(default_resources, "DEFAULT_RESOURCES_DIR", defaults_dir)

    synchronized = provision_core_skills(target_dir)

    assert synchronized == []
    assert target.read_text(encoding="utf-8") == "new bundled version"
    assert not unmanaged.exists()


def test_provision_core_skills_ignores_python_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults_dir = tmp_path / "defaults"
    skill_file = defaults_dir / "skills" / "example" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("example", encoding="utf-8")
    cache_file = defaults_dir / "skills" / "example" / "__pycache__" / "generated.pyc"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"generated")
    monkeypatch.setattr(default_resources, "DEFAULT_RESOURCES_DIR", defaults_dir)

    created = provision_core_skills(tmp_path / "installed-skills")

    assert len(created) == 1
    assert not any("__pycache__" in path.parts for path in created)


def test_provision_core_skills_removes_runtime_python_cache(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    provision_core_skills(skills_dir)
    cache = (
        skills_dir
        / "workflow-guide"
        / "scripts"
        / "__pycache__"
        / "validate_definition.cpython-311.pyc"
    )
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"runtime-cache")

    provision_core_skills(skills_dir)

    assert not cache.exists()


def test_provisioned_workflow_validator_runs_from_data_layout(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    isolated_repo = tmp_path / "repo"
    (isolated_repo / "data").mkdir(parents=True)
    os.symlink(repo_root / "src", isolated_repo / "src", target_is_directory=True)
    provision_core_skills(isolated_repo / "data" / "skills" / "builtin")
    validator = (
        isolated_repo
        / "data"
        / "skills"
        / "builtin"
        / "workflow-guide"
        / "scripts"
        / "validate_definition.py"
    )
    definition = _write_minimal_workflow_definition(tmp_path)

    result = subprocess.run(
        [sys.executable, str(validator), str(definition)],
        cwd=isolated_repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS]" in result.stdout


def test_provisioned_workflow_validator_supports_external_data_dir(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    external_skills = tmp_path / "external-data" / "skills" / "builtin"
    provision_core_skills(external_skills)
    validator = (
        external_skills
        / "workflow-guide"
        / "scripts"
        / "validate_definition.py"
    )
    definition = _write_minimal_workflow_definition(tmp_path)

    result = subprocess.run(
        [sys.executable, str(validator), str(definition)],
        cwd=repo_root,
        env={**os.environ, "AI_COMPANY_ROOT": str(repo_root)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS]" in result.stdout


def test_workflow_validator_does_not_import_from_untrusted_cwd(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    validator = (
        repo_root
        / "src"
        / "core"
        / "defaults"
        / "skills"
        / "workflow-guide"
        / "scripts"
        / "validate_definition.py"
    )
    definition = _write_minimal_workflow_definition(tmp_path)
    marker = tmp_path / "imported-from-cwd"
    fake_module = tmp_path / "src" / "workflow" / "definition.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('unsafe')\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(validator), str(definition)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[PASS]" in result.stdout
    assert not marker.exists()
