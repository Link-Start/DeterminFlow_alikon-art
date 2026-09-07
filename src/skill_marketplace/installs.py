"""Atomic first-time installation of a marketplace Skill."""

from __future__ import annotations

import shutil
from typing import Any

from .errors import LocalSkillError
from .local_skills import install_skill_atomically
from .packages import (
    pin_remote_skill,
    require_public_id,
    require_publisher_id,
    require_sha256,
    verify_downloaded_skill,
)


async def install_marketplace_skill(
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
        if service.skill_manager.config_manager is None:
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
        if service._installation_state(detail)["status"] != "available":
            raise LocalSkillError("already_exists", "本地已存在同名 Skill", status_code=409)
        content, header_sha256 = await marketplace.download_skill(slug)
        skill_id = verify_downloaded_skill(
            content,
            slug=slug,
            expected_sha256=expected_sha256,
            header_sha256=header_sha256,
            declared_name=remote.skill_name,
        )
        actual_sha256 = expected_sha256

        target = service.skill_manager.marketplace_skills_dir / skill_id
        if target.exists() or service.skill_manager.get_skill(skill_id) is not None:
            raise LocalSkillError("already_exists", "本地已存在同名 Skill", status_code=409)
        install_skill_atomically(target, content)
        provenance_recorded = False
        try:
            resource_id = require_public_id(remote.resource_id, "resource_id")
            version_id = require_public_id(remote.version_id, "version_id")
            publisher_id = require_publisher_id(remote.publisher_id)
            service.skill_manager.provenance_store.record(
                "skill",
                skill_id,
                source={
                    "kind": "marketplace",
                    "registry": marketplace.base_url,
                    "resource_id": resource_id,
                    "version_id": version_id,
                    "publisher_id": publisher_id,
                    "resource_type": remote.resource_type,
                    "functional_category": remote.functional_category,
                },
                package={
                    "version": remote.version,
                    "sha256": actual_sha256,
                    "license": remote.license,
                },
            )
            provenance_recorded = True
            config = service.skill_manager.config_manager
            if config is None:
                raise OSError("skill configuration became unavailable")
            if not config.set_enabled(skill_id, True):
                raise OSError("failed to persist enabled state")
            if not config.set_auto_inject(skill_id, True):
                raise OSError("failed to persist auto-inject state")
            service.skill_manager.reload()
            installed = service.skill_manager.get_skill(skill_id)
            if installed is None:
                raise OSError("installed skill missing after reload")
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            if provenance_recorded:
                service.skill_manager.provenance_store.remove("skill", skill_id)
            config = service.skill_manager.config_manager
            if config is not None:
                config.remove_skill(skill_id)
            service.skill_manager.reload()
            raise
    installed = service.skill_manager.get_skill(skill_id)
    enabled = bool(installed is not None and installed.enabled)
    return {
        "installed": True,
        "skill_id": skill_id,
        "version": remote.version or None,
        "sha256": actual_sha256,
        "enabled": enabled,
        "provenance": service.skill_manager.provenance_store.get("skill", skill_id),
        "installation": service._installation_state(detail),
    }
