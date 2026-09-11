import type {
  MemoryPluginSnapshot,
  MemoryProviderStatus,
  MemoryRecallMode,
  MemorySettings,
  MemorySettingsResponse,
} from "./types";

const MEMORY_KEYS = [
  "enabled",
  "external_enabled",
  "provider_id",
  "auto_recall_enabled",
  "recall_mode",
  "recall_timeout_seconds",
  "recall_max_chars",
  "recall_max_bytes",
  "auto_consolidate_enabled",
  "consolidate_idle_seconds",
  "consolidate_length_tokens",
  "max_batch_turns",
  "max_concurrent_jobs",
  "max_retries",
  "lease_seconds",
  "extract_timeout_seconds",
  "extract_model",
] as const;

type MemoryKey = (typeof MEMORY_KEYS)[number];

export const MEMORY_FIELD_LIMITS: Record<string, { min?: number; max?: number; step?: number }> = {
  recall_timeout_seconds: { min: 0.1, max: 60, step: 0.1 },
  recall_max_chars: { min: 1, max: 100000, step: 1 },
  recall_max_bytes: { min: 1, max: 200000, step: 1 },
  consolidate_idle_seconds: { min: 0, max: 86400, step: 1 },
  consolidate_length_tokens: { min: 1, max: 1000000, step: 1 },
  max_batch_turns: { min: 1, max: 100, step: 1 },
  max_concurrent_jobs: { min: 1, max: 32, step: 1 },
  max_retries: { min: 0, max: 20, step: 1 },
  lease_seconds: { min: 1, max: 3600, step: 1 },
  extract_timeout_seconds: { min: 1, max: 300, step: 1 },
};

export const MEMORY_FIELD_LABELS: Record<MemoryKey, string> = {
  enabled: "启用记忆",
  external_enabled: "启用外部记忆",
  provider_id: "记忆提供者",
  auto_recall_enabled: "自动召回",
  recall_mode: "召回时机",
  recall_timeout_seconds: "召回超时（秒）",
  recall_max_chars: "召回最大字符",
  recall_max_bytes: "召回最大字节",
  auto_consolidate_enabled: "自动整理",
  consolidate_idle_seconds: "整理空闲秒数",
  consolidate_length_tokens: "整理触发 token 数",
  max_batch_turns: "每批最大轮次",
  max_concurrent_jobs: "最大并发任务",
  max_retries: "最大重试次数",
  lease_seconds: "任务租约（秒）",
  extract_timeout_seconds: "提取超时（秒）",
  extract_model: "提取模型",
};

function isRecallMode(value: unknown): value is MemoryRecallMode {
  return value === "first" || value === "every";
}

function readBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function readMemorySettings(value: unknown): MemorySettings | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const enabled = readBoolean(record.enabled);
  const externalEnabled = readBoolean(record.external_enabled);
  const providerId = readString(record.provider_id);
  const autoRecall = readBoolean(record.auto_recall_enabled);
  const recallMode = isRecallMode(record.recall_mode) ? record.recall_mode : null;
  const recallTimeout = readNumber(record.recall_timeout_seconds);
  const recallMaxChars = readNumber(record.recall_max_chars);
  const recallMaxBytes = readNumber(record.recall_max_bytes);
  const autoConsolidate = readBoolean(record.auto_consolidate_enabled);
  const consolidateIdle = readNumber(record.consolidate_idle_seconds);
  const consolidateLength = readNumber(record.consolidate_length_tokens);
  const maxBatchTurns = readNumber(record.max_batch_turns);
  const maxConcurrentJobs = readNumber(record.max_concurrent_jobs);
  const maxRetries = readNumber(record.max_retries);
  const leaseSeconds = readNumber(record.lease_seconds);
  const extractTimeout = readNumber(record.extract_timeout_seconds);
  const extractModel = readString(record.extract_model);
  if (
    enabled == null
    || externalEnabled == null
    || providerId == null
    || autoRecall == null
    || recallMode == null
    || recallTimeout == null
    || recallMaxChars == null
    || recallMaxBytes == null
    || autoConsolidate == null
    || consolidateIdle == null
    || consolidateLength == null
    || maxBatchTurns == null
    || maxConcurrentJobs == null
    || maxRetries == null
    || leaseSeconds == null
    || extractTimeout == null
    || extractModel == null
  ) {
    return null;
  }
  return {
    enabled,
    external_enabled: externalEnabled,
    provider_id: providerId,
    auto_recall_enabled: autoRecall,
    recall_mode: recallMode,
    recall_timeout_seconds: recallTimeout,
    recall_max_chars: recallMaxChars,
    recall_max_bytes: recallMaxBytes,
    auto_consolidate_enabled: autoConsolidate,
    consolidate_idle_seconds: consolidateIdle,
    consolidate_length_tokens: consolidateLength,
    max_batch_turns: maxBatchTurns,
    max_concurrent_jobs: maxConcurrentJobs,
    max_retries: maxRetries,
    lease_seconds: leaseSeconds,
    extract_timeout_seconds: extractTimeout,
    extract_model: extractModel,
  };
}

function readProvider(value: unknown): MemoryProviderStatus | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const id = readString(record.id);
  const name = readString(record.name);
  const status = readString(record.status);
  const reason = readString(record.reason);
  if (!id || name == null || status == null || reason == null) return null;
  if (typeof record.healthy !== "boolean") return null;
  return { id, name, status, healthy: record.healthy, reason };
}

export function readMemorySettingsResponse(value: unknown): MemorySettingsResponse | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const settings = readMemorySettings(record.settings);
  if (!settings || !Array.isArray(record.providers)) return null;
  if (typeof record.effective_enabled !== "boolean") return null;
  const reason = readString(record.reason);
  if (reason == null) return null;
  const providers = record.providers.map(readProvider);
  if (providers.some((item) => item == null)) return null;
  return {
    settings,
    providers: providers as MemoryProviderStatus[],
    effective_enabled: record.effective_enabled,
    reason,
    schema: record.schema,
  };
}

export function selectedMemoryProvider(
  providers: MemoryProviderStatus[],
  providerId: string,
): MemoryProviderStatus | undefined {
  return providers.find((provider) => provider.id === providerId);
}

export function describeMemoryEnableGate(args: {
  settings: Pick<MemorySettings, "enabled" | "external_enabled" | "provider_id">;
  providers: MemoryProviderStatus[];
  plugins: MemoryPluginSnapshot[];
}): { blocked: boolean; reason: string | null } {
  if (!args.settings.enabled || !args.settings.external_enabled) {
    return { blocked: false, reason: null };
  }
  if (!args.settings.provider_id.trim()) {
    return { blocked: true, reason: "启用外部记忆前需要选择已注册的提供者" };
  }
  const provider = selectedMemoryProvider(args.providers, args.settings.provider_id);
  const plugin = args.plugins.find((item) => item.id === args.settings.provider_id);
  if (!plugin) {
    return { blocked: true, reason: "所选提供者插件未安装，关闭记忆仍可保存" };
  }
  if (plugin.pending_action === "remove") {
    return { blocked: true, reason: "提供者已安排卸载，关闭记忆仍可保存" };
  }
  if (!plugin.desired_enabled) {
    return { blocked: true, reason: "提供者已安排停用，关闭记忆仍可保存" };
  }
  if (!plugin.active_enabled || plugin.runtime_status !== "running") {
    return { blocked: true, reason: "提供者当前未在运行，关闭记忆仍可保存" };
  }
  if (plugin.restart_required) {
    return { blocked: true, reason: "提供者有待生效的变更，请重启后再启用外部记忆；关闭记忆仍可保存" };
  }
  if (!provider?.healthy) {
    return { blocked: true, reason: provider?.reason || "提供者健康检查未通过，关闭记忆仍可保存" };
  }
  return { blocked: false, reason: null };
}

export function memoryActivationCopy(args: {
  effectiveEnabled: boolean;
  reason: string;
  plugin?: MemoryPluginSnapshot;
}): { label: string; detail: string | null } {
  const restart = args.plugin?.restart_required
    ? "提供者变更需要重启后才会进入新的运行状态"
    : null;
  if (args.effectiveEnabled) {
    return { label: "当前有效", detail: restart };
  }
  return {
    label: "当前未生效",
    detail: [args.reason, restart].filter(Boolean).join("。") || null,
  };
}
