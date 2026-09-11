import assert from "node:assert/strict";
import test from "node:test";
import { readWorkspaceSettings, workspaceFieldGroups } from "./workspace-model";
import { CORE_FALLBACK_SECTIONS } from "./section-model";

const payload = { settings: { enabled: false, provider_id: "storage", context_enabled: true,
  context_token_budget: 2000, timeout_seconds: 15, local_main_enabled: false },
  providers: [{ id: "storage", name: "Storage", healthy: false, reason: "unavailable" }],
  effective_enabled: false, reason: "disabled" };

test("workspace response is validated and provider choices come from registration", () => {
  const parsed = readWorkspaceSettings(payload);
  const fields = workspaceFieldGroups(parsed)[0].fields;
  assert.deepEqual(fields.find((field) => field.id === "provider_id")?.options, [{ value: "storage", label: "Storage" }]);
  assert.equal(parsed.settings.enabled, false);
  assert.throws(() => readWorkspaceSettings({ ...payload, settings: { enabled: true } }));
  assert.throws(() => readWorkspaceSettings({ ...payload, providers: [{ id: "bad" }] }));
  assert.ok(CORE_FALLBACK_SECTIONS.find((section) => section.id === "workspace"));
});
