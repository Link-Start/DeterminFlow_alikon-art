export const MARKETPLACE_BRIDGE_CHANNEL = "determinflow.marketplace.bridge";
export const MARKETPLACE_BRIDGE_VERSION = 1;
export const MARKETPLACE_BRIDGE_MAX_BYTES = 64 * 1024;
export const MARKETPLACE_BRIDGE_READY_TIMEOUT_MS = 15_000;
export const MARKETPLACE_IFRAME_SANDBOX = "allow-scripts allow-forms allow-same-origin allow-popups";

export const MARKETPLACE_BRIDGE_METHODS = [
  "status",
  "notification.show",
  "skills.list",
  "skills.page",
  "skills.get",
  "skills.preview",
  "reviews.list",
  "reviews.page",
  "favorite.set",
  "review.save",
  "review.delete",
  "review.report",
  "report.create",
  "report.open",
  "auth.login",
  "auth.logout",
  "localSkills.list",
  "localSkills.preview",
  "localSkills.previewPrepared",
  "skill.install",
  "skill.installPinned",
  "skill.updatePinned",
  "skill.openInstalled",
  "submissions.list",
  "skill.publish",
  "resource.publish",
  "resource.publishPinned",
  "resource.publishPrepared",
  "resource.withdraw",
  "review.resume",
  "skill.lifecycle",
  "author.resources.page",
  "author.versions.page",
  "feedback.page",
  "feedback.read",
  "publishDraft.get",
  "publishDraft.save",
  "publishDraft.delete",
] as const;

export type MarketplaceBridgeMethod = (typeof MARKETPLACE_BRIDGE_METHODS)[number];
export type MarketplaceBridgeApiMethod = Exclude<MarketplaceBridgeMethod, "notification.show" | "report.open">;

export const MARKETPLACE_BRIDGE_CONFIRM_METHODS = [
  "skill.install",
  "skill.installPinned",
  "skill.updatePinned",
  "skill.publish",
  "resource.publish",
  "resource.publishPinned",
  "resource.publishPrepared",
  "resource.withdraw",
  "review.delete",
  "review.resume",
  "skill.lifecycle",
] as const;

export type MarketplaceBridgeConfirmMethod =
  (typeof MARKETPLACE_BRIDGE_CONFIRM_METHODS)[number];

const METHOD_SET = new Set<string>(MARKETPLACE_BRIDGE_METHODS);
const CONFIRM_SET = new Set<string>(MARKETPLACE_BRIDGE_CONFIRM_METHODS);
const ENVELOPE_KEYS = new Set(["channel", "version", "type", "requestId", "method", "payload"]);
const FORBIDDEN_KEYS = new Set([
  "url",
  "path",
  "token",
  "href",
  "endpoint",
  "authorization",
  "access_token",
  "refresh_token",
  "accesstoken",
  "refreshtoken",
]);
const REPORT_REASONS = new Set(["security", "misleading", "copyright", "spam", "other"]);
const NOTIFICATION_VARIANTS = new Set(["default", "success", "error", "warning"]);
const AUTHOR_STATUSES = new Set([
  "all",
  "published",
  "pending",
  "changes",
  "suspended",
  "deprecated",
  "withdrawn",
]);
const REQUEST_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const PUBLIC_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FEEDBACK_ID_PATTERN = /^(?:submission|report):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const MARKETPLACE_BRIDGE_CANCELLED = {
  code: "cancelled",
  message: "已取消",
} as const;

export interface MarketplaceHostInit {
  locale: string;
  theme: "dark" | "light";
  capabilities: MarketplaceBridgeMethod[];
}

export interface MarketplaceConfirmPrompt {
  title: string;
  message: string;
  confirmLabel: string;
  destructive: boolean;
}

export type MarketplaceBridgeInspectResult =
  | { action: "drop" }
  | { action: "ready" }
  | { action: "cancel"; requestId: string }
  | {
    action: "request";
    requestId: string;
    method: MarketplaceBridgeMethod;
    payload: Record<string, unknown>;
  }
  | { action: "reject"; requestId: string | null; code: string; message: string };

export interface MarketplaceMessageEventLike {
  source: unknown;
  origin: string;
  data: unknown;
}

type PayloadField =
  | { kind: "string"; min?: number; max: number; codePoints?: boolean; required?: boolean; enum?: Set<string>; pattern?: RegExp }
  | { kind: "int"; min: number; max: number; required?: boolean; nullable?: boolean }
  | { kind: "boolean"; required?: boolean }
  | { kind: "object"; required?: boolean; fields: Record<string, PayloadField> };

const EMPTY_PAYLOAD: Record<string, PayloadField> = {};
const DRAFT_FIELDS: Record<string, PayloadField> = {
  license: { kind: "string", max: 32, required: true },
  display_name: { kind: "string", max: 80, required: true },
  author_name: { kind: "string", max: 80, required: true },
  summary: { kind: "string", max: 1024, required: true },
  functional_category: { kind: "string", max: 32, required: true },
  primary_locale: { kind: "string", max: 16, required: true },
  tags_csv: { kind: "string", max: 680, required: true },
  release_notes: { kind: "string", max: 2000, required: true },
  usage_guide: { kind: "string", max: 8000 },
};
const PUBLISH_FIELDS: Record<string, PayloadField> = {
  skill_id: { kind: "string", min: 1, max: 64, required: true },
  resource_type: { kind: "string", min: 1, max: 16, required: true, enum: new Set(["skill"]) },
  license: { kind: "string", min: 1, max: 32, required: true },
  rights_confirmed: { kind: "boolean", required: true },
  terms_confirmed: { kind: "boolean", required: true },
  terms_version: { kind: "string", min: 1, max: 32, required: true },
  display_name: { kind: "string", min: 1, max: 80, required: true },
  author_name: { kind: "string", max: 80, required: true },
  summary: { kind: "string", min: 1, max: 50, codePoints: true, required: true },
  functional_category: { kind: "string", min: 1, max: 32, required: true },
  primary_locale: { kind: "string", min: 1, max: 16, required: true },
  tags_csv: { kind: "string", max: 680, required: true },
  release_notes: { kind: "string", max: 150, codePoints: true, required: true },
  usage_guide: { kind: "string", max: 1000, codePoints: true },
};

const PAYLOAD_SCHEMAS: Record<MarketplaceBridgeMethod, Record<string, PayloadField>> = {
  status: EMPTY_PAYLOAD,
  "report.open": {
    slug: { kind: "string", min: 1, max: 64, required: true, pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/ },
    display_name: { kind: "string", max: 80 },
    review_id: { kind: "string", min: 36, max: 36, pattern: UUID_PATTERN },
    expected_updated_at: { kind: "string", min: 1, max: 64 },
  },
  "notification.show": {
    title: { kind: "string", min: 1, max: 120, required: true },
    detail: { kind: "string", max: 500 },
    variant: { kind: "string", max: 16, required: true, enum: NOTIFICATION_VARIANTS },
  },
  "skills.list": {
    query: { kind: "string", max: 64 },
    category: { kind: "string", max: 32 },
    sort: { kind: "string", max: 16 },
  },
  "skills.page": {
    query: { kind: "string", max: 64 },
    category: { kind: "string", max: 32 },
    sort: { kind: "string", max: 16 },
    page: { kind: "int", min: 1, max: 100000 },
    page_size: { kind: "int", min: 1, max: 100 },
    favorites: { kind: "boolean" },
  },
  "skills.get": { slug: { kind: "string", max: 64, required: true } },
  "skills.preview": {
    slug: { kind: "string", max: 64, required: true },
    expected_version_id: { kind: "string", min: 1, max: 128, required: true, pattern: PUBLIC_ID_PATTERN },
    expected_sha256: { kind: "string", min: 64, max: 64, required: true, pattern: SHA256_PATTERN },
  },
  "reviews.list": { slug: { kind: "string", max: 64, required: true } },
  "reviews.page": {
    slug: { kind: "string", max: 64, required: true },
    page: { kind: "int", min: 1, max: 100000 },
    page_size: { kind: "int", min: 1, max: 100 },
  },
  "favorite.set": {
    slug: { kind: "string", max: 64, required: true },
    favorited: { kind: "boolean", required: true },
  },
  "review.save": {
    slug: { kind: "string", max: 64, required: true },
    rating: { kind: "int", min: 1, max: 5, required: true },
    body: { kind: "string", max: 2000 },
  },
  "review.delete": {
    slug: { kind: "string", max: 64, required: true },
    review_id: { kind: "string", min: 36, max: 36, required: true, pattern: UUID_PATTERN },
    expected_updated_at: { kind: "string", min: 1, max: 64, required: true },
  },
  "review.report": {
    slug: { kind: "string", max: 64, required: true },
    review_id: { kind: "string", min: 36, max: 36, required: true, pattern: UUID_PATTERN },
    expected_updated_at: { kind: "string", min: 1, max: 64, required: true },
    reason: { kind: "string", max: 32, required: true, enum: REPORT_REASONS },
    details: { kind: "string", max: 2000 },
  },
  "report.create": {
    slug: { kind: "string", max: 64, required: true },
    reason: { kind: "string", max: 32, required: true, enum: REPORT_REASONS },
    details: { kind: "string", max: 2000 },
  },
  "auth.login": EMPTY_PAYLOAD,
  "auth.logout": EMPTY_PAYLOAD,
  "localSkills.list": EMPTY_PAYLOAD,
  "localSkills.preview": { skill_id: { kind: "string", max: 64, required: true } },
  "localSkills.previewPrepared": {
    skill_id: { kind: "string", max: 64, required: true },
    target_slug: { kind: "string", min: 1, max: 64, pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/ },
    publication_version: { kind: "string", min: 1, max: 64, required: true },
  },
  "skill.install": { slug: { kind: "string", max: 64, required: true } },
  "skill.openInstalled": { slug: { kind: "string", max: 64, required: true } },
  "skill.installPinned": {
    slug: { kind: "string", max: 64, required: true },
    expected_version_id: { kind: "string", min: 1, max: 128, required: true, pattern: PUBLIC_ID_PATTERN },
    expected_sha256: { kind: "string", min: 64, max: 64, required: true, pattern: SHA256_PATTERN },
  },
  "skill.updatePinned": {
    slug: { kind: "string", max: 64, required: true },
    expected_version_id: { kind: "string", min: 1, max: 128, required: true, pattern: PUBLIC_ID_PATTERN },
    expected_sha256: { kind: "string", min: 64, max: 64, required: true, pattern: SHA256_PATTERN },
  },
  "submissions.list": EMPTY_PAYLOAD,
  "skill.publish": {
    skill_id: { kind: "string", max: 64, required: true },
    license: { kind: "string", max: 32, required: true },
    rights_confirmed: { kind: "boolean", required: true },
  },
  "resource.publish": PUBLISH_FIELDS,
  "resource.publishPinned": {
    ...PUBLISH_FIELDS,
    expected_sha256: { kind: "string", min: 64, max: 64, required: true, pattern: SHA256_PATTERN },
  },
  "resource.publishPrepared": {
    ...PUBLISH_FIELDS,
    expected_sha256: { kind: "string", min: 64, max: 64, required: true, pattern: SHA256_PATTERN },
    target_slug: { kind: "string", min: 1, max: 64, pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/ },
    publication_version: { kind: "string", min: 1, max: 64, required: true },
  },
  "resource.withdraw": {
    version_id: { kind: "string", min: 1, max: 64, required: true },
  },
  "review.resume": {
    slug: { kind: "string", min: 1, max: 64, required: true },
    expected_version_id: { kind: "string", min: 1, max: 64, required: true },
    reason: { kind: "string", min: 1, max: 1000, required: true },
  },
  "skill.lifecycle": {
    slug: { kind: "string", max: 64, required: true },
    deprecated: { kind: "boolean", required: true },
    replacement_slug: { kind: "string", max: 64 },
    message: { kind: "string", max: 1000 },
  },
  "author.resources.page": {
    query: { kind: "string", max: 64 },
    status: { kind: "string", max: 32, enum: AUTHOR_STATUSES },
    page: { kind: "int", min: 1, max: 100000 },
    page_size: { kind: "int", min: 1, max: 100 },
  },
  "author.versions.page": {
    slug: { kind: "string", max: 64, required: true },
    page: { kind: "int", min: 1, max: 100000 },
    page_size: { kind: "int", min: 1, max: 100 },
  },
  "feedback.page": {
    page: { kind: "int", min: 1, max: 100000 },
    page_size: { kind: "int", min: 1, max: 100 },
    unread_only: { kind: "boolean" },
  },
  "feedback.read": {
    id: { kind: "string", min: 1, max: 80, required: true, pattern: FEEDBACK_ID_PATTERN },
    expected_updated_at: { kind: "string", min: 1, max: 64, required: true },
  },
  "publishDraft.get": { skill_id: { kind: "string", max: 64, required: true } },
  "publishDraft.save": {
    skill_id: { kind: "string", max: 64, required: true },
    expected_revision: { kind: "int", min: 1, max: 2147483647, required: true, nullable: true },
    base_version: { kind: "string", max: 64, required: true },
    base_sha256: { kind: "string", min: 64, max: 64, required: true, pattern: SHA256_PATTERN },
    fields: { kind: "object", required: true, fields: DRAFT_FIELDS },
    source_skill_id: { kind: "string", max: 64 },
    publication_version: { kind: "string", max: 64 },
  },
  "publishDraft.delete": {
    skill_id: { kind: "string", max: 64, required: true },
    expected_revision: { kind: "int", min: 1, max: 2147483647, required: true },
  },
};

export function marketplaceBridgeTimeoutMs(method: MarketplaceBridgeMethod): number {
  if (method === "report.open") return 600_000;
  return method === "auth.login" ? 210_000 : 30_000;
}

export function methodRequiresConfirmation(
  method: string,
): method is MarketplaceBridgeConfirmMethod {
  return CONFIRM_SET.has(method);
}

export function isAllowedMarketplaceEmbedUrl(value: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return false;
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) return false;
  if (parsed.protocol === "https:") return Boolean(parsed.hostname);
  if (parsed.protocol !== "http:" || !parsed.hostname) return false;
  return isLoopbackHostname(parsed.hostname);
}

export function marketplaceEmbedOrigin(value: string): string | null {
  if (!isAllowedMarketplaceEmbedUrl(value)) return null;
  try {
    return new URL(value).origin;
  } catch {
    return null;
  }
}

export function isTrustedMarketplaceEvent(
  event: MarketplaceMessageEventLike,
  input: { contentWindow: unknown; expectedOrigin: string },
): boolean {
  return event.source === input.contentWindow
    && event.origin === input.expectedOrigin
    && Boolean(input.contentWindow)
    && Boolean(input.expectedOrigin);
}

export function marketplaceBridgeMessageBytes(data: unknown): number {
  try {
    return new TextEncoder().encode(JSON.stringify(data)).length;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}

export function inspectMarketplaceBridgeMessage(data: unknown): MarketplaceBridgeInspectResult {
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    return { action: "drop" };
  }
  if (marketplaceBridgeMessageBytes(data) > MARKETPLACE_BRIDGE_MAX_BYTES) {
    const requestId = readRequestId((data as Record<string, unknown>).requestId);
    return requestId
      ? { action: "reject", requestId, code: "too_large", message: "消息超出大小限制" }
      : { action: "drop" };
  }
  const envelope = data as Record<string, unknown>;
  if (hasForbiddenKeys(envelope)) {
    return rejectOrDrop(envelope, "invalid_message", "消息包含不允许的字段");
  }
  if (Object.keys(envelope).some((key) => !ENVELOPE_KEYS.has(key))) {
    return rejectOrDrop(envelope, "invalid_message", "消息字段无效");
  }
  if (envelope.channel !== MARKETPLACE_BRIDGE_CHANNEL) return { action: "drop" };
  if (envelope.version !== MARKETPLACE_BRIDGE_VERSION) {
    return rejectOrDrop(envelope, "unsupported_version", "不支持的 bridge 版本");
  }
  if (envelope.type === "ready") {
    if (envelope.requestId !== undefined || envelope.method !== undefined) {
      return { action: "drop" };
    }
    if (envelope.payload !== undefined && !isEmptyPayload(envelope.payload)) {
      return { action: "drop" };
    }
    return { action: "ready" };
  }
  if (envelope.type === "cancel") {
    const requestId = readRequestId(envelope.requestId);
    if (!requestId || envelope.method !== undefined || envelope.payload !== undefined) return { action: "drop" };
    return { action: "cancel", requestId };
  }
  if (envelope.type !== "request") return { action: "drop" };
  const requestId = readRequestId(envelope.requestId);
  if (!requestId) {
    return { action: "reject", requestId: null, code: "invalid_request", message: "requestId 无效" };
  }
  if (typeof envelope.method !== "string" || !METHOD_SET.has(envelope.method)) {
    return { action: "reject", requestId, code: "unsupported_method", message: "不支持的请求类型" };
  }
  const payloadResult = readPayload(
    envelope.method as MarketplaceBridgeMethod,
    envelope.payload,
  );
  if ("error" in payloadResult) {
    return { action: "reject", requestId, code: payloadResult.error.code, message: payloadResult.error.message };
  }
  return {
    action: "request",
    requestId,
    method: envelope.method as MarketplaceBridgeMethod,
    payload: payloadResult.payload,
  };
}

export function buildHostInitMessage(init: MarketplaceHostInit): Record<string, unknown> {
  return {
    channel: MARKETPLACE_BRIDGE_CHANNEL,
    version: MARKETPLACE_BRIDGE_VERSION,
    type: "host:init",
    payload: {
      locale: init.locale,
      theme: init.theme,
      capabilities: [...init.capabilities],
      request_lifecycle: true,
    },
  };
}

export function buildBridgeProgress(requestId: string, phase: "preparing" | "confirming" | "executing"): Record<string, unknown> {
  return { channel: MARKETPLACE_BRIDGE_CHANNEL, version: MARKETPLACE_BRIDGE_VERSION, type: "progress", requestId, phase };
}

export function buildBridgeResponse(requestId: string, payload: unknown): Record<string, unknown> {
  return {
    channel: MARKETPLACE_BRIDGE_CHANNEL,
    version: MARKETPLACE_BRIDGE_VERSION,
    type: "response",
    requestId,
    ok: true,
    payload,
  };
}

export function buildBridgeErrorResponse(
  requestId: string,
  code: string,
  message: string,
  extras?: { retry_after_seconds?: number },
): Record<string, unknown> {
  const error: Record<string, unknown> = { code, message };
  const retryAfter = extras?.retry_after_seconds;
  if (typeof retryAfter === "number" && Number.isInteger(retryAfter) && retryAfter >= 1 && retryAfter <= 3600) {
    error.retry_after_seconds = retryAfter;
  }
  return {
    channel: MARKETPLACE_BRIDGE_CHANNEL,
    version: MARKETPLACE_BRIDGE_VERSION,
    type: "response",
    requestId,
    ok: false,
    error,
  };
}

export function marketplaceConfirmPrompt(
  method: MarketplaceBridgeConfirmMethod,
  payload: Record<string, unknown>,
): MarketplaceConfirmPrompt {
  if (method === "skill.updatePinned") {
    return { title: "更新 Skill", message: `将更新 ${String(payload.display_name || payload.slug || "")} 到 ${String(payload.version || "")}，保留本地运行设置。`, confirmLabel: "更新", destructive: false };
  }
  if (method === "skill.install" || method === "skill.installPinned") {
    const name = String(payload.display_name || payload.slug || "");
    const version = String(payload.version || "");
    return {
      title: "安装到本机",
      message: `将安装并启用 ${name} ${version}，内容会自动注入适用对话的上下文。`,
      confirmLabel: "安装",
      destructive: false,
    };
  }
  if (method === "skill.publish" || method === "resource.publish" || method === "resource.publishPinned" || method === "resource.publishPrepared") {
    const skillId = String(payload.skill_id ?? "");
    return {
      title: "提交审核",
      message: `将提交 ${skillId} 到资源广场。已提交版本不能覆盖。`,
      confirmLabel: "提交",
      destructive: false,
    };
  }
  if (method === "resource.withdraw") {
    return {
      title: "撤回投稿",
      message: "撤回后该版本不再进入审核；如需重新投稿，请先提高版本号。",
      confirmLabel: "撤回",
      destructive: true,
    };
  }
  if (method === "review.delete") {
    return {
      title: "删除评价",
      message: "将删除该资源上的评分和评价正文。删除后不可恢复。",
      confirmLabel: "删除",
      destructive: true,
    };
  }
  if (method === "review.resume") {
    const slug = String(payload.slug ?? "");
    return {
      title: "恢复上架",
      message: `恢复 ${slug} 后，当前已通过版本会重新公开。`,
      confirmLabel: "恢复上架",
      destructive: false,
    };
  }
  const slug = String(payload.slug ?? "");
  if (payload.deprecated === true) {
    return {
      title: "弃用资源",
      message: `弃用 ${slug} 后，它不会出现在发现结果中。历史版本仍可访问。`,
      confirmLabel: "弃用",
      destructive: true,
    };
  }
  return {
    title: "恢复资源",
    message: `恢复 ${slug} 后，它会重新出现在发现结果中。`,
    confirmLabel: "恢复",
    destructive: false,
  };
}

function isLoopbackHostname(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host === "::1") return true;
  const parts = host.split(".");
  if (parts.length !== 4 || parts[0] !== "127") return false;
  return parts.every((part) => {
    if (!/^\d{1,3}$/.test(part)) return false;
    const value = Number(part);
    return value >= 0 && value <= 255;
  });
}

function hasForbiddenKeys(value: unknown, depth = 0): boolean {
  if (value === null || typeof value !== "object" || depth > 6) return false;
  if (Array.isArray(value)) {
    return value.some((item) => hasForbiddenKeys(item, depth + 1));
  }
  for (const key of Object.keys(value)) {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) return true;
    if (hasForbiddenKeys((value as Record<string, unknown>)[key], depth + 1)) return true;
  }
  return false;
}

function readRequestId(value: unknown): string | null {
  return typeof value === "string" && REQUEST_ID_PATTERN.test(value) ? value : null;
}

function isEmptyPayload(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  return typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0;
}

function readPayload(
  method: MarketplaceBridgeMethod,
  raw: unknown,
): { payload: Record<string, unknown> } | { error: { code: string; message: string } } {
  const result = readObjectPayload(PAYLOAD_SCHEMAS[method], raw);
  if (method === "report.open" && "payload" in result
    && (result.payload.review_id !== undefined) !== (result.payload.expected_updated_at !== undefined)) {
    return { error: { code: "invalid_payload", message: "评价举报缺少版本信息" } };
  }
  return result;
}

function readObjectPayload(
  schema: Record<string, PayloadField>,
  raw: unknown,
): { payload: Record<string, unknown> } | { error: { code: string; message: string } } {
  if (raw === undefined || raw === null) {
    raw = {};
  }
  if (typeof raw !== "object" || Array.isArray(raw)) {
    return { error: { code: "invalid_payload", message: "payload 无效" } };
  }
  if (hasForbiddenKeys(raw)) {
    return { error: { code: "invalid_payload", message: "payload 包含不允许的字段" } };
  }
  const record = raw as Record<string, unknown>;
  for (const key of Object.keys(record)) {
    if (!(key in schema)) {
      return { error: { code: "invalid_payload", message: "payload 字段无效" } };
    }
  }
  const payload: Record<string, unknown> = {};
  for (const [key, field] of Object.entries(schema)) {
    if (!(key in record)) {
      if (field.required) {
        return { error: { code: "invalid_payload", message: "payload 缺少必填字段" } };
      }
      continue;
    }
    const value = record[key];
    if (field.kind === "object") {
      const nested = readObjectPayload(field.fields, value);
      if ("error" in nested) return nested;
      payload[key] = nested.payload;
      continue;
    }
    if (field.kind === "string") {
      const length = typeof value === "string" ? (field.codePoints ? Array.from(value).length : value.length) : 0;
      if (typeof value !== "string" || length < (field.min ?? 0) || length > field.max) {
        return { error: { code: "invalid_payload", message: "payload 字段无效" } };
      }
      if (field.enum && !field.enum.has(value)) {
        return { error: { code: "invalid_payload", message: "payload 字段无效" } };
      }
      if (field.pattern && !field.pattern.test(value)) {
        return { error: { code: "invalid_payload", message: "payload 字段无效" } };
      }
      payload[key] = value;
      continue;
    }
    if (field.kind === "int") {
      if (value === null && field.nullable) {
        payload[key] = null;
        continue;
      }
      if (typeof value !== "number" || !Number.isInteger(value) || value < field.min || value > field.max) {
        return { error: { code: "invalid_payload", message: "payload 字段无效" } };
      }
      payload[key] = value;
      continue;
    }
    if (typeof value !== "boolean") {
      return { error: { code: "invalid_payload", message: "payload 字段无效" } };
    }
    payload[key] = value;
  }
  return { payload };
}

function rejectOrDrop(
  envelope: Record<string, unknown>,
  code: string,
  message: string,
): MarketplaceBridgeInspectResult {
  const requestId = readRequestId(envelope.requestId);
  return requestId
    ? { action: "reject", requestId, code, message }
    : { action: "drop" };
}
