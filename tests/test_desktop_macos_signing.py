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
