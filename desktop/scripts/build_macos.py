"""Build the app, seal final resource copies, then create its candidate DMG."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from desktop.scripts.sign_macos_backend import sign_macos_backend
from desktop.scripts.verify_bundle import verify_macos_app_bundle


def seal_app(app: Path) -> None:
    sign_macos_backend(app / "Contents" / "Resources" / "runtime" / "backend")
    # All nested Mach-O files are already signed. --deep would re-sign Python
    # framework aliases again and invalidate the individually sealed copies.
    subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(app)], check=True)
    verify_macos_app_bundle(app, verify_signatures=True)


def build_macos(desktop: Path) -> Path:
    subprocess.run(["npm", "exec", "--", "tauri", "build", "--bundles", "app"], cwd=desktop, check=True)
    bundle = desktop / "src-tauri" / "target" / "release" / "bundle"
    app = bundle / "macos" / "DeterminFlow.app"
    seal_app(app)
    version = json.loads((desktop / "src-tauri" / "tauri.conf.json").read_text())["version"]
    dmg = bundle / "dmg" / f"DeterminFlow_{version}_aarch64.dmg"
    dmg.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="df-dmg-") as directory:
        staging = Path(directory)
        subprocess.run(["ditto", str(app), str(staging / app.name)], check=True)
        (staging / "Applications").symlink_to("/Applications")
        subprocess.run([
            "hdiutil", "create", "-volname", "DeterminFlow", "-srcfolder", str(staging),
            "-format", "UDZO", "-ov", str(dmg),
        ], check=True)
    return dmg


if __name__ == "__main__":
    if sys.platform != "darwin":
        raise SystemExit("macOS packaging requires macOS")
    build_macos(Path(__file__).resolve().parents[1])
