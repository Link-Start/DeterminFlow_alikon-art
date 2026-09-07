import { normalizeSubmission, type MarketplaceSubmission } from "./marketplace-submissions";
import { MarketplaceApiError, requestJson } from "./skill-marketplace-http";

export interface DraftFields {
  license: string;
  display_name: string;
  author_name: string;
  summary: string;
  usage_guide?: string;
  functional_category: string;
  primary_locale: string;
  tags_csv: string;
  release_notes: string;
}

export interface PublishDraft {
  schema_version: 1;
  skill_id: string;
  source_skill_id?: string;
  publication_version?: string;
  base_version: string;
  base_sha256: string;
  fields: DraftFields;
  revision: number;
  updated_at: string;
}

export interface SavePublishDraftPayload {
  skill_id: string;
  expected_revision: number | null;
  base_version: string;
  base_sha256: string;
  fields: DraftFields;
  source_skill_id?: string;
  publication_version?: string;
}

export interface DeletePublishDraftPayload {
  skill_id: string;
  expected_revision: number;
}

export interface LocalSkillPreview {
  content: string;
  sha256: string;
  source_sha256?: string;
  version: string;
  skill_id: string;
  name?: string;
}

export interface LocalSkillPreviewRequest {
  target_slug?: string;
  publication_version?: string;
}

export interface AuthorResource {
  slug: string;
  latest: MarketplaceSubmission;
  current: MarketplaceSubmission | null;
  candidate: MarketplaceSubmission | null;
}

export interface AuthorResourcePage {
  items: AuthorResource[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuthorListOptions {
  query?: string;
  status?: string;
  page?: number;
  page_size?: number;
}

export interface AuthorVersionListOptions {
  page?: number;
  page_size?: number;
}

export type FeedbackKind = "submission" | "report";
export type FeedbackStatus = "published" | "rejected" | "open" | "resolved" | "dismissed";

export interface FeedbackItem {
  id: string;
  kind: FeedbackKind;
  resource_slug: string;
  resource_name: string;
  version: string | null;
  status: FeedbackStatus;
  message: string;
  updated_at: string;
  unread: boolean;
}

export interface FeedbackPage {
  items: FeedbackItem[];
  total: number;
  page: number;
  page_size: number;
  unread_total: number;
}

export interface FeedbackListOptions {
  page?: number;
  page_size?: number;
  unread_only?: boolean;
}

export interface FeedbackReadPayload {
  id: string;
  expected_updated_at: string;
}

function requirePageEnvelope(body: Record<string, unknown>, message: string): {
  items: unknown[];
  total: number;
  page: number;
  page_size: number;
} {
  if (
    !body || !Array.isArray(body.items)
    || !boundedInt(body.total, 0, Number.MAX_SAFE_INTEGER)
    || !boundedInt(body.page, 1, 100_000)
    || !boundedInt(body.page_size, 1, 100)
    || body.items.length > body.page_size
  ) {
    throw new MarketplaceApiError("invalid_response", message);
  }
  return {
    items: body.items,
    total: body.total,
    page: body.page,
    page_size: body.page_size,
  };
}

function boundedInt(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max;
}

function requireSubmission(raw: unknown, message: string): MarketplaceSubmission {
  if (!raw || typeof raw !== "object") {
    throw new MarketplaceApiError("invalid_response", message);
  }
  const normalized = normalizeSubmission(raw as Record<string, unknown>);
  if (!normalized) {
    throw new MarketplaceApiError("invalid_response", message);
  }
  return normalized;
}

function normalizeAuthorResource(raw: unknown): AuthorResource {
  if (!raw || typeof raw !== "object") {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效作者资源");
  }
  const record = raw as Record<string, unknown>;
  if (typeof record.slug !== "string" || !record.slug) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效作者资源");
  }
  const latest = requireSubmission(record.latest, "资源广场返回了无效作者资源");
  const current = record.current == null
    ? null
    : requireSubmission(record.current, "资源广场返回了无效作者资源");
  const candidate = record.candidate == null
    ? null
    : requireSubmission(record.candidate, "资源广场返回了无效作者资源");
  return { slug: record.slug, latest, current, candidate };
}

const DRAFT_FIELD_KEYS = [
  "license",
  "display_name",
  "author_name",
  "summary",
  "functional_category",
  "primary_locale",
  "tags_csv",
  "release_notes",
] as const;

function normalizeDraftFields(raw: unknown): DraftFields {
  if (!raw || typeof raw !== "object") {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效草稿");
  }
  const record = raw as Record<string, unknown>;
  const fields = {} as DraftFields;
  for (const key of DRAFT_FIELD_KEYS) {
    const value = record[key];
    if (typeof value !== "string") {
      throw new MarketplaceApiError("invalid_response", "资源广场返回了无效草稿");
    }
    fields[key] = value;
  }
  fields.usage_guide = typeof record.usage_guide === "string" ? record.usage_guide : "";
  return fields;
}

function normalizePublishDraft(raw: unknown): PublishDraft {
  if (!raw || typeof raw !== "object") {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效草稿");
  }
  const record = raw as Record<string, unknown>;
  if (
    record.schema_version !== 1
    || typeof record.skill_id !== "string"
    || typeof record.base_version !== "string"
    || typeof record.base_sha256 !== "string"
    || typeof record.revision !== "number"
    || !Number.isInteger(record.revision)
    || record.revision < 1
    || typeof record.updated_at !== "string"
  ) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效草稿");
  }
  return {
    schema_version: 1,
    skill_id: record.skill_id,
    ...(typeof record.source_skill_id === "string" ? { source_skill_id: record.source_skill_id } : {}),
    ...(typeof record.publication_version === "string" ? { publication_version: record.publication_version } : {}),
    base_version: record.base_version,
    base_sha256: record.base_sha256,
    fields: normalizeDraftFields(record.fields),
    revision: record.revision,
    updated_at: record.updated_at,
  };
}

const FEEDBACK_KINDS = new Set<FeedbackKind>(["submission", "report"]);
const FEEDBACK_STATUSES = new Set<FeedbackStatus>([
  "published",
  "rejected",
  "open",
  "resolved",
  "dismissed",
]);

function normalizeFeedbackItem(raw: unknown): FeedbackItem {
  if (!raw || typeof raw !== "object") {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效反馈");
  }
  const record = raw as Record<string, unknown>;
  if (
    typeof record.id !== "string"
    || typeof record.kind !== "string"
    || !FEEDBACK_KINDS.has(record.kind as FeedbackKind)
    || typeof record.resource_slug !== "string"
    || typeof record.resource_name !== "string"
    || (record.version !== null && typeof record.version !== "string")
    || typeof record.status !== "string"
    || !FEEDBACK_STATUSES.has(record.status as FeedbackStatus)
    || typeof record.message !== "string"
    || typeof record.updated_at !== "string"
    || typeof record.unread !== "boolean"
  ) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效反馈");
  }
  return {
    id: record.id,
    kind: record.kind as FeedbackKind,
    resource_slug: record.resource_slug,
    resource_name: record.resource_name,
    version: typeof record.version === "string" ? record.version : null,
    status: record.status as FeedbackStatus,
    message: record.message,
    updated_at: record.updated_at,
    unread: record.unread,
  };
}

export async function listAuthorResources(
  options: AuthorListOptions = {},
): Promise<AuthorResourcePage> {
  const params = new URLSearchParams();
  const query = options.query?.trim() ?? "";
  if (query) params.set("q", query);
  if (options.status && options.status !== "all") params.set("status", options.status);
  params.set("page", String(options.page ?? 1));
  params.set("page_size", String(options.page_size ?? 20));
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/author/resources?${params.toString()}`,
  );
  const page = requirePageEnvelope(body, "资源广场返回了无效作者资源分页");
  return {
    ...page,
    items: page.items.map(normalizeAuthorResource),
  };
}

export async function listAuthorVersions(
  slug: string,
  options: AuthorVersionListOptions = {},
): Promise<{ items: MarketplaceSubmission[]; total: number; page: number; page_size: number }> {
  const params = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.page_size ?? 20),
  });
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/author/resources/${encodeURIComponent(slug)}/versions?${params.toString()}`,
  );
  const page = requirePageEnvelope(body, "资源广场返回了无效作者版本分页");
  return {
    ...page,
    items: page.items.map((item) => requireSubmission(item, "资源广场返回了无效作者版本分页")),
  };
}

export async function listFeedback(options: FeedbackListOptions = {}): Promise<FeedbackPage> {
  const params = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.page_size ?? 20),
  });
  if (options.unread_only === true) params.set("unread_only", "true");
  if (options.unread_only === false) params.set("unread_only", "false");
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/feedback?${params.toString()}`,
  );
  const page = requirePageEnvelope(body, "资源广场返回了无效反馈分页");
  if (!boundedInt(body.unread_total, 0, Number.MAX_SAFE_INTEGER)) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效反馈分页");
  }
  return {
    ...page,
    unread_total: body.unread_total,
    items: page.items.map(normalizeFeedbackItem),
  };
}

export async function markFeedbackRead(
  payload: FeedbackReadPayload,
): Promise<{ id: string; updated_at: string; unread: false }> {
  const body = await requestJson<Record<string, unknown>>(
    "/api/resource-marketplace/feedback/read",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (
    typeof body.id !== "string"
    || typeof body.updated_at !== "string"
    || body.unread !== false
  ) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效已读结果");
  }
  return { id: body.id, updated_at: body.updated_at, unread: false };
}

export async function getPublishDraft(skillId: string): Promise<{
  draft: PublishDraft | null;
  last_source_skill_id?: string | null;
}> {
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/publish-drafts/${encodeURIComponent(skillId)}`,
  );
  if (!("draft" in body)) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效草稿");
  }
  return {
    draft: body.draft == null ? null : normalizePublishDraft(body.draft),
    ...("last_source_skill_id" in body
      ? { last_source_skill_id: typeof body.last_source_skill_id === "string" ? body.last_source_skill_id : null }
      : {}),
  };
}

export async function savePublishDraft(
  payload: SavePublishDraftPayload,
): Promise<{ draft: PublishDraft }> {
  const { skill_id, ...body } = payload;
  const result = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/publish-drafts/${encodeURIComponent(skill_id)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return { draft: normalizePublishDraft(result.draft) };
}

export async function deletePublishDraft(
  payload: DeletePublishDraftPayload,
): Promise<{ deleted: true }> {
  const { skill_id, expected_revision } = payload;
  const result = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/publish-drafts/${encodeURIComponent(skill_id)}`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision }),
    },
  );
  if (result.deleted !== true) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效草稿删除结果");
  }
  return { deleted: true };
}

export async function previewLocalSkill(
  skillId: string,
  options: LocalSkillPreviewRequest = {},
): Promise<LocalSkillPreview> {
  const params = new URLSearchParams();
  if (options.target_slug) params.set("target_slug", options.target_slug);
  if (options.publication_version) params.set("publication_version", options.publication_version);
  const query = params.toString();
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/local-skills/${encodeURIComponent(skillId)}/preview${query ? `?${query}` : ""}`,
  );
  if (
    typeof body.content !== "string"
    || typeof body.sha256 !== "string"
    || typeof body.version !== "string"
    || typeof body.skill_id !== "string"
  ) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效本地预览");
  }
  return {
    content: body.content,
    sha256: body.sha256,
    version: body.version,
    skill_id: body.skill_id,
    ...(typeof body.source_sha256 === "string" ? { source_sha256: body.source_sha256 } : {}),
    ...(typeof body.name === "string" ? { name: body.name } : {}),
  };
}
