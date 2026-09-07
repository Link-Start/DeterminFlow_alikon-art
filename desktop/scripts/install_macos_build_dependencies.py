"""Install desktop build dependencies from macOS 11 Apple Silicon wheels."""

from __future__ import annotations

import logging
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

LOGGER = logging.getLogger("desktop.install_macos_build_dependencies")
MACOS_WHEEL_PLATFORM = "macosx_11_0_arm64"
BUILD_TOOLS = ("pyinstaller==6.21.0", "pytest==9.1.1")


def build_macos_dependency_commands(
    repo_root: Path,
    wheelhouse: Path,
    *,
    python_executable: Path,
    python_version: str,
) -> tuple[list[str], list[str]]:
    packages = ["-r", str(repo_root / "requirements.lock"), *BUILD_TOOLS]
    pip = [str(python_executable), "-m", "pip"]
    download = [
        *pip,
        "download",
        "--platform",
        MACOS_WHEEL_PLATFORM,
        "--python-version",
        python_version,
        "--only-binary=:all:",
        "--dest",
        str(wheelhouse),
        *packages,
    ]
    install = [
        *pip,
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        *packages,
    ]
    return download, install


def install_macos_build_dependencies(repo_root: Path) -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise RuntimeError("macOS 桌面依赖只能在 Apple Silicon macOS 上安装")
    requirements = repo_root / "requirements.lock"
    if not requirements.is_file():
        raise RuntimeError(f"缺少运行依赖锁: {requirements}")

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    with tempfile.TemporaryDirectory(prefix="determinflow-macos11-wheels-") as raw_dir:
        wheelhouse = Path(raw_dir)
        download, install = build_macos_dependency_commands(
            repo_root,
            wheelhouse,
            python_executable=Path(sys.executable),
            python_version=python_version,
        )
        subprocess.run(download, check=True)
        subprocess.run(install, check=True)
    LOGGER.info("macOS 11 Apple Silicon 桌面构建依赖安装完成")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    install_macos_build_dependencies(repo_root)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
