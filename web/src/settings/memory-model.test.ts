import assert from "node:assert/strict";
import test from "node:test";

import { memoryFieldGroups } from "./memory-fields.ts";
import {
  describeMemoryEnableGate,
  memoryActivationCopy,
  readMemorySettingsResponse,
} from "./memory-model.ts";
import type { MemorySettings } from "./types.ts";

const SETTINGS: MemorySettings = {
  enabled: true,
  external_enabled: true,
  provider_id: "demo-memory",
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
};

test("consumes returned memory settings and does not invent defaults", () => {
  const parsed = readMemorySettingsResponse({
    settings: SETTINGS,
    providers: [{
      id: "demo-memory",
      name: "Demo",
      status: "running",
      healthy: true,
      reason: "",
    }],
    effective_enabled: false,
    reason: "提供者未运行",
  });
  assert.equal(parsed?.settings.extract_model, "");
  assert.equal(parsed?.effective_enabled, false);
  assert.equal(parsed?.reason, "提供者未运行");
  assert.equal(readMemorySettingsResponse({ settings: { enabled: true } }), null);
});

test("blocks enabling external memory but still allows closing it", () => {
  const blocked = describeMemoryEnableGate({
    settings: SETTINGS,
    providers: [{
      id: "demo-memory",
      name: "Demo",
      status: "failed",
      healthy: false,
      reason: "连接失败",
    }],
    plugins: [{
      id: "demo-memory",
      runtime_status: "failed",
      active_enabled: false,
      desired_enabled: true,
      pending_action: null,
      restart_required: false,
    }],
  });
  assert.equal(blocked.blocked, true);
  assert.match(blocked.reason || "", /关闭记忆仍可保存/);

  const closing = describeMemoryEnableGate({
    settings: { ...SETTINGS, enabled: false, external_enabled: false },
    providers: [],
    plugins: [],
  });
  assert.equal(closing.blocked, false);
});

test("keeps activation copy truthful when restart is required", () => {
  const copy = memoryActivationCopy({
    effectiveEnabled: false,
    reason: "等待重启",
    plugin: {
      id: "demo-memory",
      runtime_status: "running",
      active_enabled: true,
      desired_enabled: true,
      pending_action: null,
      restart_required: true,
    },
  });
  assert.equal(copy.label, "当前未生效");
  assert.match(copy.detail || "", /重启/);
});

test("uses returned schema titles when present and has no hindsight ids", () => {
  const groups = memoryFieldGroups({
    type: "object",
    title: "记忆",
    properties: {
      enabled: { type: "boolean", title: "启用记忆" },
      provider_id: { type: "string", title: "记忆提供者" },
    },
  });
  assert.equal(groups[0].fields[0].label, "启用记忆");
  assert.equal(groups[0].fields[2].kind, "select");
  assert.equal(JSON.stringify(groups).toLowerCase().includes("hindsight"), false);
});


test("pending provider config cannot enable memory; disabling remains available", () => {
  const providers = [{id: "demo-memory", name: "Demo", status: "running", healthy: true, reason: ""}];
  const plugins = [{id: "demo-memory", runtime_status: "running", active_enabled: true,
    desired_enabled: true, pending_action: null, restart_required: true}];
  assert.equal(describeMemoryEnableGate({settings: SETTINGS, providers, plugins}).blocked, true);
  assert.equal(describeMemoryEnableGate({settings: {...SETTINGS, enabled: false}, providers, plugins}).blocked, false);
});
