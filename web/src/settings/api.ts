import { request } from "../lib/http-client";
import { CORE_FALLBACK_SECTIONS, readSettingsSections } from "./section-model";
import { readMemorySettingsResponse } from "./memory-model";
import type {
  CompressionConfig,
  MemorySettings,
  MemorySettingsResponse,
  SettingsSection,
} from "./types";

export async function fetchSettingsSections(): Promise<SettingsSection[]> {
  const payload = await request<unknown>("/settings/sections");
  const sections = readSettingsSections(payload);
  return sections.length > 0 ? sections : CORE_FALLBACK_SECTIONS;
}

export async function fetchMemorySettings(): Promise<MemorySettingsResponse> {
  const payload = await request<unknown>("/memory/settings");
  const parsed = readMemorySettingsResponse(payload);
  if (!parsed) throw new Error("记忆配置响应无效");
  return parsed;
}

export async function updateMemorySettings(
  settings: MemorySettings,
  adminToken = "",
): Promise<MemorySettingsResponse> {
  const payload = await request<unknown>("/memory/settings", {
    method: "PUT",
    headers: adminToken.trim() ? { Authorization: `Bearer ${adminToken.trim()}` } : undefined,
    body: JSON.stringify({ settings }),
  });
  const parsed = readMemorySettingsResponse(payload);
  if (!parsed) throw new Error("记忆配置保存响应无效");
  return parsed;
}

export async function fetchCompressionConfig(): Promise<CompressionConfig> {
  return request<CompressionConfig>("/compression/config");
}

export async function updateCompressionConfig(
  config: CompressionConfig,
): Promise<void> {
  await request("/compression/config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}
