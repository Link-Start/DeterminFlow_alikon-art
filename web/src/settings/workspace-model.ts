import type { SettingsFieldGroup } from "./types";

export interface WorkspaceSettings {
  enabled: boolean;
  provider_id: string;
  context_enabled: boolean;
  context_token_budget: number;
  timeout_seconds: number;
  local_main_enabled: boolean;
}

export interface WorkspaceSettingsResponse {
  settings: WorkspaceSettings;
  providers: { id: string; name: string; healthy: boolean; reason: string }[];
  effective_enabled: boolean;
  reason: string;
}

export function readWorkspaceSettings(payload: unknown): WorkspaceSettingsResponse {
  if (!payload || typeof payload !== "object") throw new Error("工作区配置响应无效");
  const value = payload as WorkspaceSettingsResponse;
  const settings = value.settings;
  if (!settings || typeof settings.enabled !== "boolean" || typeof settings.provider_id !== "string"
      || typeof settings.context_enabled !== "boolean" || typeof settings.local_main_enabled !== "boolean"
      || !Number.isInteger(settings.context_token_budget) || !Number.isFinite(settings.timeout_seconds)
      || !Array.isArray(value.providers) || typeof value.effective_enabled !== "boolean"
      || typeof value.reason !== "string" || value.providers.some((provider) => (
        !provider || typeof provider.id !== "string" || typeof provider.name !== "string"
        || typeof provider.healthy !== "boolean" || typeof provider.reason !== "string"
      ))) throw new Error("工作区配置响应无效");
  return value;
}

export function workspaceFieldGroups(snapshot: WorkspaceSettingsResponse): SettingsFieldGroup[] {
  return [{ id: "workspace", title: "", fields: [
    { id: "provider_id", label: "工作区插件", kind: "select", options: snapshot.providers.map((provider) => ({ value: provider.id, label: provider.name })) },
    { id: "enabled", label: "启用持久工作区", kind: "boolean" },
    { id: "context_enabled", label: "自动加载上下文", kind: "boolean" },
    { id: "context_token_budget", label: "上下文预算（估算 token）", kind: "integer", min: 256, max: 8000 },
    { id: "timeout_seconds", label: "操作超时（秒）", kind: "number", min: 1, max: 120 },
    { id: "local_main_enabled", label: "允许本地 Main 接入", kind: "boolean", description: "仍需在 Agent 配置中显式启用工作区。" },
  ] }];
}
