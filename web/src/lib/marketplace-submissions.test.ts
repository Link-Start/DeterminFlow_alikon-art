import assert from "node:assert/strict";
import test from "node:test";

import {
  createGenerationGate,
  normalizeSubmission,
  shouldApplyPrivateFetch,
  submissionTone,
  visibleReviewReason,
} from "./marketplace-submissions";

const BASE = {
  id: "11111111-1111-4111-8111-111111111111",
  slug: "shared-skill",
  name: "shared-skill",
  summary: "Helpful",
  version: "1.2.3",
  sha256: "a".repeat(64),
  size_bytes: 12,
  license: "MIT",
  status: "pending_review",
  resource_status: "pending_review",
  is_current: false,
  review_reason: "缺少来源说明",
  submitted_at: "2026-08-31T00:00:00Z",
  reviewed_at: null,
};

test("normalizeSubmission keeps contract fields and drops invalid identities", () => {
  const normalized = normalizeSubmission(BASE);
  assert.equal(normalized?.id, BASE.id);
  assert.equal(normalized?.status, "pending_review");
  assert.equal(normalizeSubmission({ ...BASE, id: "not-a-uuid" }), null);
  assert.equal(normalizeSubmission({ ...BASE, status: "draft" }), null);
});

test("review reason is only visible for rejected or suspended versions", () => {
  const rejected = normalizeSubmission({ ...BASE, status: "rejected", resource_status: "rejected" });
  const pending = normalizeSubmission(BASE);
  const suspended = normalizeSubmission({
    ...BASE,
    status: "published",
    resource_status: "suspended",
  });
  assert.ok(rejected);
  assert.ok(pending);
  assert.ok(suspended);
  assert.equal(visibleReviewReason(rejected), "缺少来源说明");
  assert.equal(visibleReviewReason(pending), null);
  assert.equal(visibleReviewReason(suspended), null);
  assert.equal(submissionTone(rejected.status, rejected.resource_status), "rejected");
  assert.equal(submissionTone(pending.status, pending.resource_status), "pending");
  assert.equal(submissionTone(suspended.status, suspended.resource_status), "suspended");
  assert.equal(submissionTone("rejected", "suspended", false), "rejected");
  assert.equal(submissionTone("pending_review", "suspended", false), "pending");
  assert.equal(submissionTone("published", "suspended", false), "approved");
});

test("logout generation and signed-out state discard in-flight private payloads", () => {
  const gate = createGenerationGate();
  const requestId = gate.bump();
  const staleItems = [normalizeSubmission({ ...BASE, status: "rejected", resource_status: "rejected" })];
  gate.bump();
  assert.equal(
    shouldApplyPrivateFetch({
      requestId,
      currentId: gate.current(),
      signedIn: true,
    }),
    false,
  );
  const liveId = gate.bump();
  assert.equal(
    shouldApplyPrivateFetch({
      requestId: liveId,
      currentId: gate.current(),
      signedIn: false,
    }),
    false,
  );
  assert.equal(
    shouldApplyPrivateFetch({
      requestId: liveId,
      currentId: gate.current(),
      signedIn: true,
    }),
    true,
  );
  assert.equal(staleItems[0]?.status, "rejected");
});

test("submission metadata keeps tags for subsequent publication through the bridge", () => {
  assert.deepEqual(normalizeSubmission({ ...BASE, tags: ["writing"] })?.tags, ["writing"]);
  assert.deepEqual(normalizeSubmission({ ...BASE, resource: { tags: ["legacy"] } })?.tags, ["legacy"]);
});
