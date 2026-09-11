"""Provider-neutral settings section descriptors for Core and installed plugins."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

CORE_SECTION_IDS: tuple[str, ...] = (
    "appearance",
    "desktop",
    "models",
    "agent",
    "roundtable",
    "coding",
    "compression",
    "memory",
    "workspace",
    "system",
)

CORE_SECTION_ID_SET = frozenset(CORE_SECTION_IDS)

_CORE_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "appearance",
        "title": "外观",
        "owner": "core",
        "kind": "core",
        "order": 10,
        "description": "主题与界面外观。",
    },
    {
        "id": "desktop",
        "title": "桌面",
        "owner": "core",
        "kind": "core",
        "order": 20,
        "description": "桌面应用更新。",
    },
    {
        "id": "models",
        "title": "模型",
        "owner": "core",
        "kind": "core",
        "order": 30,
        "description": "模型供应商与可用模型。",
    },
    {
        "id": "agent",
        "title": "多 Agent",
        "owner": "core",
        "kind": "core",
        "order": 40,
        "description": "多 Agent 会话参数。",
    },
    {
        "id": "roundtable",
        "title": "圆桌",
        "owner": "core",
        "kind": "core",
        "order": 50,
        "description": "圆桌会议参数。",
    },
    {
        "id": "coding",
        "title": "编码工具",
        "owner": "core",
        "kind": "core",
        "order": 60,
        "description": "编码工具与工作区。",
    },
    {
        "id": "compression",
        "title": "压缩",
        "owner": "core",
        "kind": "core",
        "order": 70,
        "description": "会话压缩策略。",
    },
    {
        "id": "memory",
        "title": "记忆",
        "owner": "core",
        "kind": "core",
        "order": 80,
        "description": "长期记忆总开关与运行参数。",
    },
    {
        "id": "workspace",
        "title": "持久工作区",
        "owner": "core",
        "kind": "core",
        "order": 90,
        "description": "",
    },
    {
        "id": "system",
        "title": "系统",
        "owner": "core",
        "kind": "core",
        "order": 100,
        "description": "系统参数。",
    },
)

DEFAULT_PLUGIN_SECTION_ID = "settings"
DEFAULT_PLUGIN_SECTION_ORDER = 100


def plugin_descriptor_id(plugin_id: str, section_id: str) -> str:
    local_id = str(section_id or "").strip() or DEFAULT_PLUGIN_SECTION_ID
    return f"plugin:{plugin_id}:{local_id}"


def plugin_settings_section(
    plugin_id: str,
    manifest: Any,
) -> dict[str, Any] | None:
    """Build one plugin settings descriptor from an installed manifest."""

    owner = str(plugin_id or "").strip()
    if not owner:
        return None
    schema = str(getattr(manifest, "settings_schema", "") or "").strip()
    if not schema:
        return None
    section_id = str(getattr(manifest, "settings_section_id", "") or "").strip()
    if not section_id:
        section_id = DEFAULT_PLUGIN_SECTION_ID
    descriptor_id = plugin_descriptor_id(owner, section_id)
    if descriptor_id in CORE_SECTION_ID_SET:
        return None
    title = str(getattr(manifest, "settings_title", "") or "").strip()
    if not title:
        title = str(getattr(manifest, "name", "") or owner).strip() or owner
    description = str(getattr(manifest, "settings_description", "") or "").strip()
    if not description:
        description = str(getattr(manifest, "description", "") or "").strip()
    order = getattr(manifest, "settings_order", None)
    if not isinstance(order, int) or isinstance(order, bool):
        order = DEFAULT_PLUGIN_SECTION_ORDER
    return {
        "id": descriptor_id,
        "title": title,
        "owner": owner,
        "kind": "plugin",
        "order": order,
        "description": description,
        "plugin_id": owner,
    }


def collect_plugin_sections(management: Any) -> list[dict[str, Any]]:
    if management is None:
        return []
    getter = getattr(management, "iter_settings_section_manifests", None)
    if not callable(getter):
        return []
    sections: list[dict[str, Any]] = []
    items = getter()
    for item in items or ():
        if not isinstance(item, Sequence) or len(item) != 2:
            continue
        plugin_id, manifest = item
        section = plugin_settings_section(str(plugin_id), manifest)
        if section is not None:
            sections.append(section)
    return sections


def list_settings_sections(
    plugin_sections: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return Core sections plus plugin descriptors, sorted by order then id."""

    sections = [dict(item) for item in _CORE_SECTIONS]
    seen = {str(item["id"]) for item in sections}
    for raw in plugin_sections or ():
        if not isinstance(raw, Mapping):
            continue
        section = dict(raw)
        descriptor_id = str(section.get("id") or "").strip()
        if not descriptor_id or descriptor_id in seen or descriptor_id in CORE_SECTION_ID_SET:
            continue
        if str(section.get("kind") or "") != "plugin":
            continue
        plugin_id = str(section.get("plugin_id") or "").strip()
        if not plugin_id:
            continue
        section["owner"] = plugin_id
        section["kind"] = "plugin"
        sections.append(section)
        seen.add(descriptor_id)
    sections.sort(key=lambda item: (int(item.get("order") or 0), str(item.get("id") or "")))
    return sections
