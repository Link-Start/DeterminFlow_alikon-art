"""User-owned Skill package reads used by publish, preview, and drafts."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from src.skills.loader import SkillLoader
from src.skills.manager import SkillManager

from .catalog import MAX_SKILL_BYTES
from .bundle import pack, unpack, root_document, read_directory
from .errors import LocalSkillError
from .ownership import SKILL_ID_PATTERN

COMMUNITY_USE_LICENSE = "LicenseRef-DF-Community-1.0"
ALLOWED_PUBLISH_LICENSES = frozenset(
    {"MIT", "Apache-2.0", "CC-BY-4.0", "CC0-1.0", COMMUNITY_USE_LICENSE}
)

_MAX_SKILL_BYTES = MAX_SKILL_BYTES
_SEMVER_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_FRONTMATTER_OPEN = re.compile(r"\A\ufeff?---\r?\n")
_FRONTMATTER_CLOSE = re.compile(r"\r?\n---[ \t]*\r?\n")


def validate_skill_content(content: bytes) -> str:
    content = root_document(content)
    if not content or len(content) > _MAX_SKILL_BYTES:
        raise LocalSkillError("invalid_size", "SKILL.md 必须小于 256 KiB")
    if b"\x00" in content:
        raise LocalSkillError("invalid_encoding", "SKILL.md 必须是 UTF-8 文本")
    try:
        raw = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalSkillError("invalid_encoding", "SKILL.md 必须是 UTF-8 文本") from exc
    try:
        frontmatter, body = SkillLoader._parse_skill_md(raw)
    except ValueError as exc:
        raise LocalSkillError("invalid_skill", str(exc)) from exc
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not SKILL_ID_PATTERN.fullmatch(name):
        raise LocalSkillError("invalid_name", "Skill name 格式无效")
    if not isinstance(description, str) or not description.strip():
        raise LocalSkillError("invalid_description", "Skill description 不能为空")
    if not body.strip():
        raise LocalSkillError("invalid_body", "SKILL.md 正文不能为空")
    return name


def read_shareable_skill(skill_manager: SkillManager, skill_id: str) -> tuple[Path, bytes]:
    skill = skill_manager.get_skill(skill_id)
    if skill is None:
        raise LocalSkillError("not_found", "本地 Skill 不存在", status_code=404)
    provenance = skill.metadata.get("provenance")
    if not isinstance(provenance, dict):
        provenance = skill_manager.provenance_store.get("skill", skill_id)
    source = provenance.get("source") if isinstance(provenance, dict) else None
    if isinstance(source, dict) and source.get("kind") in {"core", "marketplace"}:
        raise LocalSkillError(
            "not_user_owned",
            "Core 内置或资源广场安装的 Skill 不能作为作者原稿重新投稿",
            status_code=403,
        )
    if skill.metadata.get("resource_owner", "user") != "user" or skill.metadata.get(
        "resource_read_only",
        False,
    ):
        raise LocalSkillError("not_user_owned", "只能上传用户自己的 Skill", status_code=403)
    raw_dir = skill.metadata.get("skill_dir")
    if not isinstance(raw_dir, str) or not raw_dir:
        raise LocalSkillError("invalid_local_skill", "无法定位本地 Skill")
    skill_dir = Path(raw_dir)
    content = read_directory(skill_dir)
    skill_path = skill_dir / "SKILL.md"
    parsed_id = validate_skill_content(content)
    if parsed_id != skill_id:
        raise LocalSkillError("identity_mismatch", "Skill 目录与 SKILL.md 标识不一致")
    return skill_path, content


def skill_identity(content: bytes) -> tuple[str, str]:
    raw = _decode_skill_text(content)
    frontmatter, body = _split_skill_document(raw)
    if not body.strip():
        raise LocalSkillError("invalid_body", "SKILL.md 正文不能为空")
    name = frontmatter.get("name")
    if not isinstance(name, str) or not SKILL_ID_PATTERN.fullmatch(name):
        raise LocalSkillError("invalid_name", "Skill name 格式无效")
    return name, _read_version(frontmatter)


def declared_skill_license(content: bytes) -> str:
    frontmatter, _body = _split_skill_document(_decode_skill_text(content))
    if "license" not in frontmatter:
        return ""
    value = frontmatter["license"]
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return str(value).strip()
    raise LocalSkillError("invalid_license", "所选授权与本地文件声明不一致，请保留原授权，或核实权利后更新原稿中的声明")


def require_publish_license(license_id: str, *, content: bytes) -> str:
    if license_id not in ALLOWED_PUBLISH_LICENSES:
        raise LocalSkillError("invalid_license", "请选择支持的使用授权")
    declared = declared_skill_license(content)
    if declared and declared != license_id:
        raise LocalSkillError("invalid_license", "所选授权与本地文件声明不一致，请保留原授权，或核实权利后更新原稿中的声明")
    return license_id


def prepare_skill_upload(content: bytes, *, name: str, version: str) -> bytes:
    target_name = require_skill_id(name)
    publication_version = require_publication_version(version)
    files = unpack(content)
    raw = _decode_skill_text(files["SKILL.md"])
    frontmatter, body = _split_skill_document(raw)
    current_name = frontmatter.get("name")
    current_version = _read_version(frontmatter)
    if current_name == target_name and current_version == publication_version:
        prepared = raw.encode("utf-8")
        validate_skill_content(prepared)
        return content if content.lstrip().startswith(b"{") else prepared
    next_frontmatter = dict(frontmatter)
    next_frontmatter["name"] = target_name
    _write_version(next_frontmatter, publication_version)
    dumped = yaml.safe_dump(
        next_frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    if not dumped.endswith("\n"):
        dumped += "\n"
    prepared_text = f"---\n{dumped}---\n{body}"
    prepared = prepared_text.encode("utf-8")
    parsed_name = validate_skill_content(prepared)
    if parsed_name != target_name:
        raise LocalSkillError("identity_mismatch", "准备投稿副本后的 Skill 标识不一致")
    prepared_name, prepared_version = skill_identity(prepared)
    if prepared_name != target_name or prepared_version != publication_version:
        raise LocalSkillError("identity_mismatch", "准备投稿副本后的 Skill 标识不一致")
    files["SKILL.md"] = prepared
    return pack(files)


def local_skill_preview(
    skill_manager: SkillManager,
    skill_id: str,
    *,
    target_slug: str | None = None,
    publication_version: str | None = None,
) -> dict[str, str]:
    skill = skill_manager.get_skill(skill_id)
    if skill is None:
        raise LocalSkillError("not_found", "本地 Skill 不存在", status_code=404)
    _path, content = read_shareable_skill(skill_manager, skill_id)
    source_name, source_version = skill_identity(content)
    source_sha256 = hashlib.sha256(content).hexdigest()
    prepared_name = require_skill_id(target_slug) if target_slug else source_name
    prepared_version = (
        require_publication_version(publication_version)
        if publication_version
        else source_version
    )
    if target_slug or publication_version:
        if not prepared_version:
            raise LocalSkillError("invalid_version", "发布版本必须是有效的语义化版本")
        prepared = prepare_skill_upload(
            content,
            name=prepared_name,
            version=prepared_version,
        )
    else:
        prepared = content
    prepared_name, prepared_version = skill_identity(prepared)
    return {
        "content": prepared.decode("utf-8"),
        "sha256": hashlib.sha256(prepared).hexdigest(),
        "source_sha256": source_sha256,
        "version": prepared_version,
        "skill_id": skill_id,
        "name": prepared_name,
    }


def require_publication_version(value: str) -> str:
    version = value.strip()
    if not _SEMVER_PATTERN.fullmatch(version):
        raise LocalSkillError("invalid_version", "发布版本必须是有效的语义化版本")
    return version


def require_skill_id(skill_id: str) -> str:
    value = skill_id.strip()
    if not SKILL_ID_PATTERN.fullmatch(value):
        raise LocalSkillError("invalid_slug", "Skill 标识格式无效")
    return value


def _decode_skill_text(content: bytes) -> str:
    content = root_document(content)
    if not content or len(content) > _MAX_SKILL_BYTES:
        raise LocalSkillError("invalid_size", "SKILL.md 必须小于 256 KiB")
    if b"\x00" in content:
        raise LocalSkillError("invalid_encoding", "SKILL.md 必须是 UTF-8 文本")
    try:
        raw = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalSkillError("invalid_encoding", "SKILL.md 必须是 UTF-8 文本") from exc
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    return raw


def _split_skill_document(raw: str) -> tuple[dict, str]:
    opening = _FRONTMATTER_OPEN.match(raw)
    if not opening:
        raise LocalSkillError("invalid_skill", "SKILL.md 格式错误：缺少 YAML frontmatter")
    rest = raw[opening.end() :]
    closing = _FRONTMATTER_CLOSE.search(rest)
    if closing is None:
        raise LocalSkillError("invalid_skill", "SKILL.md 格式错误：缺少 YAML frontmatter")
    try:
        loaded = yaml.safe_load(rest[: closing.start()])
    except yaml.YAMLError as exc:
        raise LocalSkillError("invalid_skill", "SKILL.md 格式错误：缺少 YAML frontmatter") from exc
    if not isinstance(loaded, dict):
        raise LocalSkillError("invalid_skill", "YAML frontmatter 必须是字典")
    return loaded, rest[closing.end() :]


def _read_version(frontmatter: dict) -> str:
    metadata = frontmatter.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    version = metadata.get("version", frontmatter.get("version"))
    if version is None:
        return ""
    return str(version).strip()


def _write_version(frontmatter: dict, version: str) -> None:
    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict):
        next_metadata = dict(metadata)
        next_metadata["version"] = version
        frontmatter["metadata"] = next_metadata
        if "version" in frontmatter:
            frontmatter["version"] = version
        return
    if "version" in frontmatter:
        frontmatter["version"] = version
        return
    frontmatter["metadata"] = {"version": version}


def install_skill_atomically(target: Path, content: bytes, *, check_types: bool = True) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".marketplace-", dir=target.parent))
    try:
        for relative, data in unpack(content, check_types=check_types).items():
            skill_path = staging / relative
            skill_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(skill_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def replace_skill_file_atomically(skill_path: Path, content: bytes, *, check_types: bool = True) -> None:
    # Stage a complete tree before touching an existing install. Keeping the
    # previous directory until the swap succeeds also removes obsolete files.
    files = unpack(content, check_types=check_types)
    if set(files) != {"SKILL.md"} or set(skill_path.parent.iterdir()) != {skill_path}:
        target = skill_path.parent
        holding = Path(tempfile.mkdtemp(prefix=".marketplace-update-", dir=target.parent))
        replacement = holding / "replacement"
        backup = holding / "previous"
        try:
            install_skill_atomically(replacement, content, check_types=check_types)
            os.replace(target, backup)
            try:
                os.replace(replacement, target)
            except Exception:
                os.replace(backup, target)
                raise
        finally:
            # If restoration itself failed, retain the backup for recovery.
            if target.exists():
                shutil.rmtree(holding, ignore_errors=True)
        return
    descriptor, name = tempfile.mkstemp(prefix=".marketplace-", suffix=".tmp", dir=skill_path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(files["SKILL.md"])
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, skill_path)
    finally:
        temporary.unlink(missing_ok=True)
