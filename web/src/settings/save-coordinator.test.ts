import assert from "node:assert/strict";
import test from "node:test";

import {
  nextDraftAfterSave,
  saveDirtyCategories,
  saveOutcomeCopy,
  summarizeCategorySaves,
} from "./save-coordinator.ts";
import type { SettingsCategoryStore } from "./types.ts";

test("retains drafts that change during a successful save", () => {
  const result = nextDraftAfterSave({
    savedDraft: { enabled: true },
    currentDraft: { enabled: false },
    equal: (left, right) => left.enabled === right.enabled,
  });
  assert.deepEqual(result, { baseline: { enabled: true }, dirty: true });
});

test("clears dirty state only when the saved draft is still current", () => {
  const result = nextDraftAfterSave({
    savedDraft: { enabled: true },
    currentDraft: { enabled: true },
    equal: (left, right) => left.enabled === right.enabled,
  });
  assert.deepEqual(result, { baseline: { enabled: true }, dirty: false });
});

test("save coordinates dirty categories and reports per-category failures", async () => {
  const saved: string[] = [];
  const stores: SettingsCategoryStore[] = [
    {
      id: "agent",
      title: "多 Agent",
      dirty: true,
      save: async () => { saved.push("agent"); },
      discard: () => undefined,
    },
    {
      id: "memory",
      title: "记忆",
      dirty: true,
      save: async () => { throw new Error("提供者未运行"); },
      discard: () => undefined,
    },
    {
      id: "system",
      title: "系统",
      dirty: false,
      save: async () => { saved.push("system"); },
      discard: () => undefined,
    },
  ];

  const results = await saveDirtyCategories(stores);
  const summary = summarizeCategorySaves(results);
  const outcome = saveOutcomeCopy(results);

  assert.deepEqual(saved, ["agent"]);
  assert.equal(summary.allSucceeded, false);
  assert.equal(summary.anySucceeded, true);
  assert.equal(summary.failed[0]?.error, "提供者未运行");
  assert.equal(outcome?.tone, "warning");
  assert.match(outcome?.text || "", /记忆 保存失败/);
  assert.equal(outcome?.text.includes("已保存 2 个分类"), false);
  assert.equal(/全部保存成功|保存成功/.test(outcome?.text || ""), false);
});

test("does not claim success when every dirty category fails", async () => {
  const results = await saveDirtyCategories([
    {
      id: "compression",
      title: "压缩",
      dirty: true,
      save: async () => { throw new Error("校验失败"); },
      discard: () => undefined,
    },
  ]);
  const outcome = saveOutcomeCopy(results);
  assert.equal(outcome?.tone, "danger");
  assert.match(outcome?.text || "", /压缩 保存失败/);
});
