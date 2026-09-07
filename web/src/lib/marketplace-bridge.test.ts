import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  buildBridgeErrorResponse,
  buildHostInitMessage,
  createMarketplaceBridgeInvoker,
  inspectMarketplaceBridgeMessage,
  isAllowedMarketplaceEmbedUrl,
  isTrustedMarketplaceEvent,
  MARKETPLACE_BRIDGE_CANCELLED,
  MARKETPLACE_BRIDGE_CHANNEL,
  MARKETPLACE_BRIDGE_CONFIRM_METHODS,
  MARKETPLACE_BRIDGE_MAX_BYTES,
  MARKETPLACE_BRIDGE_METHODS,
  MARKETPLACE_BRIDGE_VERSION,
  MARKETPLACE_IFRAME_SANDBOX,
  marketplaceBridgeMessageBytes,
  marketplaceBridgeTimeoutMs,
  marketplaceConfirmPrompt,
  marketplaceEmbedOrigin,
  MarketplaceBridgeHost,
  MarketplaceBridgeRateLimiter,
  methodRequiresConfirmation,
  withTimeout,
  type MarketplaceBridgeApi,
} from "./marketplace-bridge";
import type { MarketplaceSkill } from "./skill-marketplace";
import { envelope, trustedSkill, fakeApi } from "./marketplace-bridge-fixtures";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..");

test("bridge v1 constants stay fixed", () => {
  assert.equal(MARKETPLACE_BRIDGE_CHANNEL, "determinflow.marketplace.bridge");
  assert.equal(MARKETPLACE_BRIDGE_VERSION, 1);
  assert.equal(MARKETPLACE_BRIDGE_MAX_BYTES, 64 * 1024);
  assert.deepEqual([...MARKETPLACE_BRIDGE_METHODS], [
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
  ]);
  assert.deepEqual([...MARKETPLACE_BRIDGE_CONFIRM_METHODS], [
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
  ]);
  assert.equal(MARKETPLACE_IFRAME_SANDBOX, "allow-scripts allow-forms allow-same-origin allow-popups");
  assert.equal(MARKETPLACE_IFRAME_SANDBOX.includes("allow-top-navigation"), false);
  assert.equal(marketplaceBridgeTimeoutMs("auth.login") > marketplaceBridgeTimeoutMs("status"), true);
});

test("embed URLs allow https and loopback http and reject credentials or fragments", () => {
  assert.equal(isAllowedMarketplaceEmbedUrl("https://determinflow.com/embed/marketplace"), true);
  assert.equal(marketplaceEmbedOrigin("https://determinflow.com/embed/marketplace"), "https://determinflow.com");
  assert.equal(isAllowedMarketplaceEmbedUrl("http://127.0.0.1:8787/embed/marketplace"), true);
  assert.equal(isAllowedMarketplaceEmbedUrl("http://localhost:8787/embed/marketplace"), true);
  assert.equal(isAllowedMarketplaceEmbedUrl("http://example.com/embed/marketplace"), false);
  assert.equal(isAllowedMarketplaceEmbedUrl("https://user:pass@determinflow.com/embed/marketplace"), false);
  assert.equal(isAllowedMarketplaceEmbedUrl("https://determinflow.com/embed/marketplace#token"), false);
  assert.equal(isAllowedMarketplaceEmbedUrl("https://determinflow.com/embed/marketplace?next=/admin"), false);
  assert.equal(marketplaceEmbedOrigin("https://user:pass@determinflow.com/embed/marketplace"), null);
});

test("incoming messages require the fixed channel, version, requestId and payload shape", () => {
  assert.equal(inspectMarketplaceBridgeMessage({ type: "ready" }).action, "drop");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ type: "ready", method: undefined, requestId: undefined, payload: undefined })).action, "ready");
  assert.equal(inspectMarketplaceBridgeMessage(envelope()).action, "request");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ version: 2 })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ requestId: "" })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ method: "/api/resource-marketplace/skills" })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ method: "https://evil.example/steal" })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ token: "abc" })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ payload: { url: "/api/admin" } })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ payload: { path: "/secret" } })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "skills.get",
    payload: { slug: "writing-helper", extra: true },
  })).action, "reject");
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({
    method: "skills.get",
    payload: { slug: "writing-helper" },
  })), {
    action: "request",
    requestId: "req-1",
    method: "skills.get",
    payload: { slug: "writing-helper" },
  });
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({
    method: "skill.installPinned",
    payload: {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    },
  })), {
    action: "request",
    requestId: "req-1",
    method: "skill.installPinned",
    payload: {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    },
  });
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "skill.installPinned",
    payload: {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "zz".repeat(32),
    },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "notification.show",
    payload: { title: "已收藏", variant: "success" },
  })).action, "request");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "notification.show",
    payload: { title: "失败", variant: "destructive" },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "notification.show",
    payload: { title: "", variant: "success" },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "resource.withdraw",
    payload: { version_id: "11111111-1111-4111-8111-111111111111" },
  })).action, "request");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "review.resume",
    payload: {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      reason: "",
    },
  })).action, "reject");
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({
    method: "skills.page",
    payload: { query: "writing", page: 2, page_size: 24, favorites: true },
  })), {
    action: "request",
    requestId: "req-1",
    method: "skills.page",
    payload: { query: "writing", page: 2, page_size: 24, favorites: true },
  });
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "skills.page",
    payload: { page: 0 },
  })).action, "reject");
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({
    method: "skills.preview",
    payload: {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    },
  })), {
    action: "request",
    requestId: "req-1",
    method: "skills.preview",
    payload: {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    },
  });
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "skill.openInstalled",
    payload: { slug: "writing-helper" },
  })).action, "request");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "skill.openInstalled",
    payload: { slug: "writing-helper", skill_id: "local-id" },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "skill.openInstalled",
    payload: { slug: "writing-helper", path: "/skills/writing-helper" },
  })).action, "reject");
});

test("oversized messages are rejected without accepting arbitrary bodies", () => {
  const payload = { slug: "x".repeat(MARKETPLACE_BRIDGE_MAX_BYTES) };
  assert.equal(marketplaceBridgeMessageBytes(envelope({ method: "skills.get", payload })) > MARKETPLACE_BRIDGE_MAX_BYTES, true);
  const result = inspectMarketplaceBridgeMessage(envelope({ method: "skills.get", payload }));
  assert.equal(result.action, "reject");
  if (result.action === "reject") assert.equal(result.code, "too_large");
});

test("trusted events require matching contentWindow and origin", () => {
  const contentWindow = { id: "iframe" };
  assert.equal(isTrustedMarketplaceEvent(
    { source: contentWindow, origin: "https://determinflow.com", data: {} },
    { contentWindow, expectedOrigin: "https://determinflow.com" },
  ), true);
  assert.equal(isTrustedMarketplaceEvent(
    { source: { id: "other" }, origin: "https://determinflow.com", data: {} },
    { contentWindow, expectedOrigin: "https://determinflow.com" },
  ), false);
  assert.equal(isTrustedMarketplaceEvent(
    { source: contentWindow, origin: "https://evil.example", data: {} },
    { contentWindow, expectedOrigin: "https://determinflow.com" },
  ), false);
});

test("bridge methods call fixed local functions and never arbitrary URLs", async () => {
  const calls: string[] = [];
  let publishedPayload: Parameters<MarketplaceBridgeApi["publishMarketplaceSkill"]>[0] | null = null;
  const invoke = createMarketplaceBridgeInvoker(fakeApi({
    fetchMarketplaceSkills: async (query, category, sort) => {
      calls.push(`skills.list:${query}:${category}:${sort}`);
      return [];
    },
    fetchMarketplaceSkillPage: async (options = {}) => {
      calls.push(`skills.page:${options.query}:${options.page}:${options.favorites}`);
      return { items: [], total: 0, page: options.page ?? 1, page_size: options.page_size ?? 24 };
    },
    previewMarketplaceSkill: async (slug, pin) => {
      calls.push(`skills.preview:${slug}:${pin.expected_version_id}`);
      return { content: "# Skill", version_id: pin.expected_version_id, sha256: pin.expected_sha256 };
    },
    openInstalledMarketplaceSkill: async (slug) => {
      calls.push(`skill.openInstalled:${slug}`);
      return { opened: true, skill_id: slug };
    },
    installMarketplaceSkill: async (slug, pin) => {
      calls.push(`skill.install:${slug}:${pin.expected_version_id}`);
      return { installed: true, skill_id: slug, enabled: true };
    },
    publishMarketplaceSkill: async (payload) => {
      publishedPayload = payload;
      calls.push(`skill.publish:${payload.skill_id}`);
      return { status: "pending_review" };
    },
    withdrawMarketplaceSubmission: async (versionId) => {
      calls.push(`resource.withdraw:${versionId}`);
      return { id: versionId, status: "withdrawn" };
    },
    resumeMarketplaceSkill: async (payload) => {
      calls.push(`review.resume:${payload.slug}:${payload.expected_version_id}:${payload.reason}`);
      return { slug: payload.slug, status: "published" };
    },
  }));
  await invoke("skills.list", { query: "writing", category: "coding", sort: "popular" });
  await invoke("skills.page", { query: "writing", page: 2, favorites: true });
  await invoke("skills.preview", {
    slug: "writing-helper",
    expected_version_id: "11111111-1111-4111-8111-111111111111",
    expected_sha256: "a".repeat(64),
  });
  await invoke("skill.openInstalled", { slug: "writing-helper" });
  await invoke("skill.installPinned", {
    slug: "writing-helper",
    expected_version_id: "11111111-1111-4111-8111-111111111111",
    expected_sha256: "a".repeat(64),
  });
  await invoke("skill.publish", { skill_id: "writing-helper", license: "MIT", rights_confirmed: true });
  await invoke("resource.publish", {
    skill_id: "writing-helper",
    resource_type: "skill",
    license: "MIT",
    rights_confirmed: true,
    terms_confirmed: true,
    terms_version: "2026-09-03",
    author_name: "北辰",
    display_name: "写作助手",
    summary: "公开简介",
    usage_guide: "使用说明",
    functional_category: "novel",
    primary_locale: "zh-CN",
    tags_csv: "writing",
    release_notes: "首版",
  });
  await invoke("resource.withdraw", { version_id: "11111111-1111-4111-8111-111111111111" });
  await invoke("review.resume", {
    slug: "writing-helper",
    expected_version_id: "11111111-1111-4111-8111-111111111111",
    reason: "复核后恢复",
  });
  assert.deepEqual(calls, [
    "skills.list:writing:coding:popular",
    "skills.page:writing:2:true",
    "skills.preview:writing-helper:11111111-1111-4111-8111-111111111111",
    "skill.openInstalled:writing-helper",
    "skill.install:writing-helper:11111111-1111-4111-8111-111111111111",
    "skill.publish:writing-helper",
    "skill.publish:writing-helper",
    "resource.withdraw:11111111-1111-4111-8111-111111111111",
    "review.resume:writing-helper:11111111-1111-4111-8111-111111111111:复核后恢复",
  ]);
  assert.deepEqual(publishedPayload, {
    skill_id: "writing-helper",
    resource_type: "skill",
    license: "MIT",
    rights_confirmed: true,
    terms_confirmed: true,
    terms_version: "2026-09-03",
    author_name: "北辰",
    display_name: "写作助手",
    summary: "公开简介",
    usage_guide: "使用说明",
    functional_category: "novel",
    primary_locale: "zh-CN",
    tags_csv: "writing",
    release_notes: "首版",
  });
});

test("bridge list methods return stable items envelopes", async () => {
  const invoke = createMarketplaceBridgeInvoker(fakeApi({
    fetchMarketplaceSkills: async () => [],
    fetchCommunityReviews: async () => [],
    fetchEligibleLocalSkills: async () => [],
    fetchMySubmissions: async () => [],
  }));

  assert.deepEqual(await invoke("skills.list", {}), { items: [] });
  assert.deepEqual(await invoke("reviews.list", { slug: "writing-helper" }), { items: [] });
  assert.deepEqual(await invoke("localSkills.list", {}), { items: [] });
  assert.deepEqual(await invoke("submissions.list", {}), { items: [] });
});

test("install publish and lifecycle require confirmation and cancelled is stable", async () => {
  assert.equal(methodRequiresConfirmation("skill.install"), true);
  assert.equal(methodRequiresConfirmation("skill.installPinned"), true);
  assert.equal(methodRequiresConfirmation("skill.publish"), true);
  assert.equal(methodRequiresConfirmation("resource.publish"), true);
  assert.equal(methodRequiresConfirmation("resource.publishPinned"), true);
  assert.equal(methodRequiresConfirmation("resource.publishPrepared"), true);
  assert.equal(methodRequiresConfirmation("localSkills.previewPrepared"), false);
  assert.equal(methodRequiresConfirmation("resource.withdraw"), true);
  assert.equal(methodRequiresConfirmation("review.delete"), true);
  assert.equal(methodRequiresConfirmation("review.report"), false);
  assert.equal(methodRequiresConfirmation("reviews.page"), false);
  assert.equal(methodRequiresConfirmation("localSkills.preview"), false);
  assert.equal(methodRequiresConfirmation("publishDraft.save"), false);
  assert.equal(methodRequiresConfirmation("feedback.page"), false);
  assert.equal(methodRequiresConfirmation("review.resume"), true);
  assert.equal(methodRequiresConfirmation("skill.lifecycle"), true);
  assert.equal(methodRequiresConfirmation("status"), false);
  assert.equal(methodRequiresConfirmation("skills.page"), false);
  assert.equal(methodRequiresConfirmation("skills.preview"), false);
  assert.equal(methodRequiresConfirmation("skill.openInstalled"), false);
  assert.equal(MARKETPLACE_BRIDGE_CANCELLED.code, "cancelled");
  assert.equal(marketplaceConfirmPrompt("skill.installPinned", {
    slug: "writing-helper",
    display_name: "Writing Helper",
    version: "1.2.3",
  }).message.includes("1.2.3"), true);
  assert.equal(marketplaceConfirmPrompt("skill.install", {
    slug: "writing-helper",
    display_name: "Writing Helper",
    version: "1.2.3",
  }).confirmLabel, "安装");
  assert.equal(marketplaceConfirmPrompt("skill.lifecycle", { slug: "writing-helper", deprecated: true }).destructive, true);
  assert.equal(marketplaceConfirmPrompt("resource.withdraw", { version_id: "version" }).destructive, true);
  assert.equal(marketplaceConfirmPrompt("review.delete", {
    slug: "writing-helper",
    review_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    expected_updated_at: "2026-08-31T01:00:00Z",
  }).destructive, true);
  assert.equal(marketplaceConfirmPrompt("review.delete", {
    slug: "writing-helper",
  }).message.includes("评分和评价正文"), true);
  assert.equal(marketplaceConfirmPrompt("review.resume", { slug: "writing-helper" }).confirmLabel, "恢复上架");
});

test("host drops untrusted events and returns cancelled when confirmation is denied", async () => {
  const posted: unknown[] = [];
  const requested: string[] = [];
  const contentWindow = { id: "iframe" };
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async (method) => {
      if (method === "skills.get") return trustedSkill();
      return { installed: true };
    },
    confirm: async () => false,
    notify: () => undefined,
    onRequest: (method) => requested.push(method),
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://evil.example",
    data: envelope({ type: "ready", method: undefined, requestId: undefined }),
  });
  assert.equal(host.isReady, false);
  assert.equal(posted.length, 0);

  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ method: "status", payload: {} }),
  });
  await Promise.resolve();
  assert.equal((posted[posted.length - 1] as { error?: { code: string } } | undefined)?.error?.code, "not_ready");
  assert.deepEqual(requested, []);

  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ type: "ready", method: undefined, requestId: undefined }),
  });
  assert.equal(host.isReady, true);
  host.sendHostInit({ locale: "zh-CN", theme: "dark", capabilities: [...MARKETPLACE_BRIDGE_METHODS] });
  const init = posted[posted.length - 1] as Record<string, unknown>;
  assert.equal(init.type, "host:init");
  assert.deepEqual((init.payload as { capabilities: string[] }).capabilities, [...MARKETPLACE_BRIDGE_METHODS]);

  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ method: "skill.install", payload: { slug: "writing-helper" } }),
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(requested, ["skill.install"]);
  const response = posted[posted.length - 1] as Record<string, unknown>;
  assert.equal(response.type, "response");
  assert.equal(response.ok, false);
  assert.deepEqual(response.error, MARKETPLACE_BRIDGE_CANCELLED);
});

test("host routes marketplace notifications through its notification sink", async () => {
  const posted: unknown[] = [];
  const notifications: unknown[] = [];
  const contentWindow = { id: "iframe" };
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async () => {
      throw new Error("notification should not invoke a marketplace API");
    },
    confirm: async () => true,
    notify: (notification) => notifications.push(notification),
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ type: "ready", method: undefined, requestId: undefined, payload: undefined }),
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({
      method: "notification.show",
      payload: { title: "已收藏", detail: "稍后可在收藏中查看", variant: "success" },
    }),
  });
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.deepEqual(notifications, [{
    title: "已收藏",
    detail: "稍后可在收藏中查看",
    variant: "success",
  }]);
  assert.equal((posted[posted.length - 1] as { ok?: boolean }).ok, true);
});

for (const stage of ["prepare", "confirm", "invoke"] as const) {
  test(`reset invalidates an install waiting at ${stage}`, async () => {
    let resolve!: (value: unknown) => void;
    const pending = new Promise<unknown>((done) => { resolve = done; });
    const posted: unknown[] = [];
    const invoked: string[] = [];
    let confirmations = 0;
    const contentWindow = {};
    const host = new MarketplaceBridgeHost({
      expectedOrigin: "https://determinflow.com",
      getContentWindow: () => contentWindow,
      postMessage: (message) => { posted.push(message); },
      invoke: async (method) => {
        invoked.push(method);
        if (method === "skills.get") return stage === "prepare" ? pending : trustedSkill();
        return stage === "invoke" ? pending : { installed: true };
      },
      confirm: async () => {
        confirmations += 1;
        return stage === "confirm" ? pending as Promise<boolean> : true;
      },
      notify: () => {},
    });
    const send = (data: unknown) => host.handleMessage({ source: contentWindow, origin: "https://determinflow.com", data });
    send(envelope({ type: "ready", method: undefined, requestId: undefined }));
    send(envelope({ method: "skill.install", payload: { slug: "writing-helper" } }));
    await new Promise((done) => setTimeout(done, 0));
    host.reset();
    resolve(stage === "prepare" ? trustedSkill() : stage === "confirm" ? true : { installed: true });
    await new Promise((done) => setTimeout(done, 0));
    assert.deepEqual(posted, []);
    if (stage === "prepare") assert.equal(confirmations, 0);
    if (stage !== "invoke") assert.deepEqual(invoked, ["skills.get"]);
  });
}

test("rate limiter and timeout fail closed", async () => {
  const limiter = new MarketplaceBridgeRateLimiter(2, 10_000, 1);
  assert.equal(limiter.tryAcquire(0), "ok");
  assert.equal(limiter.tryAcquire(1), "busy");
  limiter.release();
  assert.equal(limiter.tryAcquire(2), "ok");
  limiter.release();
  assert.equal(limiter.tryAcquire(3), "rate_limited");

  await assert.rejects(
    withTimeout(new Promise(() => undefined), 1),
    (error: unknown) => error instanceof Error && error.message === "请求超时",
  );
  const init = buildHostInitMessage({ locale: "zh-CN", theme: "light", capabilities: ["status", "skills.list"] });
  assert.equal(init.type, "host:init");
  assert.deepEqual((init.payload as { capabilities: string[] }).capabilities, ["status", "skills.list"]);
  const error = buildBridgeErrorResponse("req-1", "cancelled", "已取消");
  assert.equal(error.ok, false);
  const limited = buildBridgeErrorResponse("req-2", "rate_limited", "评价提交过于频繁，请稍后重试", {
    retry_after_seconds: 42,
  });
  assert.deepEqual(limited.error, {
    code: "rate_limited",
    message: "评价提交过于频繁，请稍后重试",
    retry_after_seconds: 42,
  });
});

test("host skill.install fetches trusted details before confirm and pins the install", async () => {
  const posted: unknown[] = [];
  const confirmed: Array<Record<string, unknown>> = [];
  const installed: Array<Record<string, unknown>> = [];
  const contentWindow = { id: "iframe" };
  let resolveSkill!: (value: MarketplaceSkill) => void;
  const skillPromise = new Promise<MarketplaceSkill>((resolve) => {
    resolveSkill = resolve;
  });
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async (method, payload) => {
      if (method === "skills.get") return skillPromise;
      if (method === "skill.install") {
        installed.push(payload);
        return {
          installed: true,
          skill_id: "writing-helper",
          enabled: true,
          installation: { status: "installed", version: "2.0.0", enabled: true },
        };
      }
      throw new Error(`unexpected ${method}`);
    },
    confirm: async (_method, payload) => {
      confirmed.push(payload);
      return true;
    },
    notify: () => undefined,
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ type: "ready", method: undefined, requestId: undefined, payload: undefined }),
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ method: "skill.install", payload: { slug: "writing-helper" } }),
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(confirmed.length, 0);
  assert.equal(installed.length, 0);
  resolveSkill(trustedSkill({ version: "2.0.0", name: "Fetched Helper" }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(confirmed[0], {
    slug: "writing-helper",
    display_name: "Fetched Helper",
    version: "2.0.0",
  });
  assert.deepEqual(installed[0], {
    slug: "writing-helper",
    expected_version_id: "11111111-1111-4111-8111-111111111111",
    expected_sha256: "a".repeat(64),
  });
  assert.equal((posted[posted.length - 1] as { ok?: boolean }).ok, true);
});

test("host install rejects a download receipt and a disabled result", async () => {
  for (const result of [
    { downloaded: true, skill_id: "writing-helper" },
    { installed: true, skill_id: "writing-helper", enabled: false },
  ]) {
    const posted: Array<{ ok?: boolean; error?: { code?: string } }> = [];
    const contentWindow = { id: "iframe" };
    const host = new MarketplaceBridgeHost({
      expectedOrigin: "https://determinflow.com",
      getContentWindow: () => contentWindow,
      postMessage: (message) => posted.push(message as { ok?: boolean; error?: { code?: string } }),
      invoke: async (method) => {
        if (method === "skills.get") return trustedSkill();
        return result;
      },
      confirm: async () => true,
      notify: () => undefined,
    });
    host.handleMessage({
      source: contentWindow,
      origin: "https://determinflow.com",
      data: envelope({ type: "ready", method: undefined, requestId: undefined, payload: undefined }),
    });
    host.handleMessage({
      source: contentWindow,
      origin: "https://determinflow.com",
      data: envelope({ method: "skill.install", payload: { slug: "writing-helper" } }),
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(posted[posted.length - 1]?.ok, false);
    assert.equal(posted[posted.length - 1]?.error?.code, "operation_unknown");
  }
});

test("host skill.installPinned returns version_changed without confirming or installing", async () => {
  const posted: unknown[] = [];
  let confirmed = 0;
  let installed = 0;
  const contentWindow = { id: "iframe" };
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async (method) => {
      if (method === "skills.get") {
        return trustedSkill({
          version: "2.0.0",
          version_id: "22222222-2222-4222-8222-222222222222",
          sha256: "b".repeat(64),
        });
      }
      installed += 1;
      throw new Error("install should not run");
    },
    confirm: async () => {
      confirmed += 1;
      return true;
    },
    notify: () => undefined,
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ type: "ready", method: undefined, requestId: undefined, payload: undefined }),
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({
      method: "skill.installPinned",
      payload: {
        slug: "writing-helper",
        expected_version_id: "11111111-1111-4111-8111-111111111111",
        expected_sha256: "a".repeat(64),
      },
    }),
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const response = posted[posted.length - 1] as { ok?: boolean; error?: { code: string } };
  assert.equal(response.ok, false);
  assert.equal(response.error?.code, "version_changed");
  assert.equal(confirmed, 0);
  assert.equal(installed, 0);
});

test("preview and openInstalled are optional capabilities that skip confirmation", async () => {
  const posted: unknown[] = [];
  let confirmed = 0;
  const opened: string[] = [];
  const contentWindow = { id: "iframe" };
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async (method, payload) => {
      if (method === "skills.preview") {
        return { content: "# Skill", version_id: payload.expected_version_id, sha256: payload.expected_sha256 };
      }
      if (method === "skill.openInstalled") {
        opened.push(String(payload.slug));
        return { opened: true, skill_id: payload.slug };
      }
      throw new Error(`unexpected ${method}`);
    },
    confirm: async () => {
      confirmed += 1;
      return true;
    },
    notify: () => undefined,
  });
  const send = (data: unknown) => host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data,
  });
  send(envelope({ type: "ready", method: undefined, requestId: undefined, payload: undefined }));
  send(envelope({
    method: "skills.preview",
    payload: {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    },
  }));
  send(envelope({
    requestId: "req-2",
    method: "skill.openInstalled",
    payload: { slug: "writing-helper" },
  }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(confirmed, 0);
  assert.deepEqual(opened, ["writing-helper"]);
  assert.equal((posted[posted.length - 1] as { ok?: boolean }).ok, true);
});

test("core marketplace tab no longer ships a copied catalog UI", () => {
  const page = readFileSync(join(srcRoot, "pages", "ResourceMarketplacePage.tsx"), "utf8");
  const host = readFileSync(join(srcRoot, "components", "marketplace", "MarketplaceEmbedHost.tsx"), "utf8");
  assert.match(page, /MarketplaceEmbedHost/);
  assert.equal(page.includes("SkillMarketplacePage"), false);
  assert.match(host, /MARKETPLACE_IFRAME_SANDBOX/);
  assert.match(host, /onError/);
  assert.match(host, /useDialog/);
  assert.match(host, /在浏览器打开/);
  assert.equal(host.includes("allow-top-navigation"), false);
  const removed = [
    "SkillMarketplacePage.tsx",
    "MarketplaceAuthorCenter.tsx",
    "MarketplacePublishWorkspace.tsx",
    "MarketplaceSkillCard.tsx",
    "MarketplaceSkillDetail.tsx",
    "MarketplaceSubmissions.tsx",
  ];
  for (const file of removed) {
    assert.equal(existsSync(join(srcRoot, "components", "skills", file)), false, file);
  }
  assert.equal(existsSync(join(srcRoot, "lib", "marketplace-author.ts")), false);
});

test("stage 3 author draft and preview methods are capability-gated payloads", () => {
  const sha = "a".repeat(64);
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({
    method: "localSkills.preview",
    payload: { skill_id: "writing-helper" },
  })), {
    action: "request",
    requestId: "req-1",
    method: "localSkills.preview",
    payload: { skill_id: "writing-helper" },
  });
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "publishDraft.save",
    payload: {
      skill_id: "writing-helper",
      expected_revision: null,
      base_version: "1.2.3",
      base_sha256: sha,
      fields: {
        license: "MIT",
        display_name: "写作助手",
        author_name: "北辰",
        summary: "",
        functional_category: "novel",
        primary_locale: "zh-CN",
        tags_csv: "writing",
        release_notes: "",
      },
    },
  })).action, "request");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "publishDraft.save",
    payload: {
      skill_id: "writing-helper",
      expected_revision: null,
      base_version: "1.2.3",
      base_sha256: sha,
      fields: { license: "MIT", token: "secret" },
    },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "resource.publishPinned",
    payload: {
      skill_id: "writing-helper",
      resource_type: "skill",
      license: "MIT",
      rights_confirmed: true,
      terms_confirmed: true,
      terms_version: "2026-09-03",
      display_name: "写作助手",
      author_name: "北辰",
      summary: "简介",
      functional_category: "novel",
      primary_locale: "zh-CN",
      tags_csv: "writing",
      release_notes: "首版",
    },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "feedback.read",
    payload: {
      id: "submission:11111111-1111-4111-8111-111111111111",
      expected_updated_at: "2026-08-31T01:00:00Z",
    },
  })).action, "request");
  assert.equal(marketplaceConfirmPrompt("resource.publishPinned", {
    skill_id: "writing-helper",
  }).confirmLabel, "提交");
});

test("stage 3 invoker maps author feedback drafts and pinned publish", async () => {
  const calls: string[] = [];
  const invoke = createMarketplaceBridgeInvoker(fakeApi({
    listAuthorResources: async (options = {}) => {
      calls.push(`author:${options.query}:${options.status}`);
      return { items: [], total: 0, page: 1, page_size: 20 };
    },
    listFeedback: async (options = {}) => {
      calls.push(`feedback:${options.unread_only}`);
      return { items: [], total: 0, page: 1, page_size: 20, unread_total: 0 };
    },
    previewLocalSkill: async (skillId) => {
      calls.push(`preview:${skillId}`);
      return { content: "# Skill", sha256: "a".repeat(64), version: "1.2.3", skill_id: skillId };
    },
    getPublishDraft: async (skillId) => {
      calls.push(`draft.get:${skillId}`);
      return { draft: null };
    },
    publishMarketplaceSkill: async (payload) => {
      calls.push(`publish:${"expected_sha256" in payload ? payload.expected_sha256 : "unpinned"}`);
      return { status: "pending_review" };
    },
  }));
  await invoke("author.resources.page", { query: "writing", status: "pending" });
  await invoke("feedback.page", { unread_only: true });
  await invoke("localSkills.preview", { skill_id: "writing-helper" });
  await invoke("publishDraft.get", { skill_id: "writing-helper" });
  await invoke("resource.publishPinned", {
    skill_id: "writing-helper",
    resource_type: "skill",
    license: "MIT",
    rights_confirmed: true,
    terms_confirmed: true,
    terms_version: "2026-09-03",
    display_name: "写作助手",
    author_name: "北辰",
    summary: "简介",
    functional_category: "novel",
    primary_locale: "zh-CN",
    tags_csv: "writing",
    release_notes: "首版",
    expected_sha256: "a".repeat(64),
  });
  assert.deepEqual(calls, [
    "author:writing:pending",
    "feedback:true",
    "preview:writing-helper",
    "draft.get:writing-helper",
    `publish:${"a".repeat(64)}`,
  ]);
});
