"""Generate desktop/src-tauri/icons/icon.icns from the official brand SVG."""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LOGGER = logging.getLogger("desktop.generate_macos_icon")
BRAND_SVG_RELATIVE = Path("web/public/brand/determinflow-mark.svg")
ICNS_RELATIVE = Path("desktop/src-tauri/icons/icon.icns")
RENDERER_RELATIVE = Path("desktop/scripts/render_brand_png.swift")
ICONSET_FILES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


def generate_macos_icon(repo_root: Path, output: Path | None = None) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("macOS icon.icns 只能在 Darwin 上从官方品牌 SVG 生成")

    brand_svg = repo_root / BRAND_SVG_RELATIVE
    renderer = repo_root / RENDERER_RELATIVE
    icns_path = output or (repo_root / ICNS_RELATIVE)
    if not brand_svg.is_file():
        raise RuntimeError(f"缺少官方品牌 SVG: {brand_svg}")
    if "DeterminFlow mark" not in brand_svg.read_text(encoding="utf-8"):
        raise RuntimeError(f"品牌 SVG 不是正式 DeterminFlow mark: {brand_svg}")
    if not renderer.is_file():
        raise RuntimeError(f"缺少品牌 PNG 渲染器: {renderer}")

    swiftc = shutil.which("swiftc")
    sips = shutil.which("sips")
    iconutil = shutil.which("iconutil")
    missing = [
        name
        for name, path in (("swiftc", swiftc), ("sips", sips), ("iconutil", iconutil))
        if path is None
    ]
    if missing:
        raise RuntimeError(f"缺少 macOS 图标工具: {', '.join(missing)}")

    icns_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="determinflow-macos-icon-") as raw_root:
        root = Path(raw_root)
        renderer_bin = root / "render_brand_png"
        master_png = root / "determinflow-mark-1024.png"
        iconset = root / "icon.iconset"
        iconset.mkdir()
        subprocess.run(
            [swiftc, "-O", "-o", str(renderer_bin), str(renderer)],
            check=True,
        )
        subprocess.run([str(renderer_bin), str(brand_svg), str(master_png)], check=True)
        if not master_png.is_file() or master_png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("官方品牌 SVG 未能渲染为 PNG")
        for name, size in ICONSET_FILES:
            subprocess.run(
                [
                    sips,
                    "-z",
                    str(size),
                    str(size),
                    str(master_png),
                    "--out",
                    str(iconset / name),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        subprocess.run(
            [iconutil, "-c", "icns", str(iconset), "-o", str(icns_path)],
            check=True,
        )

    if icns_path.read_bytes()[:4] != b"icns" or icns_path.stat().st_size < 1024:
        raise RuntimeError(f"生成的 icon.icns 无效: {icns_path}")
    LOGGER.info("已从 %s 生成 %s", brand_svg, icns_path)
    return icns_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    generate_macos_icon(repo_root, options.output)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
