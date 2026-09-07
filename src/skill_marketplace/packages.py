"""Pinned remote Skill package facts used by install and update."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .errors import LocalSkillError
from .local_skills import skill_identity, validate_skill_content

PUBLIC_RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PUBLISHER_ID_PATTERN = re.compile(r"^pub_[a-f0-9]{24}$")


@dataclass(frozen=True)
class RemoteSkillRelease:
    detail: dict[str, Any]
    resource_id: Any
    version_id: str
    sha256: str
    publisher_id: Any
    skill_name: Any
    version: str
    license: str
    resource_type: str
    functional_category: str


def require_public_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not PUBLIC_RESOURCE_ID_PATTERN.fullmatch(value):
        raise LocalSkillError(
            "missing_provenance",
            f"资源广场详情缺少可信 {field}",
            status_code=502,
        )
    return value


def require_sha256(digest: str) -> str:
    if not SHA256_PATTERN.fullmatch(digest):
        raise LocalSkillError("invalid_digest", "内容摘要必须是 64 位小写十六进制")
    return digest


def require_publisher_id(value: Any) -> str:
    if not isinstance(value, str) or not PUBLISHER_ID_PATTERN.fullmatch(value):
        raise LocalSkillError(
            "missing_provenance",
            "资源广场详情缺少可信发布者标识",
            status_code=502,
        )
    return value


def parse_remote_skill(detail: dict[str, Any]) -> RemoteSkillRelease:
    resource = _mapping(detail.get("resource"))
    payload = _mapping(detail.get("payload"))
    author = _mapping(resource.get("author"))
    release = _mapping(resource.get("release"))
    current_sha256 = (
        payload.get("sha256")
        or detail.get("sha256")
        or detail.get("content_sha256")
    )
    if not isinstance(current_sha256, str) or not SHA256_PATTERN.fullmatch(current_sha256):
        raise LocalSkillError("invalid_integrity", "Skill 缺少可信完整性信息", status_code=502)
    version = (
        release.get("version")
        or detail.get("version")
        or detail.get("declared_version")
        or detail.get("version_number")
        or ""
    )
    license_id = release.get("license") or detail.get("license") or ""
    return RemoteSkillRelease(
        detail=detail,
        resource_id=resource.get("id") or detail.get("resource_id"),
        version_id=require_public_id(
            resource.get("version_id") or detail.get("version_id"),
            "version_id",
        ),
        sha256=current_sha256,
        publisher_id=(
            author.get("id")
            or author.get("publisher_id")
            or detail.get("publisher_id")
        ),
        skill_name=payload.get("name") or detail.get("skill_name") or detail.get("slug"),
        version=version.strip() if isinstance(version, str) else "",
        license=license_id if isinstance(license_id, str) else "",
        resource_type=str(
            resource.get("resource_type") or detail.get("resource_type") or "skill"
        ),
        functional_category=str(
            resource.get("functional_category")
            or detail.get("functional_category")
            or "general"
        ),
    )


def pin_remote_skill(
    detail: dict[str, Any],
    *,
    expected_version_id: str,
    expected_sha256: str,
) -> RemoteSkillRelease:
    remote = parse_remote_skill(detail)
    if remote.version_id != expected_version_id or remote.sha256 != expected_sha256:
        raise LocalSkillError(
            "version_changed",
            "资源版本已变化，请刷新详情后重新确认安装",
            status_code=409,
        )
    return remote


def verify_downloaded_skill(
    content: bytes,
    *,
    slug: str,
    expected_sha256: str,
    header_sha256: str | None,
    declared_name: Any,
    expected_version: str | None = None,
) -> str:
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256 or (
        header_sha256 is not None and header_sha256 != expected_sha256
    ):
        raise LocalSkillError("integrity_mismatch", "Skill 下载完整性校验失败", status_code=502)
    skill_id = validate_skill_content(content)
    if declared_name != skill_id or slug != skill_id:
        raise LocalSkillError("identity_mismatch", "Skill 标识与下载内容不一致", status_code=502)
    if expected_version is not None:
        _name, version = skill_identity(content)
        if version != expected_version:
            raise LocalSkillError(
                "identity_mismatch",
                "Skill 版本与下载内容不一致",
                status_code=502,
            )
    return skill_id


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
