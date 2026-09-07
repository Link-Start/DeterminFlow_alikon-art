import subprocess
from pathlib import Path

import pytest

from desktop.scripts.sign_macos_backend import sign_macos_backend


def test_signs_actual_macho_files_before_copy_not_data_or_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "Python"
    binary.write_bytes(b"\xcf\xfa\xed\xfe" + b"runtime")
    (tmp_path / "alias").symlink_to(binary)
    (tmp_path / "config.json").write_text("{}")
    calls = []
    def run(command, *, check):
        assert check
        calls.append(command)
    monkeypatch.setattr("desktop.scripts.sign_macos_backend.subprocess.run", run)
    sign_macos_backend(tmp_path)
    assert calls == [
        ["codesign", "--force", "--sign", "-", "--timestamp=none", str(binary)],
        ["codesign", "--verify", "--strict", str(binary)],
    ]


def test_signing_failure_stops_packaging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "backend").write_bytes(b"\xcf\xfa\xed\xfe")
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr("desktop.scripts.sign_macos_backend.subprocess.run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        sign_macos_backend(tmp_path)


def test_final_app_seals_resources_before_envelope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from desktop.scripts import build_macos
    events = []
    monkeypatch.setattr(build_macos, "sign_macos_backend", lambda path: events.append(("nested", path)))
    monkeypatch.setattr(build_macos.subprocess, "run", lambda cmd, **kw: events.append(("outer", cmd)))
    monkeypatch.setattr(build_macos, "verify_macos_app_bundle", lambda app, **kw: events.append(("verify", kw)))
    build_macos.seal_app(tmp_path)
    assert events[0] == ("nested", tmp_path / "Contents/Resources/runtime/backend")
    assert events[1][0] == "outer"
    assert "--deep" not in events[1][1]
    assert events[2] == ("verify", {"verify_signatures": True})


def test_invalid_app_never_reaches_dmg_creation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from desktop.scripts import build_macos
    calls = []
    monkeypatch.setattr(build_macos.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    def fail(app):
        raise RuntimeError("signature verification failed")
    monkeypatch.setattr(build_macos, "seal_app", fail)
    with pytest.raises(RuntimeError, match="signature verification"):
        build_macos.build_macos(tmp_path)
    assert len(calls) == 1
    assert calls[0][-2:] == ["--bundles", "app"]


@pytest.mark.parametrize("flavor,suffix", [("core", ""), ("full", "-full")])
def test_dmg_flavors_have_distinct_release_names(monkeypatch, tmp_path, flavor, suffix):
    from desktop.scripts import build_macos
    config = tmp_path / "src-tauri/tauri.conf.json"
    config.parent.mkdir()
    config.write_text('{"version":"1.1.0"}')
    monkeypatch.setattr(build_macos, "seal_app", lambda app: None)
    calls = []
    monkeypatch.setattr(build_macos.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    dmg = build_macos.build_macos(tmp_path, flavor=flavor)
    assert dmg.name == f"DeterminFlow_1.1.0_aarch64{suffix}.dmg"
    assert calls[-1][-1] == str(dmg)
