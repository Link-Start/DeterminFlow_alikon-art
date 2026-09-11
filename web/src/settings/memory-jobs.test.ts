import assert from "node:assert/strict";
import test from "node:test";
import React, { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { fetchMemoryJobs, isMemoryJobActive, readMemoryJobs, retryMemoryJob } from "./memory-jobs.ts";
import type { MemoryJob } from "./memory-jobs.ts";
import { MemoryJobRows } from "./categories/MemoryJobsStatus.tsx";

const failed: MemoryJob = {
  session_id: "sess:one", job_id: "job-1", status: "failed", pending_turns: 1,
  pending_tokens: 180, attempt: 3, error_code: "invalid_output", error: "提炼结果格式无效",
  has_frozen_facts: false, updated_at: "2026-09-08T12:00:00Z", last_completed_at: "",
};
const snapshot = { counts: { failed: 1 }, total: 1, jobs: [failed], truncated: false };

test("job API carries administrator authorization and the observed job fence", async (context) => {
  const calls: Array<{url:string; init?:RequestInit}> = [];
  context.mock.method(globalThis, "fetch", async (url: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return Response.json(snapshot);
  });
  assert.deepEqual(await fetchMemoryJobs(" secret "), snapshot);
  await retryMemoryJob(failed, " secret ");
  assert.equal(calls[0].url, "/api/memory/jobs");
  assert.equal(new Headers(calls[0].init?.headers).get("Authorization"), "Bearer secret");
  assert.equal(calls[1].url, "/api/memory/jobs/sess%3Aone/retry");
  assert.deepEqual(JSON.parse(calls[1].init?.body as string), { job_id: "job-1" });
});

test("malformed job response never pretends to be an empty success", () => {
  assert.throws(() => readMemoryJobs({ jobs: [] }));
  assert.throws(() => readMemoryJobs({ ...snapshot, jobs: [{ ...failed, pending_tokens: -1 }] }));
  assert.equal(isMemoryJobActive({ status: "retry_wait" }), true);
  assert.equal(isMemoryJobActive(failed), false);
});

test("failed row keeps its recovery adjacent and disables retry while gated or busy", () => {
  Object.assign(globalThis, { React });
  const render = (enabled: boolean, busy: string | null) => renderToStaticMarkup(createElement(MemoryJobRows, {
    jobs: [failed, { ...failed, session_id: "done", status: "completed" }], enabled, busy, onRetry: () => {},
  }));
  const available = render(true, null);
  assert.match(available, /提炼结果格式无效/);
  assert.match(available, /aria-label="重试会话 sess:one 的记忆整理"/);
  assert.doesNotMatch(available, / disabled=""/);
  assert.doesNotMatch(available, /会话 done/);
  assert.match(render(false, null), / disabled=""/);
  assert.match(render(true, "sess:one"), /正在重试/);
});
