import assert from "node:assert/strict";
import test from "node:test";
import { createMarketplaceBridgeInvoker, inspectMarketplaceBridgeMessage, MARKETPLACE_BRIDGE_CANCELLED, MarketplaceBridgeHost } from "./marketplace-bridge";
import { MarketplaceApiError } from "./skill-marketplace";
import { envelope, fakeApi } from "./marketplace-bridge-fixtures";

const REVIEW_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const REVIEW_UPDATED_AT = "2026-08-31T01:00:00Z";

test("host report dialogs only accept bounded resource targets and paired review identity", () => {
  const inspect = (payload: Record<string, unknown>) => inspectMarketplaceBridgeMessage(envelope({ method: "report.open", payload })).action;
  assert.equal(inspect({ slug: "writing-helper", display_name: "写作助手" }), "request");
  assert.equal(inspect({ slug: "writing-helper", review_id: REVIEW_ID, expected_updated_at: REVIEW_UPDATED_AT }), "request");
  assert.equal(inspect({ slug: "../settings" }), "reject");
  assert.equal(inspect({ slug: "writing-helper", review_id: REVIEW_ID }), "reject");
  assert.equal(inspect({ slug: "writing-helper", expected_updated_at: REVIEW_UPDATED_AT }), "reject");
  assert.equal(inspect({ slug: "writing-helper", display_name: "x".repeat(81) }), "reject");
  assert.equal(inspect({ slug: "writing-helper", url: "https://invalid.example" }), "reject");
});

test("report.open delegates to the host dialog and never calls a write API before user submission", async () => {
  const posted: unknown[] = [];
  const contentWindow = {};
  let opened = 0;
  let resolve!: (value: { reported: boolean }) => void;
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    confirm: async () => { throw new Error("not a second confirmation"); },
    notify: () => undefined,
    invoke: async () => { throw new Error("report API must be owned by the form"); },
    openReport: async (payload) => {
      opened += 1;
      assert.equal(payload.slug, "writing-helper");
      return new Promise((done) => { resolve = done; });
    },
  });
  const event = (data: unknown) => ({ source: contentWindow, origin: "https://determinflow.com", data });
  host.handleMessage(event(envelope({ type: "ready", requestId: undefined, method: undefined, payload: undefined })));
  const request = envelope({ method: "report.open", payload: { slug: "writing-helper" } });
  host.handleMessage({ ...event(request), source: {} });
  assert.equal(opened, 0);
  host.handleMessage(event(request));
  assert.equal(opened, 1);
  assert.deepEqual(posted, []);
  resolve({ reported: false });
  await new Promise((done) => setTimeout(done, 0));
  assert.deepEqual((posted[0] as { payload: unknown }).payload, { reported: false });
});

test("stage 4 review methods validate uuid payloads and skip extra fields", () => {
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({
    method: "reviews.page",
    payload: { slug: "writing-helper", page: 2, page_size: 20 },
  })), {
    action: "request",
    requestId: "req-1",
    method: "reviews.page",
    payload: { slug: "writing-helper", page: 2, page_size: 20 },
  });
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "reviews.page",
    payload: { slug: "writing-helper", path: "/api/admin" },
  })).action, "reject");
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({
    method: "review.delete",
    payload: {
      slug: "writing-helper",
      review_id: REVIEW_ID,
      expected_updated_at: REVIEW_UPDATED_AT,
    },
  })), {
    action: "request",
    requestId: "req-1",
    method: "review.delete",
    payload: {
      slug: "writing-helper",
      review_id: REVIEW_ID,
      expected_updated_at: REVIEW_UPDATED_AT,
    },
  });
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "review.delete",
    payload: {
      slug: "writing-helper",
      review_id: "not-a-uuid",
      expected_updated_at: REVIEW_UPDATED_AT,
    },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "review.report",
    payload: {
      slug: "writing-helper",
      review_id: REVIEW_ID,
      expected_updated_at: REVIEW_UPDATED_AT,
      reason: "spam",
      url: "https://evil.example",
    },
  })).action, "reject");
  assert.equal(inspectMarketplaceBridgeMessage(envelope({
    method: "review.report",
    payload: {
      slug: "writing-helper",
      review_id: REVIEW_ID,
      expected_updated_at: REVIEW_UPDATED_AT,
      reason: "spam",
      details: "重复广告",
    },
  })).action, "request");
});

test("stage 4 invoker maps review page delete and report", async () => {
  const calls: string[] = [];
  const invoke = createMarketplaceBridgeInvoker(fakeApi({
    fetchCommunityReviewPage: async (slug, options = {}) => {
      calls.push(`page:${slug}:${options.page}:${options.page_size}`);
      return { items: [], total: 0, page: options.page ?? 1, page_size: options.page_size ?? 20 };
    },
    deleteMarketplaceReview: async (slug, reviewId, expectedUpdatedAt) => {
      calls.push(`delete:${slug}:${reviewId}:${expectedUpdatedAt}`);
      return { deleted: true };
    },
    reportMarketplaceReview: async (slug, reviewId, expectedUpdatedAt, reason, details) => {
      calls.push(`report:${slug}:${reviewId}:${expectedUpdatedAt}:${reason}:${details}`);
      return { reported: true };
    },
  }));
  await invoke("reviews.page", { slug: "writing-helper", page: 2, page_size: 10 });
  await invoke("review.delete", {
    slug: "writing-helper",
    review_id: REVIEW_ID,
    expected_updated_at: REVIEW_UPDATED_AT,
  });
  await invoke("review.report", {
    slug: "writing-helper",
    review_id: REVIEW_ID,
    expected_updated_at: REVIEW_UPDATED_AT,
    reason: "spam",
    details: "重复广告",
  });
  assert.deepEqual(calls, [
    "page:writing-helper:2:10",
    `delete:writing-helper:${REVIEW_ID}:${REVIEW_UPDATED_AT}`,
    `report:writing-helper:${REVIEW_ID}:${REVIEW_UPDATED_AT}:spam:重复广告`,
  ]);
});

test("review.delete cancel does not call backend and retry_after stays on the error envelope", async () => {
  const posted: unknown[] = [];
  const deleted: string[] = [];
  const contentWindow = { id: "iframe" };
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async (method, payload) => {
      if (method === "review.delete") {
        deleted.push(String(payload.review_id));
        return { deleted: true };
      }
      throw new MarketplaceApiError("rate_limited", "评价提交过于频繁，请稍后重试", 42);
    },
    confirm: async () => false,
    notify: () => undefined,
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ type: "ready", method: undefined, requestId: undefined }),
  });
  host.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({
      method: "review.delete",
      payload: {
        slug: "writing-helper",
        review_id: REVIEW_ID,
        expected_updated_at: REVIEW_UPDATED_AT,
      },
    }),
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(deleted, []);
  assert.deepEqual((posted[posted.length - 1] as { error?: unknown }).error, MARKETPLACE_BRIDGE_CANCELLED);

  const retryHost = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com",
    getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async () => {
      throw new MarketplaceApiError("rate_limited", "评价提交过于频繁，请稍后重试", 42);
    },
    confirm: async () => true,
    notify: () => undefined,
  });
  retryHost.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({ type: "ready", method: undefined, requestId: undefined }),
  });
  retryHost.handleMessage({
    source: contentWindow,
    origin: "https://determinflow.com",
    data: envelope({
      method: "review.report",
      payload: {
        slug: "writing-helper",
        review_id: REVIEW_ID,
        expected_updated_at: REVIEW_UPDATED_AT,
        reason: "spam",
      },
    }),
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual((posted[posted.length - 1] as { error?: unknown }).error, {
    code: "rate_limited",
    message: "评价提交过于频繁，请稍后重试",
    retry_after_seconds: 42,
  });
});
