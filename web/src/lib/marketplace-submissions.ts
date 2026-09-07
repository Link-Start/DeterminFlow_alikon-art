export type SubmissionStatus = "pending_review" | "published" | "rejected" | "withdrawn";
export type ResourceStatus = SubmissionStatus | "suspended";
export type SubmissionTone = "pending" | "published" | "approved" | "rejected" | "suspended" | "withdrawn";

export interface MarketplaceSubmission {
  id: string;
  resource_type: string;
  slug: string;
  name: string;
  summary: string;
  usage_guide?: string;
  tags?: string[];
  version: string;
  sha256: string;
  size_bytes: number;
  license: string;
  status: SubmissionStatus;
  resource_status: ResourceStatus;
  is_current: boolean;
  review_reason: string | null;
  suspension_reason: string | null;
  submitted_at: string;
  reviewed_at: string | null;
  display_name: string;
  category: string;
  functional_category: string;
  primary_locale: string;
  publisher_name: string;
  author_name: string;
  author_description: string;
  repository_url: string | null;
  homepage_url: string | null;
  support_url: string | null;
  skill_format_version: number;
  determinflow_requires: string;
  required_tools: string[];
  required_plugins: string[];
  required_apps: string[];
  release_notes: string;
  published_at: string | null;
  terms_version: string;
  terms_accepted_at: string | null;
  download_count: number;
  favorite_count: number;
  rating_average: number | null;
  rating_count: number;
  review_count: number;
  deprecated_at: string | null;
  replacement_slug: string | null;
  deprecation_message: string | null;
}

const VERSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATUSES = new Set<SubmissionStatus>(["pending_review", "published", "rejected", "withdrawn"]);
const RESOURCE_STATUSES = new Set<ResourceStatus>([
  "pending_review",
  "published",
  "rejected",
  "suspended",
  "withdrawn",
]);

export function createGenerationGate() {
  let current = 0;
  return {
    current() {
      return current;
    },
    bump() {
      current += 1;
      return current;
    },
    isCurrent(id: number) {
      return id === current;
    },
  };
}

export function shouldApplyPrivateFetch(input: {
  requestId: number;
  currentId: number;
  signedIn: boolean;
}): boolean {
  return input.signedIn && input.requestId === input.currentId;
}

export function submissionTone(
  status: SubmissionStatus,
  resourceStatus: ResourceStatus,
  isCurrent = true,
): SubmissionTone {
  if (status === "withdrawn") return "withdrawn";
  if (status === "rejected") return "rejected";
  if (status === "published") {
    if (!isCurrent) return "approved";
    return resourceStatus === "suspended" ? "suspended" : "published";
  }
  return "pending";
}

export function visibleReviewReason(submission: MarketplaceSubmission): string | null {
  const reason = submission.review_reason?.trim() || "";
  if (!reason) return null;
  if (submission.status === "rejected") {
    return reason;
  }
  return null;
}

export function normalizeSubmission(raw: Record<string, unknown>): MarketplaceSubmission | null {
  const id = typeof raw.id === "string" ? raw.id : "";
  const slug = typeof raw.slug === "string" ? raw.slug : "";
  const status = raw.status;
  const resourceStatus = raw.resource_status;
  if (!VERSION_ID.test(id) || !slug) return null;
  if (typeof status !== "string" || !STATUSES.has(status as SubmissionStatus)) return null;
  if (
    typeof resourceStatus !== "string"
    || !RESOURCE_STATUSES.has(resourceStatus as ResourceStatus)
  ) {
    return null;
  }
  const stringList = (value: unknown) => Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
  return {
    id,
    resource_type: typeof raw.resource_type === "string" ? raw.resource_type : "skill",
    slug,
    name: String(raw.name ?? slug),
    summary: typeof raw.summary === "string" ? raw.summary : "",
    usage_guide: typeof raw.usage_guide === "string" ? raw.usage_guide : "",
    tags: stringList(raw.tags ?? (raw.resource && typeof raw.resource === "object" ? (raw.resource as Record<string, unknown>).tags : [])),
    version: String(raw.version ?? ""),
    sha256: typeof raw.sha256 === "string" ? raw.sha256 : "",
    size_bytes: typeof raw.size_bytes === "number" ? raw.size_bytes : 0,
    license: typeof raw.license === "string" ? raw.license : "",
    status: status as SubmissionStatus,
    resource_status: resourceStatus as ResourceStatus,
    is_current: raw.is_current === true,
    review_reason: typeof raw.review_reason === "string" && raw.review_reason.trim()
      ? raw.review_reason
      : null,
    suspension_reason: typeof raw.suspension_reason === "string" ? raw.suspension_reason : null,
    submitted_at: typeof raw.submitted_at === "string" ? raw.submitted_at : "",
    reviewed_at: typeof raw.reviewed_at === "string" ? raw.reviewed_at : null,
    display_name: String(raw.display_name ?? raw.name ?? slug),
    category: typeof raw.category === "string" ? raw.category : "general",
    functional_category: typeof raw.functional_category === "string" ? raw.functional_category : "general",
    primary_locale: typeof raw.primary_locale === "string" ? raw.primary_locale : "und",
    publisher_name: typeof raw.publisher_name === "string" ? raw.publisher_name : "",
    author_name: typeof raw.author_name === "string" ? raw.author_name : "",
    author_description: typeof raw.author_description === "string" ? raw.author_description : "",
    repository_url: typeof raw.repository_url === "string" ? raw.repository_url : null,
    homepage_url: typeof raw.homepage_url === "string" ? raw.homepage_url : null,
    support_url: typeof raw.support_url === "string" ? raw.support_url : null,
    skill_format_version: typeof raw.skill_format_version === "number" ? raw.skill_format_version : 1,
    determinflow_requires: typeof raw.determinflow_requires === "string" ? raw.determinflow_requires : "*",
    required_tools: stringList(raw.required_tools),
    required_plugins: stringList(raw.required_plugins),
    required_apps: stringList(raw.required_apps),
    release_notes: typeof raw.release_notes === "string" ? raw.release_notes : "",
    published_at: typeof raw.published_at === "string" ? raw.published_at : null,
    terms_version: typeof raw.terms_version === "string" ? raw.terms_version : "",
    terms_accepted_at: typeof raw.terms_accepted_at === "string" ? raw.terms_accepted_at : null,
    download_count: typeof raw.download_count === "number" ? raw.download_count : 0,
    favorite_count: typeof raw.favorite_count === "number" ? raw.favorite_count : 0,
    rating_average: typeof raw.rating_average === "number" ? raw.rating_average : null,
    rating_count: typeof raw.rating_count === "number" ? raw.rating_count : 0,
    review_count: typeof raw.review_count === "number" ? raw.review_count : 0,
    deprecated_at: typeof raw.deprecated_at === "string" ? raw.deprecated_at : null,
    replacement_slug: typeof raw.replacement_slug === "string" ? raw.replacement_slug : null,
    deprecation_message: typeof raw.deprecation_message === "string" ? raw.deprecation_message : null,
  };
}
