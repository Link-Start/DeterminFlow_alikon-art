import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_VISIBLE_TOASTS,
  enqueueToast,
  type Toast,
} from "./use-toast";

function toast(id: string, title: string): Toast {
  return { id, title, variant: "success" };
}

test("toast queue replaces duplicate feedback with the latest item", () => {
  const current = [toast("old", "已收藏")];
  const next = enqueueToast(current, toast("new", "已收藏"));

  assert.deepEqual(next, [toast("new", "已收藏")]);
});

test("toast queue keeps only the latest visible feedback", () => {
  const current = [
    toast("1", "一"),
    toast("2", "二"),
    toast("3", "三"),
  ];
  const next = enqueueToast(current, toast("4", "四"));

  assert.equal(MAX_VISIBLE_TOASTS, 3);
  assert.deepEqual(next.map((item) => item.id), ["2", "3", "4"]);
});
