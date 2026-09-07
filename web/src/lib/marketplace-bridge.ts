import { prepareMarketplaceInstall, readCompletedInstall, readCompletedUpdate } from "./marketplace-install";
import { isMarketplaceWrite, waitForConfirmation, type MarketplaceConfirmationContext } from "./marketplace-request-lifecycle";
import {
  deleteMarketplaceReview,
  deletePublishDraft,
  fetchCommunityReviewPage,
  fetchCommunityReviews,
  fetchEligibleLocalSkills,
  fetchMarketplaceSkill,
  fetchMarketplaceSkillPage,
  fetchMarketplaceSkills,
  fetchMarketplaceStatus,
  fetchMySubmissions,
  getPublishDraft,
  installMarketplaceSkill,
  updateMarketplaceSkill,
  listAuthorResources,
  listAuthorVersions,
  listFeedback,
  loginMarketplace,
  logoutMarketplace,
  markFeedbackRead,
  MarketplaceApiError,
  openInstalledMarketplaceSkill,
  previewLocalSkill,
  previewMarketplaceSkill,
  publishMarketplaceSkill,
  reportMarketplaceReview,
  reportMarketplaceSkill,
  saveMarketplaceReview,
  savePublishDraft,
  setMarketplaceFavorite,
  resumeMarketplaceSkill,
  type MarketplacePublishPayload,
  type MarketplaceSkill,
  updateMarketplaceSkillLifecycle,
  withdrawMarketplaceSubmission,
} from "./skill-marketplace";
import {
  buildBridgeErrorResponse,
  buildBridgeResponse,
  buildHostInitMessage,
  buildBridgeProgress,
  inspectMarketplaceBridgeMessage,
  isTrustedMarketplaceEvent,
  MARKETPLACE_BRIDGE_CANCELLED,
  marketplaceBridgeTimeoutMs,
  methodRequiresConfirmation,
  type MarketplaceBridgeApiMethod,
  type MarketplaceBridgeConfirmMethod,
  type MarketplaceBridgeMethod,
  type MarketplaceHostInit,
  type MarketplaceMessageEventLike,
} from "./marketplace-bridge-protocol";

export {
  buildBridgeErrorResponse,
  buildBridgeResponse,
  buildHostInitMessage,
  inspectMarketplaceBridgeMessage,
  isAllowedMarketplaceEmbedUrl,
  isTrustedMarketplaceEvent,
  MARKETPLACE_BRIDGE_CANCELLED,
  MARKETPLACE_BRIDGE_CHANNEL,
  MARKETPLACE_BRIDGE_CONFIRM_METHODS,
  MARKETPLACE_BRIDGE_MAX_BYTES,
  MARKETPLACE_BRIDGE_METHODS,
  MARKETPLACE_BRIDGE_READY_TIMEOUT_MS,
  MARKETPLACE_BRIDGE_VERSION,
  MARKETPLACE_IFRAME_SANDBOX,
  marketplaceBridgeMessageBytes,
  marketplaceBridgeTimeoutMs,
  marketplaceConfirmPrompt,
  marketplaceEmbedOrigin,
  methodRequiresConfirmation,
} from "./marketplace-bridge-protocol";
export type {
  MarketplaceBridgeApiMethod,
  MarketplaceBridgeConfirmMethod,
  MarketplaceBridgeInspectResult,
  MarketplaceBridgeMethod,
  MarketplaceConfirmPrompt,
  MarketplaceHostInit,
  MarketplaceMessageEventLike,
} from "./marketplace-bridge-protocol";

export class MarketplaceBridgeError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
    this.name = "MarketplaceBridgeError";
  }
}

export interface MarketplaceBridgeNotification {
  title: string;
  detail?: string;
  variant: "default" | "success" | "error" | "warning";
}

export interface MarketplaceBridgeApi {
  fetchMarketplaceStatus: typeof fetchMarketplaceStatus;
  fetchMarketplaceSkills: typeof fetchMarketplaceSkills;
  fetchMarketplaceSkillPage: typeof fetchMarketplaceSkillPage;
  fetchMarketplaceSkill: typeof fetchMarketplaceSkill;
  previewMarketplaceSkill: typeof previewMarketplaceSkill;
  openInstalledMarketplaceSkill: typeof openInstalledMarketplaceSkill;
  fetchCommunityReviews: typeof fetchCommunityReviews;
  fetchCommunityReviewPage: typeof fetchCommunityReviewPage;
  setMarketplaceFavorite: typeof setMarketplaceFavorite;
  saveMarketplaceReview: typeof saveMarketplaceReview;
  deleteMarketplaceReview: typeof deleteMarketplaceReview;
  reportMarketplaceSkill: typeof reportMarketplaceSkill;
  reportMarketplaceReview: typeof reportMarketplaceReview;
  loginMarketplace: typeof loginMarketplace;
  logoutMarketplace: typeof logoutMarketplace;
  fetchEligibleLocalSkills: typeof fetchEligibleLocalSkills;
  previewLocalSkill: typeof previewLocalSkill;
  installMarketplaceSkill: typeof installMarketplaceSkill;
  updateMarketplaceSkill: typeof updateMarketplaceSkill;
  fetchMySubmissions: typeof fetchMySubmissions;
  publishMarketplaceSkill: typeof publishMarketplaceSkill;
  withdrawMarketplaceSubmission: typeof withdrawMarketplaceSubmission;
  resumeMarketplaceSkill: typeof resumeMarketplaceSkill;
  updateMarketplaceSkillLifecycle: typeof updateMarketplaceSkillLifecycle;
  listAuthorResources: typeof listAuthorResources;
  listAuthorVersions: typeof listAuthorVersions;
  listFeedback: typeof listFeedback;
  markFeedbackRead: typeof markFeedbackRead;
  getPublishDraft: typeof getPublishDraft;
  savePublishDraft: typeof savePublishDraft;
  deletePublishDraft: typeof deletePublishDraft;
}

function publishPayload(payload: Record<string, unknown>): MarketplacePublishPayload {
  const body: MarketplacePublishPayload = {
    skill_id: String(payload.skill_id),
    resource_type: "skill",
    license: String(payload.license),
    rights_confirmed: payload.rights_confirmed === true,
    terms_confirmed: payload.terms_confirmed === true,
    terms_version: String(payload.terms_version),
    display_name: String(payload.display_name),
    author_name: String(payload.author_name),
    summary: String(payload.summary),
    usage_guide: optionalString(payload.usage_guide),
    functional_category: String(payload.functional_category),
    primary_locale: String(payload.primary_locale),
    tags_csv: String(payload.tags_csv),
    release_notes: String(payload.release_notes),
  };
  if (typeof payload.expected_sha256 === "string") {
    body.expected_sha256 = payload.expected_sha256;
  }
  if (typeof payload.target_slug === "string") {
    body.target_slug = payload.target_slug;
  }
  if (typeof payload.publication_version === "string") {
    body.publication_version = payload.publication_version;
  }
  return body;
}

export function createMarketplaceBridgeInvoker(
  api: MarketplaceBridgeApi = defaultMarketplaceBridgeApi(),
) {
  return async function invoke(
    method: MarketplaceBridgeApiMethod,
    payload: Record<string, unknown>,
  ): Promise<unknown> {
    switch (method) {
      case "status":
        return api.fetchMarketplaceStatus();
      case "skills.list":
        return {
          items: await api.fetchMarketplaceSkills(
            optionalString(payload.query),
            optionalString(payload.category) || "all",
            optionalString(payload.sort) || "updated",
          ),
        };
      case "skills.page":
        return api.fetchMarketplaceSkillPage({
          query: optionalString(payload.query) || undefined,
          category: optionalString(payload.category) || undefined,
          sort: optionalString(payload.sort) || undefined,
          page: typeof payload.page === "number" ? payload.page : undefined,
          page_size: typeof payload.page_size === "number" ? payload.page_size : undefined,
          favorites: typeof payload.favorites === "boolean" ? payload.favorites : undefined,
        });
      case "skills.get":
        return api.fetchMarketplaceSkill(String(payload.slug));
      case "skills.preview":
        return api.previewMarketplaceSkill(String(payload.slug), {
          expected_version_id: String(payload.expected_version_id),
          expected_sha256: String(payload.expected_sha256),
        });
      case "skill.openInstalled":
        return api.openInstalledMarketplaceSkill(String(payload.slug));
      case "reviews.list":
        return { items: await api.fetchCommunityReviews(String(payload.slug)) };
      case "reviews.page":
        return api.fetchCommunityReviewPage(String(payload.slug), {
          page: typeof payload.page === "number" ? payload.page : undefined,
          page_size: typeof payload.page_size === "number" ? payload.page_size : undefined,
        });
      case "favorite.set":
        return api.setMarketplaceFavorite(String(payload.slug), payload.favorited === true);
      case "review.save":
        return api.saveMarketplaceReview(
          String(payload.slug),
          Number(payload.rating),
          optionalString(payload.body),
        );
      case "review.delete":
        return api.deleteMarketplaceReview(
          String(payload.slug),
          String(payload.review_id),
          String(payload.expected_updated_at),
        );
      case "review.report":
        return api.reportMarketplaceReview(
          String(payload.slug),
          String(payload.review_id),
          String(payload.expected_updated_at),
          String(payload.reason),
          optionalString(payload.details),
        );
      case "report.create":
        return api.reportMarketplaceSkill(
          String(payload.slug),
          String(payload.reason),
          optionalString(payload.details),
        );
      case "auth.login":
        return api.loginMarketplace();
      case "auth.logout":
        return api.logoutMarketplace();
      case "localSkills.list":
        return { items: await api.fetchEligibleLocalSkills() };
      case "localSkills.preview":
        return api.previewLocalSkill(String(payload.skill_id));
      case "localSkills.previewPrepared":
        return api.previewLocalSkill(String(payload.skill_id), {
          ...(typeof payload.target_slug === "string" ? { target_slug: payload.target_slug } : {}),
          publication_version: String(payload.publication_version),
        });
      case "skill.install":
      case "skill.installPinned":
        return api.installMarketplaceSkill(String(payload.slug), {
          expected_version_id: String(payload.expected_version_id),
          expected_sha256: String(payload.expected_sha256),
        });
      case "skill.updatePinned":
        return api.updateMarketplaceSkill(String(payload.slug), { expected_version_id: String(payload.expected_version_id), expected_sha256: String(payload.expected_sha256) });
      case "submissions.list":
        return { items: await api.fetchMySubmissions() };
      case "skill.publish":
        return api.publishMarketplaceSkill({
          skill_id: String(payload.skill_id),
          license: String(payload.license),
          rights_confirmed: payload.rights_confirmed === true,
        });
      case "resource.publish":
      case "resource.publishPinned":
      case "resource.publishPrepared":
        return api.publishMarketplaceSkill(publishPayload(payload));
      case "resource.withdraw":
        return api.withdrawMarketplaceSubmission(String(payload.version_id));
      case "review.resume":
        return api.resumeMarketplaceSkill({
          slug: String(payload.slug),
          expected_version_id: String(payload.expected_version_id),
          reason: String(payload.reason),
        });
      case "skill.lifecycle":
        return api.updateMarketplaceSkillLifecycle({
          slug: String(payload.slug),
          deprecated: payload.deprecated === true,
          replacement_slug: optionalString(payload.replacement_slug) || undefined,
          message: optionalString(payload.message) || undefined,
        });
      case "author.resources.page":
        return api.listAuthorResources({
          query: optionalString(payload.query) || undefined,
          status: optionalString(payload.status) || undefined,
          page: typeof payload.page === "number" ? payload.page : undefined,
          page_size: typeof payload.page_size === "number" ? payload.page_size : undefined,
        });
      case "author.versions.page":
        return api.listAuthorVersions(String(payload.slug), {
          page: typeof payload.page === "number" ? payload.page : undefined,
          page_size: typeof payload.page_size === "number" ? payload.page_size : undefined,
        });
      case "feedback.page":
        return api.listFeedback({
          page: typeof payload.page === "number" ? payload.page : undefined,
          page_size: typeof payload.page_size === "number" ? payload.page_size : undefined,
          unread_only: typeof payload.unread_only === "boolean" ? payload.unread_only : undefined,
        });
      case "feedback.read":
        return api.markFeedbackRead({
          id: String(payload.id),
          expected_updated_at: String(payload.expected_updated_at),
        });
      case "publishDraft.get":
        return api.getPublishDraft(String(payload.skill_id));
      case "publishDraft.save":
        return api.savePublishDraft({
          skill_id: String(payload.skill_id),
          expected_revision: payload.expected_revision === null ? null : Number(payload.expected_revision),
          base_version: String(payload.base_version),
          base_sha256: String(payload.base_sha256),
          fields: payload.fields as SavePublishDraftFields,
          ...(typeof payload.source_skill_id === "string" ? { source_skill_id: payload.source_skill_id } : {}),
          ...(typeof payload.publication_version === "string" ? { publication_version: payload.publication_version } : {}),
        });
      case "publishDraft.delete":
        return api.deletePublishDraft({
          skill_id: String(payload.skill_id),
          expected_revision: Number(payload.expected_revision),
        });
    }
  };
}

type SavePublishDraftFields = Parameters<typeof savePublishDraft>[0]["fields"];

export function defaultMarketplaceBridgeApi(): MarketplaceBridgeApi {
  return {
    fetchMarketplaceStatus,
    fetchMarketplaceSkills,
    fetchMarketplaceSkillPage,
    fetchMarketplaceSkill,
    previewMarketplaceSkill,
    openInstalledMarketplaceSkill,
    fetchCommunityReviews,
    fetchCommunityReviewPage,
    setMarketplaceFavorite,
    saveMarketplaceReview,
    deleteMarketplaceReview,
    reportMarketplaceSkill,
    reportMarketplaceReview,
    loginMarketplace,
    logoutMarketplace,
    fetchEligibleLocalSkills,
    previewLocalSkill,
    installMarketplaceSkill,
    updateMarketplaceSkill,
    fetchMySubmissions,
    publishMarketplaceSkill,
    withdrawMarketplaceSubmission,
    resumeMarketplaceSkill,
    updateMarketplaceSkillLifecycle,
    listAuthorResources,
    listAuthorVersions,
    listFeedback,
    markFeedbackRead,
    getPublishDraft,
    savePublishDraft,
    deletePublishDraft,
  };
}

export function bridgeErrorFromUnknown(error: unknown): {
  code: string;
  message: string;
  retry_after_seconds?: number;
} {
  if (error instanceof MarketplaceBridgeError) {
    return { code: error.code, message: error.message };
  }
  if (error instanceof MarketplaceApiError) {
    return {
      code: error.code,
      message: error.message,
      ...(error.retry_after_seconds != null
        ? { retry_after_seconds: error.retry_after_seconds }
        : {}),
    };
  }
  return { code: "request_failed", message: "请求失败" };
}

export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new MarketplaceBridgeError("timeout", "请求超时"));
    }, ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

export class MarketplaceBridgeRateLimiter {
  private timestamps: number[] = [];
  private inFlight = 0;

  constructor(
    private readonly maxPerWindow = 40,
    private readonly windowMs = 10_000,
    private readonly maxInFlight = 8,
  ) {}

  tryAcquire(now: number): "ok" | "rate_limited" | "busy" {
    this.timestamps = this.timestamps.filter((stamp) => now - stamp < this.windowMs);
    if (this.inFlight >= this.maxInFlight) return "busy";
    if (this.timestamps.length >= this.maxPerWindow) return "rate_limited";
    this.timestamps.push(now);
    this.inFlight += 1;
    return "ok";
  }

  release(): void {
    if (this.inFlight > 0) this.inFlight -= 1;
  }
}

export class MarketplaceBridgeHost {
  private ready = false;
  private generation = 0;
  private readonly inFlight = new Set<string>();
  private readonly pending = new Map<string, { controller: AbortController; phase: "preparing" | "confirming" | "executing"; pulse: ReturnType<typeof setInterval> }>();
  private limiter = new MarketplaceBridgeRateLimiter();

  constructor(private readonly config: {
    expectedOrigin: string;
    getContentWindow: () => unknown;
    postMessage: (message: unknown, targetOrigin: string) => void;
    invoke: (method: MarketplaceBridgeApiMethod, payload: Record<string, unknown>) => Promise<unknown>;
    confirm: (
      method: MarketplaceBridgeConfirmMethod,
      payload: Record<string, unknown>,
      context: MarketplaceConfirmationContext,
    ) => Promise<boolean>;
    notify: (notification: MarketplaceBridgeNotification) => void;
    openInstalledSkill?: (skillId: string) => void;
    openReport?: (payload: Record<string, unknown>) => Promise<{ reported: boolean }>;
    now?: () => number;
    onReady?: () => void;
    onRequest?: (method: MarketplaceBridgeMethod) => void;
  }) {}

  get isReady(): boolean {
    return this.ready;
  }

  reset(): void {
    this.generation += 1;
    this.ready = false;
    for (const request of this.pending.values()) {
      clearInterval(request.pulse);
      request.controller.abort();
    }
    this.pending.clear();
    this.inFlight.clear();
    this.limiter = new MarketplaceBridgeRateLimiter();
  }

  sendHostInit(init: MarketplaceHostInit): void {
    this.post(buildHostInitMessage(init));
  }

  handleMessage(event: MarketplaceMessageEventLike): void {
    if (!isTrustedMarketplaceEvent(event, {
      contentWindow: this.config.getContentWindow(),
      expectedOrigin: this.config.expectedOrigin,
    })) {
      return;
    }
    const inspected = inspectMarketplaceBridgeMessage(event.data);
    if (inspected.action === "drop") return;
    if (inspected.action === "ready") {
      this.ready = true;
      this.config.onReady?.();
      return;
    }
    if (inspected.action === "cancel") {
      const request = this.pending.get(inspected.requestId);
      // Once invoked, cancellation cannot promise to undo a write. Keep its result.
      if (request && request.phase !== "executing") request.controller.abort();
      return;
    }
    if (inspected.action === "reject") {
      if (inspected.requestId) {
        this.post(buildBridgeErrorResponse(inspected.requestId, inspected.code, inspected.message));
      }
      return;
    }
    void this.fulfill(inspected.requestId, inspected.method, inspected.payload);
  }

  private async fulfill(
    requestId: string,
    method: MarketplaceBridgeMethod,
    payload: Record<string, unknown>,
  ): Promise<void> {
    if (!this.ready) {
      this.post(buildBridgeErrorResponse(requestId, "not_ready", "宿主尚未就绪"));
      return;
    }
    this.config.onRequest?.(method);
    if (this.inFlight.has(requestId)) {
      this.post(buildBridgeErrorResponse(requestId, "duplicate_request", "重复的请求"));
      return;
    }
    const admission = this.limiter.tryAcquire(this.config.now?.() ?? Date.now());
    if (admission !== "ok") {
      const code = admission === "busy" ? "busy" : "rate_limited";
      this.post(buildBridgeErrorResponse(
        requestId,
        code,
        admission === "busy" ? "进行中的请求过多" : "请求过于频繁，请稍后重试",
      ));
      return;
    }
    this.inFlight.add(requestId);
    const generation = this.generation;
    const limiter = this.limiter;
    const current = () => generation === this.generation;
    const request = {
      controller: new AbortController(),
      phase: "preparing" as "preparing" | "confirming" | "executing",
      pulse: setInterval(() => {
        if (current()) this.post(buildBridgeProgress(requestId, request.phase));
      }, 5_000),
    };
    this.pending.set(requestId, request);
    try {
      let confirmPayload = payload;
      let invokePayload = payload;
      if (method === "skill.install" || method === "skill.installPinned" || method === "skill.updatePinned") {
        const prepared = await withTimeout(
          prepareMarketplaceInstall(
            async (slug) => this.config.invoke("skills.get", { slug }) as Promise<MarketplaceSkill>,
            method,
            payload,
          ),
          marketplaceBridgeTimeoutMs(method),
        );
        if (!current()) return;
        confirmPayload = prepared.confirmPayload;
        invokePayload = prepared.invokePayload;
      }
      if (request.controller.signal.aborted) throw new MarketplaceBridgeError("cancelled", "已取消操作");
      if (methodRequiresConfirmation(method)) {
        request.phase = "confirming";
        const accepted = await waitForConfirmation(this.config.confirm(method, confirmPayload, {
          requestId, signal: request.controller.signal,
        }), request.controller.signal);
        if (!current()) return;
        if (!accepted || request.controller.signal.aborted) {
          this.post(buildBridgeErrorResponse(
            requestId,
            MARKETPLACE_BRIDGE_CANCELLED.code,
            MARKETPLACE_BRIDGE_CANCELLED.message,
          ));
          return;
        }
      }
      if (request.controller.signal.aborted) throw new MarketplaceBridgeError("cancelled", "已取消操作");
      request.phase = "executing";
      if (method === "notification.show") {
        this.config.notify({
          title: String(payload.title),
          ...(payload.detail ? { detail: String(payload.detail) } : {}),
          variant: String(payload.variant) as MarketplaceBridgeNotification["variant"],
        });
        this.post(buildBridgeResponse(requestId, {}));
        return;
      }
      if (method === "report.open") {
        if (!this.config.openReport) throw new MarketplaceBridgeError("unsupported_method", "请更新客户端后举报");
        const result = await this.config.openReport(payload);
        if (current()) this.post(buildBridgeResponse(requestId, result));
        return;
      }
      const operation = this.config.invoke(method, invokePayload);
      const result = await (isMarketplaceWrite(method)
        ? operation
        : withTimeout(operation, marketplaceBridgeTimeoutMs(method)));
      if (!current()) return;
      if (method === "skill.openInstalled") {
        const opened = result as { opened?: unknown; skill_id?: unknown } | null;
        if (opened?.opened !== true || typeof opened.skill_id !== "string"
          || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(opened.skill_id)) {
          throw new MarketplaceBridgeError("invalid_response", "无法打开已安装 Skill");
        }
        this.config.openInstalledSkill?.(opened.skill_id);
      }
      if (method === "skill.install" || method === "skill.installPinned") {
        readCompletedInstall(result, String(invokePayload.slug));
      }
      if (method === "skill.updatePinned") readCompletedUpdate(result, String(invokePayload.slug));
      this.post(buildBridgeResponse(requestId, result));
    } catch (error) {
      if (!current()) return;
      const mapped = bridgeErrorFromUnknown(error);
      if (request.phase === "executing" && isMarketplaceWrite(method)
        && (error instanceof TypeError || ["timeout", "network_unavailable", "invalid_response", "service_unavailable"].includes(mapped.code))) {
        mapped.code = "operation_unknown";
        mapped.message = "暂未确认操作结果，请刷新查看实际状态后再重试。";
      }
      this.post(buildBridgeErrorResponse(
        requestId,
        mapped.code,
        mapped.message,
        mapped.retry_after_seconds != null
          ? { retry_after_seconds: mapped.retry_after_seconds }
          : undefined,
      ));
    } finally {
      clearInterval(request.pulse);
      if (this.pending.get(requestId) === request) this.pending.delete(requestId);
      if (current()) this.inFlight.delete(requestId);
      limiter.release();
    }
  }

  private post(message: unknown): void {
    this.config.postMessage(message, this.config.expectedOrigin);
  }
}

function defaultMarketplaceLocale(): string {
  if (typeof navigator === "undefined") return "zh-CN";
  return navigator.language || "zh-CN";
}

export function marketplaceHostLocale(
  language: string | undefined = typeof navigator === "undefined" ? undefined : navigator.language,
): string {
  const value = (language || "").trim();
  return value || defaultMarketplaceLocale();
}

function optionalString(value: unknown): string {
  return typeof value === "string" ? value : "";
}
