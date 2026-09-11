"""Explicit safe updates of an already-installed marketplace Skill."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from src.skills.manager import SkillManager

from .errors import LocalSkillError
from .bundle import package_file_metadata, read_directory, unpack
from .local_skills import replace_skill_file_atomically
from .ownership import compare_semver
from .packages import (
    pin_remote_skill,
    require_public_id,
    require_publisher_id,
    require_sha256,
    verify_downloaded_skill,
)


async def update_marketplace_skill(
    service: Any,
    slug: str,
    *,
    expected_version_id: str,
    expected_sha256: str,
) -> dict[str, Any]:
    service._validate_slug(slug)
    expected_version_id = require_public_id(expected_version_id, "version_id")
    require_sha256(expected_sha256)
    async with service._lock:
        manager: SkillManager = service.skill_manager
        config = manager.config_manager
        if config is None:
            raise LocalSkillError(
                "config_unavailable",
                "无法保存 Skill 启用状态，请恢复本地配置后重试",
                status_code=503,
            )
        marketplace = service._require_marketplace()
        detail = await marketplace.get_skill(slug)
        remote = pin_remote_skill(
            detail,
            expected_version_id=expected_version_id,
            expected_sha256=expected_sha256,
        )
        resource_id = require_public_id(remote.resource_id, "resource_id")
        publisher_id = require_publisher_id(remote.publisher_id)
        skill, provenance, source, package = _require_updatable_install(
            manager,
            slug,
            marketplace_url=marketplace.base_url,
            resource_id=resource_id,
            publisher_id=publisher_id,
        )
        skill_path = _trusted_marketplace_skill_path(manager, slug, skill)
        previous_bytes = _require_unmodified_original(skill_path, package)
        local_version = (
            package.get("version")
            if isinstance(package.get("version"), str)
            else skill.version
        )
        _require_newer_version(remote.version, local_version if isinstance(local_version, str) else "")
        content, header_sha256 = await marketplace.download_skill(slug)
        skill_id = verify_downloaded_skill(
            content,
            slug=slug,
            expected_sha256=expected_sha256,
            header_sha256=header_sha256,
            declared_name=remote.skill_name,
            expected_version=remote.version,
        )
        if skill_id != slug:
            raise LocalSkillError("identity_mismatch", "Skill 标识与下载内容不一致", status_code=502)
        # The download yields control: recheck ownership and bytes immediately before writing.
        current_skill, current_provenance, _, _ = _require_updatable_install(
            manager, slug, marketplace_url=marketplace.base_url,
            resource_id=resource_id, publisher_id=publisher_id,
        )
        if current_provenance != provenance:
            raise LocalSkillError("local_modified", "本地 Skill 来源已变化，请刷新后重试", status_code=409)
        skill_path = _trusted_marketplace_skill_path(manager, slug, current_skill)
        _require_unmodified_original(skill_path, package)
        previous_provenance = dict(provenance)
        file_replaced = False
        provenance_replaced = False
        try:
            replace_skill_file_atomically(skill_path, content)
            file_replaced = True
            manager.provenance_store.record(
                "skill",
                skill_id,
                source={
                    **source,
                    "kind": "marketplace",
                    "registry": marketplace.base_url,
                    "resource_id": resource_id,
                    "version_id": remote.version_id,
                    "publisher_id": publisher_id,
                    "resource_type": remote.resource_type,
                    "functional_category": remote.functional_category,
                },
                package={
                    "version": remote.version,
                    "sha256": expected_sha256,
                    "license": remote.license,
                    **package_file_metadata(content),
                },
                installed_at=previous_provenance.get("installed_at")
                if isinstance(previous_provenance.get("installed_at"), str)
                else None,
            )
            provenance_replaced = True
            manager.reload()
            installed = manager.get_skill(skill_id)
            if installed is None:
                raise OSError("updated skill missing after reload")
            current = _trusted_marketplace_skill_path(manager, skill_id, installed)
            if unpack(read_directory(current.parent)) != unpack(content):
                raise OSError("updated skill files did not match the pinned package")
        except Exception:
            if file_replaced:
                replace_skill_file_atomically(skill_path, previous_bytes, check_types=False)
            if provenance_replaced:
                manager.provenance_store.record(
                    "skill",
                    skill_id,
                    source=dict(previous_provenance.get("source") or source),
                    package=dict(previous_provenance.get("package") or package),
                    installed_at=previous_provenance.get("installed_at")
                    if isinstance(previous_provenance.get("installed_at"), str)
                    else None,
                )
            try:
                manager.reload()
            except Exception:
                pass
            raise
    installed = manager.get_skill(skill_id)
    enabled = bool(installed is not None and installed.enabled)
    return {
        "installed": True,
        "updated": True,
        "skill_id": skill_id,
        "version": remote.version or None,
        "sha256": expected_sha256,
        "enabled": enabled,
        "provenance": manager.provenance_store.get("skill", skill_id),
        "installation": service._installation_state(detail),
    }


def _require_updatable_install(
    manager: SkillManager,
    slug: str,
    *,
    marketplace_url: str,
    resource_id: str,
    publisher_id: str,
) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    skill = manager.get_skill(slug)
    if skill is None:
        if (manager.marketplace_skills_dir / slug).exists():
            raise LocalSkillError(
                "conflict",
                "本地存在同名但来源不同的 Skill",
                status_code=409,
            )
        raise LocalSkillError("not_found", "本地未安装该 Skill", status_code=404)
    provenance = manager.provenance_store.get("skill", slug)
    provenance = dict(provenance) if isinstance(provenance, dict) else {}
    source = provenance.get("source")
    source = dict(source) if isinstance(source, dict) else {}
    package = provenance.get("package")
    package = dict(package) if isinstance(package, dict) else {}
    if source.get("kind") != "marketplace":
        raise LocalSkillError(
            "conflict",
            "本地存在同名但来源不同的 Skill",
            status_code=409,
        )
    if source.get("registry") != marketplace_url or source.get("resource_id") != resource_id:
        raise LocalSkillError(
            "conflict",
            "本地存在同名但来源不同的 Skill",
            status_code=409,
        )
    if source.get("publisher_id") != publisher_id:
        raise LocalSkillError(
            "identity_mismatch",
            "资源发布者与已安装来源不一致",
            status_code=409,
        )
    return skill, provenance, source, package


def _trusted_marketplace_skill_path(
    manager: SkillManager,
    skill_id: str,
    skill: Any,
) -> Path:
    marketplace_root = manager.marketplace_skills_dir.resolve()
    candidate = marketplace_root / skill_id
    if candidate.is_symlink() or not candidate.is_dir():
        raise LocalSkillError("conflict", "Skill 安装路径无效", status_code=409)
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise LocalSkillError("conflict", "无法验证 Skill 安装路径", status_code=409) from exc
    if resolved.parent != marketplace_root or resolved.name != skill_id:
        raise LocalSkillError("conflict", "Skill 安装路径无效", status_code=409)
    raw_dir = skill.metadata.get("skill_dir")
    if not isinstance(raw_dir, str) or not raw_dir:
        raise LocalSkillError("invalid_local_skill", "无法定位本地 Skill")
    try:
        if Path(raw_dir).resolve() != resolved:
            raise LocalSkillError("conflict", "Skill 安装路径无效", status_code=409)
    except OSError as exc:
        raise LocalSkillError("conflict", "无法验证 Skill 安装路径", status_code=409) from exc
    skill_path = resolved / "SKILL.md"
    if skill_path.is_symlink() or not skill_path.is_file():
        raise LocalSkillError("conflict", "Skill 安装路径无效", status_code=409)
    return skill_path


def _require_unmodified_original(skill_path: Path, package: dict[str, Any]) -> bytes:
    try:
        current = read_directory(skill_path.parent, check_types=False)
    except LocalSkillError as exc:
        raise LocalSkillError("local_modified", "本地 Skill 文件已修改，拒绝覆盖", status_code=409) from exc
    expected_files = package.get("files")
    if isinstance(expected_files, dict):
        actual_files = {path: hashlib.sha256(data).hexdigest()
                        for path, data in unpack(current, check_types=False).items()}
        matches = actual_files == expected_files
    else:
        matches = hashlib.sha256(current).hexdigest() == package.get("sha256")
    if not matches:
        raise LocalSkillError("local_modified", "本地 Skill 文件已修改，拒绝覆盖", status_code=409)
    return current


def _require_newer_version(remote_version: str, local_version: str) -> None:
    compared = compare_semver(remote_version, local_version)
    if compared == 1:
        return
    if compared == -1:
        raise LocalSkillError(
            "no_update",
            "远程版本不高于已安装版本",
            status_code=409,
        )
    if compared == 0:
        raise LocalSkillError(
            "no_update",
            "当前已是该版本，无需更新",
            status_code=409,
        )
    raise LocalSkillError(
        "no_update",
        "没有可安装的更新版本",
        status_code=409,
    )
