"""Account-isolated local publish drafts. Never uploaded to the website."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import LocalSkillError
from .ownership import SKILL_ID_PATTERN

SCHEMA_VERSION = 1
MAX_DRAFT_BYTES = 64 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_BASE_VERSION = 64
_MAX_REVISION = 2_147_483_647
_LAST_SOURCES_NAME = "last-sources.json"
DRAFT_FIELD_LIMITS = {
    "license": 32,
    "display_name": 80,
    "author_name": 80,
    "summary": 1024,
    "functional_category": 32,
    "primary_locale": 16,
    "tags_csv": 680,
    "release_notes": 2000,
    "usage_guide": 8000,
}


def partition_key(issuer: str, subject: str, marketplace_origin: str) -> str:
    material = "\0".join(
        ("marketplace-draft-v1", issuer, subject, marketplace_origin)
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def require_local_identity(account: Any, marketplace_origin: str) -> tuple[str, str]:
    if account is None or account.access_token() is None:
        raise LocalSkillError("login_required", "请先登录 DeterminFlow", status_code=401)
    claims = account.local_identity_claims()
    if not isinstance(claims, tuple) or len(claims) != 2:
        raise LocalSkillError(
            "identity_unavailable",
            "当前登录缺少稳定账号标识",
            status_code=401,
        )
    issuer, subject = claims
    if not isinstance(issuer, str) or not isinstance(subject, str):
        raise LocalSkillError(
            "identity_unavailable",
            "当前登录缺少稳定账号标识",
            status_code=401,
        )
    origin = marketplace_origin.strip()
    if not origin:
        raise LocalSkillError(
            "marketplace_not_configured",
            "资源广场服务尚未配置",
            status_code=503,
        )
    return issuer, subject


def bind_draft_access(account: Any, marketplace_origin: str) -> dict[str, Any]:
    issuer, subject = require_local_identity(account, marketplace_origin)
    token = account.access_token()

    def validate_access() -> None:
        if account.access_token() != token or require_local_identity(account, marketplace_origin) != (issuer, subject):
            raise LocalSkillError("login_changed", "登录状态已变化，请重试", status_code=401)

    return {"issuer": issuer, "subject": subject, "marketplace_origin": marketplace_origin,
            "validate_access": validate_access}


def normalize_draft_fields(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise LocalSkillError("invalid_draft", "草稿字段无效")
    fields: dict[str, str] = {}
    for name, limit in DRAFT_FIELD_LIMITS.items():
        value = raw.get(name, "")
        if not isinstance(value, str):
            raise LocalSkillError("invalid_draft", f"{name} 必须是字符串")
        if len(value) > limit:
            raise LocalSkillError("invalid_draft", f"{name} 超出长度限制")
        fields[name] = value
    return fields


def normalize_skill_id(skill_id: str) -> str:
    value = skill_id.strip()
    if not SKILL_ID_PATTERN.fullmatch(value):
        raise LocalSkillError("invalid_slug", "Skill 标识格式无效")
    return value


def normalize_optional_skill_id(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise LocalSkillError("invalid_slug", "Skill 标识格式无效")
    stripped = value.strip()
    if not stripped:
        return ""
    return normalize_skill_id(stripped)


def normalize_publication_version(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > _MAX_BASE_VERSION:
        raise LocalSkillError("invalid_draft", "publication_version 无效")
    return value.strip()


def normalize_base_version(value: Any) -> str:
    if not isinstance(value, str) or len(value) > _MAX_BASE_VERSION:
        raise LocalSkillError("invalid_draft", "base_version 无效")
    return value


def normalize_base_sha256(value: Any) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise LocalSkillError("invalid_digest", "内容摘要必须是 64 位小写十六进制")
    return value


def normalize_expected_revision(value: Any, *, allow_null: bool) -> int | None:
    if value is None:
        if allow_null:
            return None
        raise LocalSkillError("invalid_draft", "expected_revision 无效")
    if not isinstance(value, int) or isinstance(value, bool):
        raise LocalSkillError("invalid_draft", "expected_revision 无效")
    if value < 1 or value > _MAX_REVISION:
        raise LocalSkillError("invalid_draft", "expected_revision 无效")
    return value


class PublishDraftStore:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser()
        self._lock = asyncio.Lock()

    async def get(
        self,
        *,
        issuer: str,
        subject: str,
        marketplace_origin: str,
        skill_id: str,
        validate_access: Callable[[], None] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        skill_id = normalize_skill_id(skill_id)
        async with self._lock:
            if validate_access is not None:
                validate_access()
            path = self._draft_path(issuer, subject, marketplace_origin, skill_id)
            draft = self._read_draft(path, skill_id)
            last_source = self._read_last_source(
                issuer, subject, marketplace_origin, skill_id
            )
            if draft is not None:
                source = str(draft.get("source_skill_id") or "")
                if source:
                    last_source = source
            return draft, last_source

    async def save(
        self,
        *,
        issuer: str,
        subject: str,
        marketplace_origin: str,
        skill_id: str,
        expected_revision: int | None,
        base_version: str,
        base_sha256: str,
        fields: dict[str, str],
        source_skill_id: str = "",
        publication_version: str = "",
        validate_access: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        skill_id = normalize_skill_id(skill_id)
        base_version = normalize_base_version(base_version)
        base_sha256 = normalize_base_sha256(base_sha256)
        fields = normalize_draft_fields(fields)
        source_skill_id = normalize_optional_skill_id(source_skill_id)
        publication_version = normalize_publication_version(publication_version)
        async with self._lock:
            if validate_access is not None:
                validate_access()
            path = self._draft_path(issuer, subject, marketplace_origin, skill_id)
            current = self._read_draft(path, skill_id)
            current_revision = None if current is None else current["revision"]
            if current_revision != expected_revision:
                raise LocalSkillError(
                    "draft_conflict",
                    "草稿已被更新，请刷新后重试",
                    status_code=409,
                )
            next_revision = 1 if current_revision is None else current_revision + 1
            draft = {
                "schema_version": SCHEMA_VERSION,
                "skill_id": skill_id,
                "source_skill_id": source_skill_id,
                "publication_version": publication_version,
                "base_version": base_version,
                "base_sha256": base_sha256,
                "fields": fields,
                "revision": next_revision,
                "updated_at": _utc_now(),
            }
            self._write_draft(path, draft)
            if source_skill_id:
                self._write_last_source(
                    issuer, subject, marketplace_origin, skill_id, source_skill_id
                )
            return draft

    async def delete(
        self,
        *,
        issuer: str,
        subject: str,
        marketplace_origin: str,
        skill_id: str,
        expected_revision: int,
        validate_access: Callable[[], None] | None = None,
    ) -> dict[str, bool]:
        skill_id = normalize_skill_id(skill_id)
        async with self._lock:
            if validate_access is not None:
                validate_access()
            path = self._draft_path(issuer, subject, marketplace_origin, skill_id)
            current = self._read_draft(path, skill_id)
            if current is None:
                return {"deleted": True}
            if current["revision"] != expected_revision:
                raise LocalSkillError(
                    "draft_conflict",
                    "草稿已被更新，请刷新后重试",
                    status_code=409,
                )
            try:
                path.unlink()
            except FileNotFoundError:
                return {"deleted": True}
            except OSError as exc:
                raise LocalSkillError("draft_store_invalid", "无法删除草稿") from exc
            return {"deleted": True}

    def _draft_path(
        self,
        issuer: str,
        subject: str,
        marketplace_origin: str,
        skill_id: str,
    ) -> Path:
        partition = partition_key(issuer, subject, marketplace_origin)
        root = self._secure_root()
        directory = root / partition
        if directory.is_symlink():
            raise LocalSkillError("draft_store_invalid", "草稿目录无效", status_code=500)
        path = directory / f"{skill_id}.json"
        self._assert_contained(root, path)
        return path

    def _secure_root(self) -> Path:
        _secure_mkdir(self.root)
        root = self.root.resolve()
        if root.is_symlink() or not root.is_dir():
            raise LocalSkillError("draft_store_invalid", "草稿目录无效", status_code=500)
        return root

    def _read_draft(self, path: Path, skill_id: str) -> dict[str, Any] | None:
        if path.is_symlink():
            raise LocalSkillError("draft_store_invalid", "草稿文件无效", status_code=500)
        if not path.exists():
            return None
        if not path.is_file():
            raise LocalSkillError("draft_store_invalid", "草稿文件无效", status_code=500)
        try:
            size = path.stat().st_size
        except (OSError, UnicodeDecodeError) as exc:
            raise LocalSkillError("draft_store_invalid", "无法读取草稿") from exc
        if size > MAX_DRAFT_BYTES:
            raise LocalSkillError("draft_too_large", "草稿超出大小限制", status_code=413)
        try:
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                raw = handle.read(MAX_DRAFT_BYTES + 1)
        except (OSError, UnicodeDecodeError) as exc:
            raise LocalSkillError("draft_store_invalid", "无法读取草稿") from exc
        if len(raw.encode("utf-8")) > MAX_DRAFT_BYTES:
            raise LocalSkillError("draft_too_large", "草稿超出大小限制", status_code=413)
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise LocalSkillError("draft_unreadable", "草稿内容已损坏", status_code=500) from exc
        draft = _coerce_draft(payload, skill_id)
        if draft is None:
            raise LocalSkillError("draft_unreadable", "草稿内容已损坏", status_code=500)
        return draft

    def _write_draft(self, path: Path, draft: dict[str, Any]) -> None:
        encoded = json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        payload = encoded.encode("utf-8")
        if len(payload) > MAX_DRAFT_BYTES:
            raise LocalSkillError("draft_too_large", "草稿超出大小限制", status_code=413)
        _secure_mkdir(path.parent)
        if path.is_symlink():
            raise LocalSkillError("draft_store_invalid", "草稿文件无效", status_code=500)
        temporary = path.with_name(f".{path.name}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _last_sources_path(
        self,
        issuer: str,
        subject: str,
        marketplace_origin: str,
    ) -> Path:
        partition = partition_key(issuer, subject, marketplace_origin)
        root = self._secure_root()
        directory = root / partition
        if directory.is_symlink():
            raise LocalSkillError("draft_store_invalid", "草稿目录无效", status_code=500)
        path = directory / _LAST_SOURCES_NAME
        self._assert_contained(root, path)
        return path

    def _read_last_source(
        self,
        issuer: str,
        subject: str,
        marketplace_origin: str,
        skill_id: str,
    ) -> str:
        path = self._last_sources_path(issuer, subject, marketplace_origin)
        if path.is_symlink() or not path.is_file():
            return ""
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, ValueError):
            return ""
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            return ""
        sources = payload.get("sources")
        if not isinstance(sources, dict):
            return ""
        value = sources.get(skill_id)
        if not isinstance(value, str):
            return ""
        try:
            return normalize_optional_skill_id(value)
        except LocalSkillError:
            return ""

    def _write_last_source(
        self,
        issuer: str,
        subject: str,
        marketplace_origin: str,
        skill_id: str,
        source_skill_id: str,
    ) -> None:
        path = self._last_sources_path(issuer, subject, marketplace_origin)
        sources: dict[str, str] = {}
        if path.is_file() and not path.is_symlink():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("sources"), dict):
                for key, value in payload["sources"].items():
                    try:
                        sources[normalize_skill_id(str(key))] = normalize_optional_skill_id(value)
                    except LocalSkillError:
                        continue
        sources[skill_id] = source_skill_id
        document = {
            "schema_version": SCHEMA_VERSION,
            "sources": sources,
        }
        self._write_draft(path, document)

    @staticmethod
    def _assert_contained(root: Path, path: Path) -> None:
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise LocalSkillError("invalid_slug", "Skill 标识格式无效") from exc


def _secure_mkdir(path: Path) -> None:
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise LocalSkillError("draft_store_invalid", "草稿目录无效", status_code=500)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise LocalSkillError("draft_store_invalid", "草稿目录无效", status_code=500)
    os.chmod(path, 0o700)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_draft(payload: Any, skill_id: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != SCHEMA_VERSION:
        return None
    if payload.get("skill_id") != skill_id:
        return None
    try:
        fields = normalize_draft_fields(payload.get("fields"))
        base_version = normalize_base_version(payload.get("base_version"))
        base_sha256 = normalize_base_sha256(payload.get("base_sha256"))
        source_skill_id = normalize_optional_skill_id(payload.get("source_skill_id"))
        publication_version = normalize_publication_version(payload.get("publication_version"))
        revision = payload.get("revision")
        updated_at = payload.get("updated_at")
    except LocalSkillError:
        return None
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        return None
    if not isinstance(updated_at, str) or not updated_at:
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_id": skill_id,
        "source_skill_id": source_skill_id,
        "publication_version": publication_version,
        "base_version": base_version,
        "base_sha256": base_sha256,
        "fields": fields,
        "revision": revision,
        "updated_at": updated_at,
    }
