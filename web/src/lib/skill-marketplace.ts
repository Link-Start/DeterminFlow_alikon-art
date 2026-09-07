import { patchSearchParams } from "../hooks/useUrlParam";
import { normalizeSubmission, type MarketplaceSubmission } from "./marketplace-submissions";
import { publishAccountStatus } from "./account";
import { readCompletedInstall, readCompletedUpdate } from "./marketplace-install";
import { MarketplaceApiError, requestJson } from "./skill-marketplace-http";

export { MarketplaceApiError } from "./skill-marketplace-http";
export {
  deletePublishDraft,
  getPublishDraft,
  listAuthorResources,
  listAuthorVersions,
  listFeedback,
  markFeedbackRead,
  previewLocalSkill,
  savePublishDraft,
} from "./skill-marketplace-authoring";
export type {
  AuthorListOptions,
  AuthorResource,
  AuthorResourcePage,
  AuthorVersionListOptions,
  DeletePublishDraftPayload,
  DraftFields,
  FeedbackItem,
  FeedbackKind,
  FeedbackListOptions,
  FeedbackPage,
  FeedbackReadPayload,
  FeedbackStatus,
  LocalSkillPreview,
  PublishDraft,
  SavePublishDraftPayload,
} from "./skill-marketplace-authoring";

export type {
  MarketplaceSubmission,
  ResourceStatus,
  SubmissionStatus,
} from "./marketplace-submissions";

export interface MarketplaceStatus {
  configured: boolean;
  signed_in: boolean;
  account_name: string | null;
  marketplace_url: string | null;
  embed_url: string | null;
  resource_types: string[];
  publishable_resource_types: string[];
  functional_categories: string[];
}

export interface MarketplaceResourceEnvelope {
  schema_version: 1;
  id: string | null;
  version_id: string | null;
  resource_type: string;
  slug: string;
  display_name: string;
  summary: string;
  usage_guide?: string;
  functional_category: string;
  primary_locale: string;
  tags: string[];
  author: { id: string | null; name: string };
  release: {
    version: string;
    license: string;
    release_notes: string;
    published_at: string | null;
    created_at: string | null;
    updated_at: string | null;
  };
  links: { repository_url: string | null; homepage_url: string | null; support_url: string | null };
  compatibility: {
    determinflow_requires: string;
    required_tools: string[];
    required_plugins: string[];
    required_apps: string[];
  };
  community: {
    download_count: number;
    downloads_30d: number;
    favorite_count: number;
    rating_average: number | null;
    rating_count: number;
    review_count: number;
  };
  lifecycle: {
    deprecated_at: string | null;
    replacement_slug: string | null;
    deprecation_message: string | null;
  };
}

export interface MarketplaceSkillPayload {
  type: "skill";
  name: string;
  format_version: number;
  sha256: string | null;
  size_bytes: number | null;
}

export interface MarketplaceSkill {
  resource: MarketplaceResourceEnvelope;
  payload: MarketplaceSkillPayload;
  resource_id?: string;
  version_id?: string;
  publisher_id?: string;
  resource_type: string;
  slug: string;
  skill_name?: string;
  name: string;
  description: string;
  version: string;
  license: string;
  publisher_name: string;
  author_name: string;
  author_description: string;
  category: string;
  functional_category: string;
  primary_locale: string;
  tags: string[];
  determinflow_requires: string;
  required_tools: string[];
  required_plugins: string[];
  required_apps: string[];
  repository_url: string | null;
  homepage_url: string | null;
  support_url: string | null;
  release_notes: string;
  published_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  download_count: number;
  downloads_30d: number;
  favorite_count: number;
  rating_average: number | null;
  rating_count: number;
  review_count: number;
  deprecated_at: string | null;
  replacement_slug: string | null;
  deprecation_message: string | null;
  sha256?: string;
  viewer: MarketplaceViewer | null;
  installation?: MarketplaceInstallation;
}

export type CommunityReviewVisibility = "visible" | "hidden";

export interface OwnCommunityReview {
  rating: number;
  body: string;
  updated_at: string;
  id?: string;
  visibility?: CommunityReviewVisibility;
  moderation_reason?: string | null;
}

export interface MarketplaceViewer {
  favorited: boolean;
  review: OwnCommunityReview | null;
}

export type MarketplaceInstallationStatus = "available" | "installed" | "builtin" | "conflict";

export interface MarketplaceInstallation {
  status: MarketplaceInstallationStatus;
  update_available?: boolean;
  version: string | null;
  enabled: boolean | null;
}

export interface CommunityReview {
  id: string;
  author_label: string;
  rating: number;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface CommunityReviewPage {
  items: CommunityReview[];
  total: number;
  page: number;
  page_size: number;
}

export interface EligibleLocalSkill {
  resource_type: "skill";
  id: string;
  name: string;
  description: string;
  version: string;
  size_bytes: number;
  category: string;
  author: string;
  tags: string[];
  compatibility: string;
  declared_license: string;
  release_notes: string;
  primary_locale: string;
  required_tools: string[];
  required_plugins: string[];
  required_apps: string[];
  sha256: string;
  preflight: Array<{ id: string; label: string; passed: boolean }>;
}

export interface MarketplacePublishPayload {
  skill_id: string;
  resource_type: "skill";
  license: string;
  rights_confirmed: boolean;
  terms_confirmed: boolean;
  terms_version: string;
  display_name: string;
  author_name: string;
  summary: string;
  usage_guide?: string;
  functional_category: string;
  primary_locale: string;
  tags_csv: string;
  release_notes: string;
  expected_sha256?: string;
  target_slug?: string;
  publication_version?: string;
}

export interface InstallResult {
  installed: boolean;
  skill_id: string;
  version?: string;
  sha256?: string;
  enabled: boolean;
  provenance?: Record<string, unknown>;
  installation?: MarketplaceInstallation;
}

export interface MarketplaceCatalogQuery {
  query?: string;
  category?: string;
  sort?: string;
  page?: number;
  page_size?: number;
  favorites?: boolean;
}

export interface MarketplaceCatalogPage {
  items: MarketplaceSkill[];
  total: number;
  page: number;
  page_size: number;
}

export interface MarketplaceSkillPreview {
  content: string;
  version_id: string;
  sha256: string;
}

export interface InstallPin {
  expected_version_id: string;
  expected_sha256: string;
}

export interface OpenInstalledSkillResult {
  opened: true;
  skill_id: string;
}

const INSTALLATION_STATUSES = new Set<MarketplaceInstallationStatus>([
  "available",
  "installed",
  "builtin",
  "conflict",
]);

function normalizeOwnReview(raw: Record<string, unknown>): OwnCommunityReview | null {
  if (typeof raw.rating !== "number") return null;
  const review: OwnCommunityReview = {
    rating: raw.rating,
    body: typeof raw.body === "string" ? raw.body : "",
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : "",
  };
  if (typeof raw.id === "string" && raw.id) review.id = raw.id;
  if (raw.visibility === "visible" || raw.visibility === "hidden") review.visibility = raw.visibility;
  if (raw.moderation_reason === null || typeof raw.moderation_reason === "string") {
    review.moderation_reason = raw.moderation_reason;
  }
  return review;
}

function normalizePublicReview(raw: unknown): CommunityReview | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  if (typeof record.rating !== "number") return null;
  return {
    id: typeof record.id === "string" ? record.id : "",
    author_label: typeof record.author_label === "string" ? record.author_label : "",
    rating: record.rating,
    body: typeof record.body === "string" ? record.body : "",
    created_at: typeof record.created_at === "string" ? record.created_at : "",
    updated_at: typeof record.updated_at === "string" ? record.updated_at : "",
  };
}

function normalizePublicReviews(items: unknown): CommunityReview[] {
  if (!Array.isArray(items)) return [];
  return items.flatMap((item) => {
    const review = normalizePublicReview(item);
    return review ? [review] : [];
  });
}

function normalizeInstallation(raw: unknown): MarketplaceInstallation | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const record = raw as Record<string, unknown>;
  if (typeof record.status !== "string" || !INSTALLATION_STATUSES.has(record.status as MarketplaceInstallationStatus)) {
    return undefined;
  }
  return {
    status: record.status as MarketplaceInstallationStatus,
    ...(typeof record.update_available === "boolean" ? { update_available: record.update_available } : {}),
    version: typeof record.version === "string" ? record.version : null,
    enabled: typeof record.enabled === "boolean" ? record.enabled : null,
  };
}

function normalizeSkill(raw: Record<string, unknown>): MarketplaceSkill {
  const envelope = raw.resource && typeof raw.resource === "object" ? raw.resource as Record<string, unknown> : {};
  const usageGuide = raw.usage_guide ?? envelope.usage_guide;
  const slug = String(raw.slug ?? raw.skill_name ?? raw.name ?? "");
  const viewerRaw = raw.viewer && typeof raw.viewer === "object"
    ? raw.viewer as Record<string, unknown>
    : null;
  const reviewRaw = viewerRaw?.review && typeof viewerRaw.review === "object"
    ? viewerRaw.review as Record<string, unknown>
    : null;
  const stringList = (value: unknown) => Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
  const skill = {
    ...(typeof raw.resource_id === "string" ? { resource_id: raw.resource_id } : {}),
    ...(typeof raw.version_id === "string" ? { version_id: raw.version_id } : {}),
    ...(typeof raw.publisher_id === "string" ? { publisher_id: raw.publisher_id } : {}),
    resource_type: typeof raw.resource_type === "string" ? raw.resource_type : "skill",
    slug,
    skill_name: typeof raw.skill_name === "string" ? raw.skill_name : undefined,
    name: String(raw.display_name ?? raw.name ?? raw.skill_name ?? slug),
    description: String(raw.summary ?? raw.description ?? ""),
    version: String(raw.version ?? raw.declared_version ?? raw.version_number ?? ""),
    license: String(raw.license ?? ""),
    publisher_name: typeof raw.publisher_name === "string"
      ? raw.publisher_name
      : typeof raw.owner_display_name === "string" ? raw.owner_display_name : "社区贡献者",
    author_name: typeof raw.author_name === "string" ? raw.author_name : "",
    author_description: typeof raw.author_description === "string" ? raw.author_description : "",
    category: typeof raw.category === "string" ? raw.category : "general",
    functional_category: typeof raw.functional_category === "string" ? raw.functional_category : "general",
    primary_locale: typeof raw.primary_locale === "string" ? raw.primary_locale : "und",
    tags: stringList(raw.tags),
    determinflow_requires: typeof raw.determinflow_requires === "string" ? raw.determinflow_requires : "*",
    required_tools: stringList(raw.required_tools),
    required_plugins: stringList(raw.required_plugins),
    required_apps: stringList(raw.required_apps),
    repository_url: typeof raw.repository_url === "string" ? raw.repository_url : null,
    homepage_url: typeof raw.homepage_url === "string" ? raw.homepage_url : null,
    support_url: typeof raw.support_url === "string" ? raw.support_url : null,
    release_notes: typeof raw.release_notes === "string" ? raw.release_notes : "",
    published_at: typeof raw.published_at === "string" ? raw.published_at : null,
    created_at: typeof raw.created_at === "string" ? raw.created_at : null,
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : null,
    download_count: typeof raw.download_count === "number" ? raw.download_count : 0,
    downloads_30d: typeof raw.downloads_30d === "number" ? raw.downloads_30d : 0,
    favorite_count: typeof raw.favorite_count === "number" ? raw.favorite_count : 0,
    rating_average: typeof raw.rating_average === "number" ? raw.rating_average : null,
    rating_count: typeof raw.rating_count === "number" ? raw.rating_count : 0,
    review_count: typeof raw.review_count === "number" ? raw.review_count : 0,
    deprecated_at: typeof raw.deprecated_at === "string" ? raw.deprecated_at : null,
    replacement_slug: typeof raw.replacement_slug === "string" ? raw.replacement_slug : null,
    deprecation_message: typeof raw.deprecation_message === "string" ? raw.deprecation_message : null,
    sha256: typeof raw.sha256 === "string"
      ? raw.sha256
      : typeof raw.content_sha256 === "string" ? raw.content_sha256 : undefined,
    installation: normalizeInstallation(raw.installation),
    viewer: viewerRaw ? {
      favorited: viewerRaw.favorited === true,
      review: reviewRaw ? normalizeOwnReview(reviewRaw) : null,
    } : null,
  };
  return {
    ...skill,
    resource: {
      schema_version: 1,
      id: skill.resource_id ?? null,
      version_id: skill.version_id ?? null,
      resource_type: skill.resource_type,
      slug: skill.slug,
      display_name: skill.name,
      summary: skill.description,
      usage_guide: typeof usageGuide === "string" ? usageGuide : "",
      functional_category: skill.functional_category,
      primary_locale: skill.primary_locale,
      tags: skill.tags,
      author: {
        id: skill.publisher_id ?? null,
        name: skill.author_name,
      },
      release: {
        version: skill.version,
        license: skill.license,
        release_notes: skill.release_notes,
        published_at: skill.published_at,
        created_at: skill.created_at,
        updated_at: skill.updated_at,
      },
      links: {
        repository_url: skill.repository_url,
        homepage_url: skill.homepage_url,
        support_url: skill.support_url,
      },
      compatibility: {
        determinflow_requires: skill.determinflow_requires,
        required_tools: skill.required_tools,
        required_plugins: skill.required_plugins,
        required_apps: skill.required_apps,
      },
      community: {
        download_count: skill.download_count,
        downloads_30d: skill.downloads_30d,
        favorite_count: skill.favorite_count,
        rating_average: skill.rating_average,
        rating_count: skill.rating_count,
        review_count: skill.review_count,
      },
      lifecycle: {
        deprecated_at: skill.deprecated_at,
        replacement_slug: skill.replacement_slug,
        deprecation_message: skill.deprecation_message,
      },
    },
    payload: {
      type: "skill",
      name: skill.skill_name ?? skill.slug,
      format_version: typeof raw.skill_format_version === "number" ? raw.skill_format_version : 1,
      sha256: skill.sha256 ?? null,
      size_bytes: typeof raw.size_bytes === "number" ? raw.size_bytes : null,
    },
  };
}

export async function fetchMarketplaceStatus(): Promise<MarketplaceStatus> {
  return requestJson("/api/resource-marketplace/status");
}

export async function fetchMarketplaceSkills(
  query = "",
  category = "all",
  sort = "updated",
): Promise<MarketplaceSkill[]> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (category !== "all") params.set("category", category);
  if (sort !== "updated") params.set("sort", sort);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  const body = await requestJson<{ items: Record<string, unknown>[] }>(
    `/api/resource-marketplace/skills${suffix}`,
  );
  return body.items.map(normalizeSkill).filter((skill) => skill.slug);
}

export async function fetchMarketplaceSkillPage(
  options: MarketplaceCatalogQuery = {},
): Promise<MarketplaceCatalogPage> {
  const params = new URLSearchParams();
  const query = options.query?.trim() ?? "";
  if (query) params.set("q", query);
  if (options.category && options.category !== "all") params.set("category", options.category);
  if (options.sort && options.sort !== "updated") params.set("sort", options.sort);
  params.set("page", String(options.page ?? 1));
  params.set("page_size", String(options.page_size ?? 24));
  if (options.favorites === true) params.set("favorites", "true");
  if (options.favorites === false) params.set("favorites", "false");
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/catalog/skills?${params.toString()}`,
  );
  if (
    !Array.isArray(body.items)
    || typeof body.total !== "number"
    || typeof body.page !== "number"
    || typeof body.page_size !== "number"
  ) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效分页");
  }
  return {
    items: body.items
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
      .map(normalizeSkill)
      .filter((skill) => skill.slug),
    total: body.total,
    page: body.page,
    page_size: body.page_size,
  };
}

export async function previewMarketplaceSkill(
  slug: string,
  pin: InstallPin,
): Promise<MarketplaceSkillPreview> {
  const params = new URLSearchParams({
    expected_version_id: pin.expected_version_id,
    expected_sha256: pin.expected_sha256,
  });
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/preview?${params.toString()}`,
  );
  if (
    typeof body.content !== "string"
    || typeof body.version_id !== "string"
    || typeof body.sha256 !== "string"
  ) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效预览");
  }
  return {
    content: body.content,
    version_id: body.version_id,
    sha256: body.sha256,
  };
}

export interface CoreSkillNavigationRuntime {
  pathname: string;
  search: string;
  hash: string;
  historyState: unknown;
  pushState: (state: unknown, unused: string, url: string) => void;
  dispatchEvent: (event: Event) => boolean;
}

export function browserSkillNavigationRuntime(): CoreSkillNavigationRuntime {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
    historyState: window.history.state,
    pushState: window.history.pushState.bind(window.history),
    dispatchEvent: window.dispatchEvent.bind(window),
  };
}

export function navigateToCoreSkill(
  skillId: string,
  runtime: CoreSkillNavigationRuntime = browserSkillNavigationRuntime(),
): void {
  const nextSearch = patchSearchParams(runtime.search, {
    tab: "skills",
    skill: skillId,
  });
  runtime.pushState(runtime.historyState, "", `${runtime.pathname}${nextSearch}${runtime.hash}`);
  runtime.dispatchEvent(
    typeof PopStateEvent === "function" ? new PopStateEvent("popstate") : new Event("popstate"),
  );
}

export function navigateToMarketplaceSkill(
  skillId: string,
  runtime: CoreSkillNavigationRuntime = browserSkillNavigationRuntime(),
): void {
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(skillId)) return;
  const search = patchSearchParams(runtime.search, { tab: "marketplace", marketplace_skill: skillId });
  runtime.pushState(runtime.historyState, "", `${runtime.pathname}${search}${runtime.hash}`);
  runtime.dispatchEvent(typeof PopStateEvent === "function" ? new PopStateEvent("popstate") : new Event("popstate"));
}

export function marketplaceSkillEmbedUrl(embedUrl: string, skillId: string | null): string {
  if (!skillId || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(skillId)) return embedUrl;
  const url = new URL(embedUrl);
  url.searchParams.set("skill", skillId);
  return url.toString();
}

export async function openInstalledMarketplaceSkill(
  slug: string,
): Promise<OpenInstalledSkillResult> {
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/open-installed`,
    { method: "POST" },
  );
  const skillId = typeof body.skill_id === "string" ? body.skill_id : "";
  if (body.opened !== true || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(skillId)) {
    throw new MarketplaceApiError("request_failed", "无法打开已安装 Skill");
  }
  return { opened: true, skill_id: skillId };
}

export async function fetchCommunityReviews(slug: string): Promise<CommunityReview[]> {
  const body = await requestJson<{ items: unknown }>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/reviews`,
  );
  return normalizePublicReviews(body.items);
}

export async function fetchCommunityReviewPage(
  slug: string,
  options: { page?: number; page_size?: number } = {},
): Promise<CommunityReviewPage> {
  const params = new URLSearchParams({
    page: String(options.page ?? 1),
    page_size: String(options.page_size ?? 20),
  });
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/reviews/page?${params.toString()}`,
  );
  if (
    typeof body.total !== "number"
    || typeof body.page !== "number"
    || typeof body.page_size !== "number"
  ) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效评价分页");
  }
  return {
    items: normalizePublicReviews(body.items),
    total: body.total,
    page: body.page,
    page_size: body.page_size,
  };
}

export async function setMarketplaceFavorite(slug: string, favorited: boolean): Promise<{ favorited: boolean; favorite_count: number }> {
  return requestJson(`/api/resource-marketplace/skills/${encodeURIComponent(slug)}/favorite`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ favorited }),
  });
}

export async function saveMarketplaceReview(slug: string, rating: number, body: string): Promise<Record<string, unknown>> {
  const result = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/review`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rating, body }),
    },
  );
  const own = normalizeOwnReview(result);
  return own ? { ...own } : result;
}

export async function deleteMarketplaceReview(
  slug: string,
  reviewId: string,
  expectedUpdatedAt: string,
): Promise<{ deleted: true }> {
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/review`,
    {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review_id: reviewId,
        expected_updated_at: expectedUpdatedAt,
      }),
    },
  );
  if (body.deleted !== true) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效删除结果");
  }
  return { deleted: true };
}

export async function reportMarketplaceSkill(slug: string, reason: string, details: string): Promise<Record<string, unknown>> {
  return requestJson(`/api/resource-marketplace/skills/${encodeURIComponent(slug)}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, details }),
  });
}

export async function reportMarketplaceReview(
  slug: string,
  reviewId: string,
  expectedUpdatedAt: string,
  reason: string,
  details = "",
): Promise<{ reported: true }> {
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/reviews/${encodeURIComponent(reviewId)}/report`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_updated_at: expectedUpdatedAt,
        reason,
        details,
      }),
    },
  );
  if (body.reported !== true) {
    throw new MarketplaceApiError("invalid_response", "资源广场返回了无效举报结果");
  }
  return { reported: true };
}

export async function fetchMarketplaceSkill(slug: string): Promise<MarketplaceSkill> {
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}`,
  );
  return normalizeSkill(body);
}

export async function fetchEligibleLocalSkills(): Promise<EligibleLocalSkill[]> {
  const body = await requestJson<{ items: EligibleLocalSkill[] }>(
    "/api/resource-marketplace/eligible-skills",
  );
  return body.items;
}

export async function loginMarketplace(): Promise<MarketplaceStatus> {
  const status = await requestJson<MarketplaceStatus>(
    "/api/resource-marketplace/login",
    { method: "POST" },
  );
  publishAccountStatus({ configured: status.configured, signed_in: status.signed_in });
  return status;
}

export async function logoutMarketplace(): Promise<MarketplaceStatus> {
  const status = await requestJson<MarketplaceStatus>(
    "/api/resource-marketplace/logout",
    { method: "POST" },
  );
  publishAccountStatus({ configured: status.configured, signed_in: status.signed_in });
  return status;
}

export async function installMarketplaceSkill(
  slug: string,
  pin: { expected_version_id: string; expected_sha256: string },
): Promise<InstallResult> {
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/install`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_version_id: pin.expected_version_id,
        expected_sha256: pin.expected_sha256,
      }),
    },
  );
  const completed = readCompletedInstall(body, slug);
  return {
    installed: true,
    skill_id: completed.skill_id,
    version: typeof body.version === "string" ? body.version : undefined,
    sha256: typeof body.sha256 === "string" ? body.sha256 : undefined,
    enabled: true,
    provenance: body.provenance && typeof body.provenance === "object"
      ? body.provenance as Record<string, unknown>
      : undefined,
    installation: normalizeInstallation(body.installation),
  };
}

export async function updateMarketplaceSkill(
  slug: string,
  pin: { expected_version_id: string; expected_sha256: string },
): Promise<InstallResult & { updated: true }> {
  const body = await requestJson<Record<string, unknown>>(
    `/api/resource-marketplace/skills/${encodeURIComponent(slug)}/update`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expected_version_id: pin.expected_version_id,
        expected_sha256: pin.expected_sha256,
      }),
    },
  );
  const completed = readCompletedUpdate(body, slug);
  return {
    installed: true,
    skill_id: completed.skill_id,
    version: typeof body.version === "string" ? body.version : undefined,
    sha256: typeof body.sha256 === "string" ? body.sha256 : undefined,
    enabled: completed.enabled,
    updated: true,
    provenance: body.provenance && typeof body.provenance === "object"
      ? body.provenance as Record<string, unknown>
      : undefined,
    installation: normalizeInstallation(body.installation),
  };
}

export async function publishMarketplaceSkill(
  payload: MarketplacePublishPayload | Pick<MarketplacePublishPayload, "skill_id" | "license" | "rights_confirmed">,
): Promise<Record<string, unknown>> {
  const generic = "resource_type" in payload;
  const pinned = generic && "expected_sha256" in payload && typeof payload.expected_sha256 === "string"
    ? { expected_sha256: payload.expected_sha256 }
    : {};
  const prepared = generic && "publication_version" in payload && typeof payload.publication_version === "string"
    ? {
        publication_version: payload.publication_version,
        ...(typeof payload.target_slug === "string" ? { target_slug: payload.target_slug } : {}),
      }
    : {};
  return requestJson("/api/resource-marketplace/publish", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(generic ? {
      skill_id: payload.skill_id,
      resource_type: payload.resource_type,
      license: payload.license,
      rights_confirmed: payload.rights_confirmed,
      terms_confirmed: payload.terms_confirmed,
      terms_version: payload.terms_version,
      metadata: {
        display_name: payload.display_name,
        author_name: payload.author_name,
        summary: payload.summary,
        usage_guide: payload.usage_guide || "",
        functional_category: payload.functional_category,
        primary_locale: payload.primary_locale,
        tags: payload.tags_csv.split(",").map((tag) => tag.trim()).filter(Boolean),
        release_notes: payload.release_notes,
      },
      ...pinned,
      ...prepared,
    } : payload),
  });
}

export async function fetchMySubmissions(): Promise<MarketplaceSubmission[]> {
  const body = await requestJson<{ items: Record<string, unknown>[] }>(
    "/api/resource-marketplace/submissions",
  );
  return (body.items ?? []).flatMap((item) => {
    const normalized = normalizeSubmission(item);
    return normalized ? [normalized] : [];
  });
}

export async function withdrawMarketplaceSubmission(
  versionId: string,
): Promise<Record<string, unknown>> {
  return requestJson(
    `/api/resource-marketplace/submissions/${encodeURIComponent(versionId)}/withdraw`,
    { method: "POST" },
  );
}

export async function resumeMarketplaceSkill(payload: {
  slug: string;
  expected_version_id: string;
  reason: string;
}): Promise<Record<string, unknown>> {
  const { slug, ...body } = payload;
  return requestJson(`/api/resource-marketplace/skills/${encodeURIComponent(slug)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateMarketplaceSkillLifecycle(payload: {
  slug: string;
  deprecated: boolean;
  replacement_slug?: string;
  message?: string;
}): Promise<{ slug: string; deprecated_at: string | null; replacement_slug: string | null; deprecation_message: string | null }> {
  const { slug, ...body } = payload;
  return requestJson(`/api/resource-marketplace/skills/${encodeURIComponent(slug)}/lifecycle`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
