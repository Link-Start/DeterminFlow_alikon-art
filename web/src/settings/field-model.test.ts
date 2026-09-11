import assert from "node:assert/strict";
import test from "node:test";

import type { ConfigItemMeta } from "../types";
import {
  displayFieldValue,
  fieldSpecFromConfigMeta,
  isEnumField,
  isSensitiveField,
  numericDisplayValue,
  parseNumericInput,
  reconcileEditedAfterSave,
  updateEditedValue,
} from "./field-model.ts";

const secretItem: ConfigItemMeta = {
  key: "API_TOKEN",
  label: "访问令牌",
  group: "system",
  type: "string",
  sensitive: true,
};

test("maps default, enum, sensitive and readonly field behavior", () => {
  const secret = fieldSpecFromConfigMeta(secretItem);
  assert.equal(secret.kind, "sensitive");
  assert.equal(isSensitiveField(secret), true);
  assert.equal(displayFieldValue({ ...secret, default: "from-schema" }, undefined), "from-schema");
  assert.equal(displayFieldValue(secret, "kept"), "kept");

  const enumerated = fieldSpecFromConfigMeta({
    key: "CODING_CMD_MODE",
    label: "命令审批模式",
    group: "coding",
    type: "select",
    options: ["allow", "deny"],
  });
  assert.equal(isEnumField(enumerated), true);
  assert.deepEqual(enumerated.options, [
    { value: "allow", label: "allow" },
    { value: "deny", label: "deny" },
  ]);

  const locked = fieldSpecFromConfigMeta({
    key: "WEB_HOST",
    label: "Web 服务地址",
    group: "system",
    type: "string",
    readonly: true,
  });
  assert.equal(locked.kind, "readonly");
});

test("scaled numeric fields convert display units without inventing defaults", () => {
  const spec = {
    id: "general.compactionThreshold",
    label: "压缩触发阈值",
    kind: "number" as const,
    min: 50,
    max: 95,
    step: 5,
    scale: 100,
  };
  assert.equal(numericDisplayValue(spec, 0.8), 80);
  assert.equal(numericDisplayValue(spec, undefined), "");
  assert.equal(parseNumericInput(spec, "75"), 0.75);
});

test("keeps in-flight edits after a partial group save", () => {
  const next = reconcileEditedAfterSave({
    captured: { MAX_SUB_SESSIONS: 4 },
    edited: { MAX_SUB_SESSIONS: 4, CODING_CMD_TIMEOUT: 12 },
    nextConfig: { MAX_SUB_SESSIONS: 4, CODING_CMD_TIMEOUT: 30 },
    savedKeys: ["MAX_SUB_SESSIONS"],
  });
  assert.deepEqual(next, { CODING_CMD_TIMEOUT: 12 });
});


test("returning to the old value during save remains an unsaved edit", () => {
  const edited = updateEditedValue({limit: 4}, {limit: 2}, "limit", 2, new Set(["limit"]));
  assert.deepEqual(reconcileEditedAfterSave({edited, captured: {limit: 4}, nextConfig: {limit: 4}, savedKeys: ["limit"]}), {limit: 2});
  assert.deepEqual(updateEditedValue({limit: 4}, {limit: 2}, "limit", 2, new Set()), {});
});
