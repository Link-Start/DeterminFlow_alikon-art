export const CORE_TAB_IDS = [
  "chat",
  "dashboard",
  "graph",
  "roundtable",
  "orchestration",
  "workflow",
  "cron",
  "marketplace",
  "skills",
  "rules",
  "system-prompt",
  "settings",
  "extensions",
] as const;

export type CoreTabId = (typeof CORE_TAB_IDS)[number];

export type CorePageScrollMode = "contained" | "document";

/**
 * contained 页面自己管理内部面板滚动；document 页面由 App Shell 提供唯一页面滚动容器。
 */
export const CORE_PAGE_SCROLL_MODE: Record<CoreTabId, CorePageScrollMode> = {
  chat: "contained",
  dashboard: "contained",
  graph: "contained",
  roundtable: "contained",
  orchestration: "contained",
  workflow: "contained",
  cron: "document",
  marketplace: "contained",
  skills: "document",
  rules: "document",
  "system-prompt": "document",
  settings: "document",
  extensions: "document",
};

const CORE_TAB_ID_SET = new Set<string>(CORE_TAB_IDS);

export function isCoreTabId(value: string): value is CoreTabId {
  return CORE_TAB_ID_SET.has(value);
}
