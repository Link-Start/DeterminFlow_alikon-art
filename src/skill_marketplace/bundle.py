"""Versioned, deterministic single-Skill packages; legacy Markdown stays unchanged."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from pathlib import Path

from .errors import LocalSkillError

FORMAT = "determinflow.skill-bundle.v1"
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_FILES = 64
_COMPONENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)


def _invalid(message: str, code: str = "invalid_package") -> LocalSkillError:
    return LocalSkillError(code, message)


def validate_paths(files: dict[str, bytes], *, check_types: bool = True) -> None:
    if not files or len(files) > MAX_FILES or "SKILL.md" not in files:
        raise _invalid("Skill 包必须包含根 SKILL.md，且最多包含 64 个文件")
    seen: set[str] = set()
    directories: set[str] = set()
    directory_spellings: dict[str, str] = {}
    total = 0
    enabled = check_types and os.environ.get("MARKETPLACE_SKILL_FILE_TYPE_CHECK", "true") != "false"
    extensions = {
        item.strip().lower() for item in
        os.environ.get("MARKETPLACE_SKILL_ALLOWED_EXTENSIONS", ".md").split(",")
        if item.strip()
    }
    for path, content in files.items():
        parts = path.split("/")
        if len(path) > 240 or len(parts) > 16 or any(
            not _COMPONENT.fullmatch(part) or part.endswith(".") or _RESERVED.match(part)
            for part in parts
        ):
            raise _invalid(f"Skill 包文件路径无效：{path}")
        folded = path.lower()
        if folded in seen or (parts[-1].lower() == "skill.md" and path != "SKILL.md"):
            raise _invalid("Skill 包不能包含重名文件或多个 Skill")
        seen.add(folded)
        directories.update("/".join(parts[:i]).lower() for i in range(1, len(parts)))
        for i in range(1, len(parts)):
            directory = "/".join(parts[:i])
            if directory_spellings.setdefault(directory.lower(), directory) != directory:
                raise _invalid("Skill 包目录大小写冲突")
        if enabled and Path(path).suffix.lower() not in extensions:
            raise _invalid(f"文件类型不在白名单中：{path}", "file_type_not_allowed")
        if len(content) > MAX_FILE_BYTES:
            raise _invalid(f"文件超过 256 KiB：{path}", "invalid_size")
        if Path(path).suffix.lower() == ".md":
            try:
                content.decode("utf-8")
                if b"\x00" in content:
                    raise ValueError("NUL")
            except (UnicodeError, ValueError) as exc:
                raise _invalid(f"Markdown 必须是 UTF-8 文本：{path}", "invalid_encoding") from exc
        total += len(content)
    if seen & directories:
        raise _invalid("Skill 包文件和目录路径冲突")
    if total > MAX_TOTAL_BYTES:
        raise _invalid("Skill 包展开后不能超过 1 MiB", "invalid_size")


def unpack(content: bytes, *, check_types: bool = True) -> dict[str, bytes]:
    if not content or len(content) > MAX_PACKAGE_BYTES:
        raise _invalid("Skill 包不能为空或超过 2 MiB", "invalid_size")
    if not content.lstrip().startswith(b"{"):
        files = {"SKILL.md": content}
        validate_paths(files, check_types=check_types)
        return files
    try:
        document = json.loads(content.decode("utf-8"))
        if not isinstance(document, dict) or set(document) != {"format", "files"} or document["format"] != FORMAT:
            raise ValueError("unsupported package")
        entries = document["files"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
            raise ValueError("invalid file count")
        files = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "content"}:
                raise ValueError("invalid entry")
            path, encoded = entry["path"], entry["content"]
            if not isinstance(path, str) or not isinstance(encoded, str) or path in files:
                raise ValueError("invalid or duplicate path")
            data = base64.b64decode(encoded, validate=True)
            if base64.b64encode(data).decode("ascii") != encoded:
                raise ValueError("noncanonical base64")
            files[path] = data
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError) as exc:
        raise _invalid("Skill 包格式无效") from exc
    validate_paths(files, check_types=check_types)
    return files


def pack(files: dict[str, bytes], *, check_types: bool = True) -> bytes:
    validate_paths(files, check_types=check_types)
    if set(files) == {"SKILL.md"}:
        return files["SKILL.md"]
    return json.dumps({"format": FORMAT, "files": [
        {"path": path, "content": base64.b64encode(files[path]).decode("ascii")}
        for path in sorted(files)
    ]}, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def root_document(content: bytes) -> bytes:
    return unpack(content)["SKILL.md"]


def file_digests(content: bytes) -> dict[str, str]:
    return {path: hashlib.sha256(data).hexdigest() for path, data in unpack(content).items()}


def package_file_metadata(content: bytes) -> dict:
    files = file_digests(content)
    return {"files": files} if len(files) > 1 or content.lstrip().startswith(b"{") else {}


def read_directory(directory: Path, *, check_types: bool = True) -> bytes:
    """Read only regular files, without following links or unbounded special files."""
    if directory.is_symlink() or not directory.is_dir():
        raise _invalid("Skill 目录无效", "attachments_not_allowed")
    files: dict[str, bytes] = {}

    def fail_read(error: OSError) -> None:
        raise error

    try:
        for parent, dirs, names in os.walk(directory, followlinks=False, onerror=fail_read):
            for name in dirs:
                if (Path(parent) / name).is_symlink():
                    raise _invalid("Skill 包不能包含软链接", "attachments_not_allowed")
            for name in names:
                path = Path(parent) / name
                if path.is_symlink():
                    raise _invalid("Skill 包不能包含软链接", "attachments_not_allowed")
                descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
                with os.fdopen(descriptor, "rb") as handle:
                    info = os.fstat(handle.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        raise _invalid("Skill 包只能包含普通文件", "attachments_not_allowed")
                    if info.st_size > MAX_FILE_BYTES:
                        raise _invalid("Skill 文件不能超过 256 KiB", "invalid_size")
                    files[path.relative_to(directory).as_posix()] = handle.read(MAX_FILE_BYTES + 1)
                if len(files) > MAX_FILES:
                    raise _invalid("Skill 包最多包含 64 个文件", "invalid_size")
    except OSError as exc:
        raise _invalid("无法读取 Skill 文件或发现软链接", "attachments_not_allowed") from exc
    return pack(files, check_types=check_types)
