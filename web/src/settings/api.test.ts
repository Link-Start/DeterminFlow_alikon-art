import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchCompressionConfig,
  fetchMemorySettings,
  fetchSettingsSections,
  updateCompressionConfig,
  updateMemorySettings,
} from "./api.ts";
import { CORE_FALLBACK_SECTIONS } from "./section-model.ts";

test("settings and memory APIs follow the shared contract", async (context) => {
  const requests: Array<{ url: string; method: string; body: unknown; authorization: string | null }> = [];
  context.mock.method(globalThis, "fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    requests.push({ url, method: init?.method ?? "GET", body, authorization: new Headers(init?.headers).get("Authorization") });
    if (url === "/api/settings/sections") {
      return new Response(JSON.stringify({
        sections: [{
          id: "appearance",
          title: "外观",
          owner: "core",
          kind: "core",
          order: 10,
          description: "",
        }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "/api/memory/settings" && (init?.method ?? "GET") === "GET") {
      return new Response(JSON.stringify({
        settings: {
          enabled: false,
          external_enabled: false,
          provider_id: "",
          auto_recall_enabled: true,
          recall_mode: "every",
          recall_timeout_seconds: 2,
          recall_max_chars: 4000,
          recall_max_bytes: 8000,
          auto_consolidate_enabled: true,
          consolidate_idle_seconds: 1800,
          consolidate_length_tokens: 20000,
          max_batch_turns: 8,
          max_concurrent_jobs: 2,
          max_retries: 3,
          lease_seconds: 30,
          extract_timeout_seconds: 5,
          extract_model: "",
        },
        providers: [],
        effective_enabled: false,
        reason: "未启用",
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "/api/memory/settings") {
      return new Response(JSON.stringify({
        settings: body.settings,
        providers: [],
        effective_enabled: false,
        reason: "未启用",
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url === "/api/compression/config") {
      return new Response(JSON.stringify({
        general: { enabled: true, compactionThreshold: 0.8 },
        micro_compact: {
          maxToolResults: 15,
          toolResultTokenRatio: 0.4,
          keepRecentToolResults: 5,
          placeholder: "[Content compacted]",
        },
        full_compact: { keepRecentTokens: 51200, maxRetryCount: 2, summaryTokenBudget: 4096 },
        reactive_compact: { maxRetryCount: 5 },
        post_compact: { maxFilesToRead: 5, maxTokensPerFile: 5000 },
        transcript: { logsDir: "./logs/compression" },
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("missing", { status: 404 });
  });

  const sections = await fetchSettingsSections();
  const memory = await fetchMemorySettings();
  const saved = await updateMemorySettings(memory.settings, " test-admin-token ");
  await fetchCompressionConfig();
  await updateCompressionConfig({
    general: { enabled: true, compactionThreshold: 0.8 },
    micro_compact: {
      maxToolResults: 15,
      toolResultTokenRatio: 0.4,
      keepRecentToolResults: 5,
      placeholder: "[Content compacted]",
    },
    full_compact: { keepRecentTokens: 51200, maxRetryCount: 2, summaryTokenBudget: 4096 },
    reactive_compact: { maxRetryCount: 5 },
    post_compact: { maxFilesToRead: 5, maxTokensPerFile: 5000 },
    transcript: { logsDir: "./logs/compression" },
  });

  assert.equal(sections[0].id, "appearance");
  assert.equal(saved.settings.enabled, false);
  assert.deepEqual(requests.map((item) => `${item.method} ${item.url}`), [
    "GET /api/settings/sections",
    "GET /api/memory/settings",
    "PUT /api/memory/settings",
    "GET /api/compression/config",
    "PUT /api/compression/config",
  ]);
  assert.deepEqual(requests[2].body, { settings: memory.settings });
  assert.equal(requests[2].authorization, "Bearer test-admin-token");
});

test("falls back to core sections when the descriptor list is empty", async (context) => {
  context.mock.method(globalThis, "fetch", async () => (
    new Response(JSON.stringify({ sections: [] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })
  ));
  const sections = await fetchSettingsSections();
  assert.deepEqual(sections.map((section) => section.id), CORE_FALLBACK_SECTIONS.map((section) => section.id));
});
