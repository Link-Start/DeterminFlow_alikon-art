"""Seal frozen Mach-O files at their final paths inside the application."""

from __future__ import annotations

import subprocess
from pathlib import Path


MACHO_MAGICS = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def sign_macos_backend(backend: Path) -> None:
    # Tauri dereferences Python framework aliases. Sign the final copies,
    # deepest first, so each file has the correct local resource envelope.
    for path in sorted(backend.rglob("*"), key=lambda item: (-len(item.parts), str(item))):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            magic = stream.read(4)
        if magic not in MACHO_MAGICS:
            continue
        subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(path)], check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(path)], check=True)
