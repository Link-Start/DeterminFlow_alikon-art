"""Local ownership is authoritative for marketplace installation state."""

from __future__ import annotations

import re
from typing import Any

from src.skills.manager import SkillManager

from .errors import LocalSkillError

SKILL_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def installation_state(
    detail: dict[str, Any],
    *,
    skill_manager: SkillManager,
    marketplace_url: str | None,
) -> dict[str, Any]:
    """Local ownership is authoritative; never relay a registry's local state."""
    resource = _mapping(detail.get("resource"))
    payload = _mapping(detail.get("payload"))
    skill_id = payload.get("name") or detail.get("skill_name") or resource.get("slug") or detail.get("slug")
    state: dict[str, Any] = {"status": "available", "version": None, "enabled": None}
    if not isinstance(skill_id, str) or not SKILL_ID_PATTERN.fullmatch(skill_id):
        return {**state, "status": "conflict"}
    skill = skill_manager.get_skill(skill_id)
    if skill is None:
        if (skill_manager.marketplace_skills_dir / skill_id).exists():
            state["status"] = "conflict"
        return state
    state.update(status="conflict", version=skill.version or None, enabled=skill.enabled)
    provenance = skill.metadata.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    source = _mapping(provenance.get("source"))
    if source.get("kind") == "core":
        state["status"] = "builtin"
    elif (
        source.get("kind") == "marketplace"
        and marketplace_url is not None
        and source.get("registry") == marketplace_url
        and source.get("resource_id") == remote_resource_id(detail)
        and source.get("resource_id") is not None
    ):
        state["status"] = "installed"
        local_version = skill.version or _package_version(provenance)
        comparison = compare_semver(remote_release_version(detail), local_version)
        if comparison is not None:
            state["update_available"] = comparison == 1
    return state


def resolve_openable_skill(
    slug: str,
    *,
    skill_manager: SkillManager,
    marketplace_url: str | None,
) -> str:
    if not SKILL_ID_PATTERN.fullmatch(slug):
        raise LocalSkillError("invalid_slug", "Skill 标识格式无效")
    skill = skill_manager.get_skill(slug)
    if skill is None:
        if (skill_manager.marketplace_skills_dir / slug).exists():
            raise LocalSkillError(
                "conflict",
                "本地存在同名但来源不同的 Skill",
                status_code=409,
            )
        raise LocalSkillError("not_found", "本地未安装该 Skill", status_code=404)
    provenance = skill.metadata.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    source = _mapping(provenance.get("source"))
    if source.get("kind") == "core":
        return slug
    if (
        source.get("kind") == "marketplace"
        and marketplace_url is not None
        and source.get("registry") == marketplace_url
    ):
        return slug
    raise LocalSkillError(
        "conflict",
        "本地存在同名但来源不同的 Skill",
        status_code=409,
    )


def remote_resource_id(detail: dict[str, Any]) -> Any:
    resource = _mapping(detail.get("resource"))
    return resource.get("id") or detail.get("resource_id")


def remote_release_version(detail: dict[str, Any]) -> str:
    resource = _mapping(detail.get("resource"))
    release = _mapping(resource.get("release"))
    version = (
        release.get("version")
        or detail.get("version")
        or detail.get("declared_version")
        or detail.get("version_number")
    )
    if not isinstance(version, str):
        return ""
    return version.strip()


def is_newer_semver(remote: str | None, local: str | None) -> bool:
    compared = compare_semver(remote, local)
    return compared == 1


def compare_semver(left: str | None, right: str | None) -> int | None:
    parsed_left = parse_semver(left)
    parsed_right = parse_semver(right)
    if parsed_left is None or parsed_right is None:
        return None
    if parsed_left > parsed_right:
        return 1
    if parsed_left < parsed_right:
        return -1
    return 0


def parse_semver(value: str | None) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]] | None:
    if not isinstance(value, str):
        return None
    match = _SEMVER_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    major, minor, patch, prerelease = match.groups()
    if prerelease is None:
        return (int(major), int(minor), int(patch), 1, ())
    parts: list[tuple[int, int | str]] = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            if len(identifier) > 1 and identifier.startswith("0"):
                return None
            parts.append((0, int(identifier)))
        else:
            parts.append((1, identifier))
    return (int(major), int(minor), int(patch), 0, tuple(parts))


def _package_version(provenance: dict[str, Any]) -> str:
    package = _mapping(provenance.get("package"))
    version = package.get("version")
    return version.strip() if isinstance(version, str) else ""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
