import {
  CORE_SECTION_IDS,
  type CoreSectionId,
  type SettingsSection,
  type SettingsSectionKind,
} from "./types";

export const CORE_SECTION_ID_SET = new Set<string>(CORE_SECTION_IDS);

export const CORE_FALLBACK_SECTIONS: SettingsSection[] = [
  { id: "appearance", title: "外观", owner: "core", kind: "core", order: 10, description: "" },
  { id: "desktop", title: "桌面应用", owner: "core", kind: "core", order: 20, description: "" },
  { id: "models", title: "模型", owner: "core", kind: "core", order: 30, description: "" },
  { id: "agent", title: "多 Agent", owner: "core", kind: "core", order: 40, description: "" },
  { id: "roundtable", title: "圆桌", owner: "core", kind: "core", order: 50, description: "" },
  { id: "coding", title: "编码工具", owner: "core", kind: "core", order: 60, description: "" },
  { id: "compression", title: "压缩", owner: "core", kind: "core", order: 70, description: "" },
  { id: "memory", title: "记忆", owner: "core", kind: "core", order: 80, description: "" },
  { id: "workspace", title: "持久工作区", owner: "core", kind: "core", order: 90, description: "" },
  { id: "system", title: "系统", owner: "core", kind: "core", order: 100, description: "" },
];

export function isCoreSectionId(id: string): id is CoreSectionId {
  return CORE_SECTION_ID_SET.has(id);
}

export function pluginSectionId(pluginId: string, localId = "settings"): string {
  return `plugin:${pluginId}:${localId || "settings"}`;
}

export function parsePluginSectionId(
  id: string,
): { pluginId: string; localId: string } | null {
  if (!id.startsWith("plugin:")) return null;
  const rest = id.slice("plugin:".length);
  const separator = rest.lastIndexOf(":");
  if (separator <= 0 || separator === rest.length - 1) return null;
  return {
    pluginId: rest.slice(0, separator),
    localId: rest.slice(separator + 1),
  };
}

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asKind(value: unknown): SettingsSectionKind | null {
  return value === "core" || value === "plugin" ? value : null;
}

function readSection(value: unknown): SettingsSection | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const id = asString(record.id)?.trim();
  const title = asString(record.title)?.trim();
  const owner = asString(record.owner)?.trim();
  const kind = asKind(record.kind);
  const order = record.order;
  if (!id || !title || !owner || !kind || typeof order !== "number" || !Number.isInteger(order)) {
    return null;
  }
  const description = asString(record.description) ?? "";
  if (kind === "plugin") {
    const pluginId = asString(record.plugin_id)?.trim();
    if (!pluginId) return null;
    return {
      id,
      title,
      owner,
      kind,
      order,
      description,
      plugin_id: pluginId,
    };
  }
  return { id, title, owner, kind, order, description };
}

export function readSettingsSections(payload: unknown): SettingsSection[] {
  const sections = payload && typeof payload === "object"
    ? (payload as { sections?: unknown }).sections
    : undefined;
  if (!Array.isArray(sections)) return [];
  const seen = new Set<string>();
  const parsed: SettingsSection[] = [];
  for (const item of sections) {
    const section = readSection(item);
    if (!section || seen.has(section.id)) continue;
    seen.add(section.id);
    parsed.push(section);
  }
  return parsed.sort((left, right) => (
    left.order === right.order
      ? left.id.localeCompare(right.id)
      : left.order - right.order
  ));
}

export function resolveSelectedSection(
  sections: SettingsSection[],
  requested: string | null,
): SettingsSection | null {
  if (sections.length === 0) return null;
  if (!requested) return sections[0];
  const exact = sections.find((section) => section.id === requested);
  if (exact) return exact;
  const parsed = parsePluginSectionId(requested);
  if (!parsed) return sections[0];
  const pluginSections = sections.filter((section) => (
    section.kind === "plugin" && section.plugin_id === parsed.pluginId
  ));
  if (pluginSections.length === 1) return pluginSections[0];
  return pluginSections.find((section) => {
    const local = parsePluginSectionId(section.id);
    return local?.localId === parsed.localId;
  }) ?? sections[0];
}

export function settingsDeepLink(sectionId: string): { tab: string; section: string } {
  return { tab: "settings", section: sectionId };
}
