export const CORE_SECTION_IDS = [
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
] as const;

export type CoreSectionId = (typeof CORE_SECTION_IDS)[number];
export type SettingsSectionKind = "core" | "plugin";

export interface SettingsSection {
  id: string;
  title: string;
  owner: string;
  kind: SettingsSectionKind;
  order: number;
  description: string;
  plugin_id?: string;
}

export type SettingsFieldKind =
  | "boolean"
  | "number"
  | "integer"
  | "string"
  | "select"
  | "sensitive"
  | "multiline"
  | "string-array"
  | "readonly";

export interface SettingsFieldOption {
  value: string;
  label: string;
}

export interface SettingsFieldSpec {
  id: string;
  label: string;
  kind: SettingsFieldKind;
  description?: string;
  required?: boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: SettingsFieldOption[];
  scale?: number;
  suffix?: string;
  placeholder?: string;
  default?: unknown;
  readonly?: boolean;
}

export interface SettingsFieldGroup {
  id: string;
  title: string;
  description?: string;
  fields: SettingsFieldSpec[];
}

export type SettingsScalar = string | number | boolean;

export interface SettingsCategoryStore {
  id: string;
  title: string;
  dirty: boolean;
  requiresAdminToken?: boolean;
  save: () => Promise<void>;
  discard: () => void;
}

export interface CategorySaveResult {
  id: string;
  title: string;
  ok: boolean;
  error?: string;
}

export type MemoryRecallMode = "first" | "every";

export interface MemorySettings {
  enabled: boolean;
  external_enabled: boolean;
  provider_id: string;
  auto_recall_enabled: boolean;
  auto_consolidate_enabled: boolean;
  recall_mode: MemoryRecallMode;
  recall_timeout_seconds: number;
  recall_max_chars: number;
  recall_max_bytes: number;
  consolidate_idle_seconds: number;
  consolidate_length_tokens: number;
  max_batch_turns: number;
  max_concurrent_jobs: number;
  max_retries: number;
  lease_seconds: number;
  extract_timeout_seconds: number;
  extract_model: string;
}

export interface MemoryProviderStatus {
  id: string;
  name: string;
  status: string;
  healthy: boolean;
  reason: string;
}

export interface MemorySettingsResponse {
  settings: MemorySettings;
  providers: MemoryProviderStatus[];
  effective_enabled: boolean;
  reason: string;
  schema?: unknown;
}

export interface CompressionConfig {
  general: {
    compactionThreshold: number;
    enabled: boolean;
  };
  micro_compact: {
    maxToolResults: number;
    toolResultTokenRatio: number;
    keepRecentToolResults: number;
    placeholder: string;
  };
  full_compact: {
    keepRecentTokens: number;
    maxRetryCount: number;
    summaryTokenBudget: number;
  };
  reactive_compact: {
    maxRetryCount: number;
  };
  post_compact: {
    maxFilesToRead: number;
    maxTokensPerFile: number;
  };
  transcript: {
    logsDir: string;
  };
}

export interface MemoryPluginSnapshot {
  id: string;
  runtime_status: string;
  active_enabled: boolean;
  desired_enabled: boolean;
  pending_action: string | null;
  restart_required: boolean;
}
