"""Verify desktop runtime and optional Windows/macOS bundle output."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from desktop.scripts.stage_defaults import SENSITIVE_KEYS
from src.plugin_system.release import load_release_plugin
from src.plugin_system.store import PluginStore

LOGGER = logging.getLogger("desktop.verify_bundle")
WINDOWS_GUI_SUBSYSTEM = 2
MACHO_MAGIC_64 = b"\xcf\xfa\xed\xfe"
MACHO_CIGAM_64 = b"\xfe\xed\xfa\xcf"
FAT_MAGICS = {
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
}
CPU_TYPE_ARM64 = 0x0100000C
MINIMUM_MACOS_VERSION = "11.0"


def _inspect_secrets(value: Any, location: str) -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}"
            if (
                key.lower() in SENSITIVE_KEYS
                and isinstance(child, str)
                and child
                and not (child.startswith("${") and child.endswith("}"))
            ):
                findings.append(child_location)
            findings.extend(_inspect_secrets(child, child_location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_inspect_secrets(child, f"{location}[{index}]"))
    return findings


def verify_defaults(config_dir: Path) -> None:
    required = {
        "extensions.json",
        "mcp_servers.json",
        "models_config.example.json",
        "models_config.json",
        "plugin-sources.json",
    }
    names = {path.name for path in config_dir.glob("*.json")}
    missing = required - names
    if missing:
        raise RuntimeError(f"桌面默认配置缺失: {', '.join(sorted(missing))}")

    findings: list[str] = []
    combined = ""
    for path in sorted(config_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        findings.extend(_inspect_secrets(payload, path.name))
        combined += path.read_text(encoding="utf-8")
    if findings:
        raise RuntimeError(f"桌面默认配置包含明文凭据: {', '.join(findings)}")
    forbidden = ("ssh://git@localhost", "AI Company Core")
    leaked = [item for item in forbidden if item in combined]
    if leaked:
        raise RuntimeError(f"桌面默认配置包含私有边界内容: {', '.join(leaked)}")


def verify_bundled_plugins(snapshot_dir: Path) -> list[str]:
    if not snapshot_dir.is_dir():
        raise RuntimeError(f"桌面 Full Plugin 快照不存在: {snapshot_dir}")
    metadata_path = snapshot_dir / "release-plugins.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        plugin_ids = sorted(metadata["plugins"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("桌面 Full Plugin 快照元数据无效") from error
    if not plugin_ids:
        raise RuntimeError("桌面 Full Plugin 快照不能为空")
    store = PluginStore(snapshot_dir)
    if sorted(store.read_lock()) != plugin_ids:
        raise RuntimeError("桌面 Full Plugin 快照锁与元数据不一致")
    for plugin_id in plugin_ids:
        store.verify(plugin_id)
        load_release_plugin(snapshot_dir, plugin_id)
    LOGGER.info("桌面 Full Plugin 快照验证通过: %s", ", ".join(plugin_ids))
    return plugin_ids


def verify_icns(path: Path) -> None:
    data = path.read_bytes()
    if data[:4] != b"icns" or len(data) < 1024:
        raise RuntimeError(f"macOS 图标不是有效的 ICNS: {path}")
    LOGGER.info("macOS ICNS 验证通过: %s", path)


def _read_prefix(path: Path, size: int) -> bytes:
    with path.open("rb") as source:
        return source.read(size)


def verify_macos_arm64_executable(executable: Path) -> None:
    image = _read_prefix(executable, 8)
    if len(image) < 8:
        raise RuntimeError(f"macOS 程序过短，无法校验架构: {executable}")
    magic = image[:4]
    if magic in FAT_MAGICS:
        raise RuntimeError(
            f"macOS 候选包必须是 Apple Silicon 单架构，不能是 universal: {executable}"
        )
    if magic == MACHO_MAGIC_64:
        cputype = int.from_bytes(image[4:8], "little")
    elif magic == MACHO_CIGAM_64:
        cputype = int.from_bytes(image[4:8], "big")
    else:
        raise RuntimeError(f"macOS 程序不是 Mach-O 64 可执行文件: {executable}")
    if cputype != CPU_TYPE_ARM64:
        raise RuntimeError(
            f"macOS 候选包必须是 arm64，实际 cputype={cputype:#x}: {executable}"
        )
    LOGGER.info("macOS arm64 Mach-O 验证通过: %s", executable)


def _version_tuple(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as error:
        raise RuntimeError(f"无效的 macOS 最低版本: {value}") from error


def _macho_deployment_target(executable: Path) -> str:
    output = subprocess.run(
        ["otool", "-l", str(executable)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for index, line in enumerate(output):
        command = line.strip()
        if command == "cmd LC_BUILD_VERSION":
            key = "minos"
        elif command == "cmd LC_VERSION_MIN_MACOSX":
            key = "version"
        else:
            continue
        for detail in output[index + 1 : index + 12]:
            fields = detail.strip().split()
            if len(fields) == 2 and fields[0] == key:
                return fields[1]
    raise RuntimeError(f"Mach-O 缺少 macOS deployment target: {executable}")


def verify_macos_app_bundle(
    app_bundle: Path, *, verify_load_commands: bool = False, verify_signatures: bool = False
) -> None:
    if not app_bundle.is_dir() or app_bundle.suffix != ".app":
        raise RuntimeError(f"macOS .app bundle 不存在: {app_bundle}")
    contents = app_bundle / "Contents"
    macos_dir = contents / "MacOS"
    info_plist = contents / "Info.plist"
    if not info_plist.is_file():
        raise RuntimeError(f"macOS bundle 缺少 Info.plist: {app_bundle}")
    try:
        info = plistlib.loads(info_plist.read_bytes())
    except Exception as error:
        raise RuntimeError(f"macOS bundle Info.plist 无法解析: {app_bundle}") from error
    if info.get("CFBundleIdentifier") != "io.determinflow.desktop":
        raise RuntimeError(
            f"macOS bundle identifier 必须是 io.determinflow.desktop: {app_bundle}"
        )
    if info.get("LSMinimumSystemVersion") != MINIMUM_MACOS_VERSION:
        raise RuntimeError(
            f"macOS bundle 最低版本必须是 {MINIMUM_MACOS_VERSION}: {app_bundle}"
        )
    main_executables = [path for path in macos_dir.iterdir() if path.is_file()]
    if not main_executables:
        raise RuntimeError(f"macOS bundle 缺少可执行文件: {app_bundle}")
    backend = contents / "Resources" / "runtime" / "backend" / "determinflow-backend"
    if not backend.is_file():
        raise RuntimeError(f"macOS bundle 缺少冻结后端: {backend}")

    macho_files: list[Path] = []
    for path in contents.rglob("*"):
        if not path.is_file():
            continue
        magic = _read_prefix(path, 4)
        if magic in {MACHO_MAGIC_64, MACHO_CIGAM_64, *FAT_MAGICS}:
            verify_macos_arm64_executable(path)
            macho_files.append(path)
    if not macho_files or backend not in macho_files:
        raise RuntimeError(f"macOS bundle 未完整识别内置 Mach-O: {app_bundle}")

    if verify_load_commands:
        maximum = _version_tuple(MINIMUM_MACOS_VERSION)
        for path in macho_files:
            target = _macho_deployment_target(path)
            if _version_tuple(target) > maximum:
                raise RuntimeError(
                    f"Mach-O deployment target {target} 超过应用声明的 "
                    f"{MINIMUM_MACOS_VERSION}: {path}"
                )
    if verify_signatures:
        for path in [*macho_files, app_bundle]:
            subprocess.run(
                ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(path)],
                check=True,
            )
    LOGGER.info("macOS .app bundle 验证通过: %s", app_bundle)


def verify_macos_dmg(dmg: Path, *, verify_container: bool = False) -> Path:
    if not dmg.is_file() or dmg.suffix.lower() != ".dmg":
        raise RuntimeError(f"macOS DMG 不存在: {dmg}")
    if dmg.stat().st_size < 1024:
        raise RuntimeError(f"macOS DMG 过小: {dmg}")
    if verify_container:
        subprocess.run(
            ["hdiutil", "verify", str(dmg)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    checksum = write_checksum(dmg)
    LOGGER.info("macOS DMG 验证通过: %s", dmg)
    LOGGER.info("SHA-256 文件: %s", checksum)
    return checksum


def assert_no_updater_artifacts(root: Path) -> None:
    candidates = [
        path
        for pattern in ("*", "*/*")
        for path in root.glob(pattern)
        if path.is_file()
    ]
    forbidden = [
        path
        for path in candidates
        if path.name.endswith(".sig") or path.name.endswith(".app.tar.gz")
    ]
    if forbidden:
        names = ", ".join(sorted(path.name for path in forbidden))
        raise RuntimeError(f"macOS 候选包不应包含 updater artifacts: {names}")
    LOGGER.info("macOS 候选包未生成 updater artifacts: %s", root)


def verify_windows_gui_executable(executable: Path) -> None:
    """Require a Windows PE GUI subsystem so release startup has no console."""
    image = executable.read_bytes()
    if len(image) < 64 or image[:2] != b"MZ":
        raise RuntimeError(f"桌面程序不是有效的 Windows PE 文件: {executable}")

    pe_offset = int.from_bytes(image[0x3C:0x40], "little")
    optional_header = pe_offset + 24
    subsystem_offset = optional_header + 68
    if (
        subsystem_offset + 2 > len(image)
        or image[pe_offset : pe_offset + 4] != b"PE\x00\x00"
        or int.from_bytes(image[optional_header : optional_header + 2], "little")
        not in {0x10B, 0x20B}
    ):
        raise RuntimeError(f"桌面程序的 Windows PE Header 无效: {executable}")

    subsystem = int.from_bytes(
        image[subsystem_offset : subsystem_offset + 2], "little"
    )
    if subsystem != WINDOWS_GUI_SUBSYSTEM:
        raise RuntimeError(
            f"桌面程序必须使用 Windows GUI Subsystem，实际值={subsystem}: {executable}"
        )
    LOGGER.info("Windows GUI Subsystem 验证通过: %s", executable)


def write_checksum(installer: Path) -> Path:
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    checksum_path = installer.with_suffix(installer.suffix + ".sha256")
    checksum_path.write_bytes(f"{digest}  {installer.name}\n".encode("ascii"))
    return checksum_path


def verify_updater_signature(signature: Path) -> None:
    if not signature.is_file():
        raise RuntimeError(f"更新签名不存在: {signature}")
    encoded = signature.read_text(encoding="utf-8").strip()
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise RuntimeError(f"更新签名不是有效的 Base64: {signature}") from error
    if len(decoded) < 64:
        raise RuntimeError(f"更新签名内容过短: {signature}")
    LOGGER.info("Tauri 更新签名验证通过: %s", signature)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--app-bundle", type=Path)
    parser.add_argument("--dmg", type=Path)
    parser.add_argument("--updater-signature", type=Path)
    parser.add_argument("--forbid-updater-artifacts", type=Path)
    parser.add_argument("--verify-macos-load-commands", action="store_true")
    parser.add_argument("--verify-macos-signatures", action="store_true")
    parser.add_argument("--verify-dmg-container", action="store_true")
    parser.add_argument("--desktop-executable", type=Path)
    parser.add_argument("--expected-flavor", choices=("core", "full"))
    options = parser.parse_args()

    verify_defaults(repo_root / "desktop" / "generated" / "default-config")
    executable_name = "determinflow-backend.exe" if sys.platform == "win32" else "determinflow-backend"
    backend = repo_root / "desktop" / "runtime" / "backend" / executable_name
    if not backend.is_file():
        raise RuntimeError(f"桌面后端不存在: {backend}")

    if options.expected_flavor:
        runtime_snapshot = backend.parent / "_internal" / "bundled-plugins"
        if options.expected_flavor == "full":
            verify_bundled_plugins(runtime_snapshot)
        elif runtime_snapshot.exists():
            raise RuntimeError("桌面 Core 后端意外包含 Full Plugin 快照")

    if options.desktop_executable:
        executable = options.desktop_executable.resolve()
        header = executable.read_bytes()[:2]
        if header == b"MZ":
            verify_windows_gui_executable(executable)
        else:
            verify_macos_arm64_executable(executable)

    if options.installer:
        installer = options.installer.resolve()
        if not installer.is_file() or installer.suffix.lower() != ".exe":
            raise RuntimeError(f"NSIS 安装包不存在: {installer}")
        checksum = write_checksum(installer)
        LOGGER.info("NSIS 安装包验证通过: %s", installer)
        LOGGER.info("SHA-256 文件: %s", checksum)
    elif options.app_bundle or options.dmg:
        LOGGER.info("macOS 候选包校验开始")
    else:
        LOGGER.info("桌面运行时边界验证通过")

    if options.app_bundle:
        verify_macos_app_bundle(
            options.app_bundle.resolve(),
            verify_load_commands=options.verify_macos_load_commands,
            verify_signatures=options.verify_macos_signatures,
        )

    if options.dmg:
        verify_macos_dmg(
            options.dmg.resolve(), verify_container=options.verify_dmg_container
        )

    if options.forbid_updater_artifacts:
        assert_no_updater_artifacts(options.forbid_updater_artifacts.resolve())

    if options.updater_signature:
        verify_updater_signature(options.updater_signature.resolve())
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
