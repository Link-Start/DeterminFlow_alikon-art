import assert from "node:assert/strict";
import test from "node:test";

import {
  collectPinnedItems,
  normalizePinnedSessionIds,
  prunePinnedSessionIds,
  readPinnedSessionIds,
  togglePinnedSessionId,
  shouldShowRegularSessionHeading,
  writePinnedSessionIds,
} from "./session-pins";

test("normalizePinnedSessionIds keeps first-seen order and drops junk", () => {
  assert.deepEqual(
    normalizePinnedSessionIds(["b", "", "a", "b", 1, "c"]),
    ["b", "a", "c"],
  );
  assert.deepEqual(normalizePinnedSessionIds({ ids: ["a"] }), []);
});

test("togglePinnedSessionId pins to the front and unpins in place", () => {
  assert.deepEqual(togglePinnedSessionId(["a", "b"], "c"), ["c", "a", "b"]);
  assert.deepEqual(togglePinnedSessionId(["c", "a", "b"], "a"), ["c", "b"]);
  assert.deepEqual(togglePinnedSessionId(["a"], ""), ["a"]);
});

test("collectPinnedItems follows pin order and skips missing ids", () => {
  const items = [
    { id: "a", name: "A" },
    { id: "b", name: "B" },
    { id: "c", name: "C" },
  ];
  assert.deepEqual(
    collectPinnedItems(items, (item) => item.id, ["c", "missing", "a"]),
    [{ id: "c", name: "C" }, { id: "a", name: "A" }],
  );
});

test("prunePinnedSessionIds drops ids that are no longer present", () => {
  assert.deepEqual(prunePinnedSessionIds(["gone", "keep"], ["keep", "other"]), ["keep"]);
});

test("regular session heading stays hidden until a pinned group exists", () => {
  assert.equal(shouldShowRegularSessionHeading(0, 3), false);
  assert.equal(shouldShowRegularSessionHeading(2, 0), false);
  assert.equal(shouldShowRegularSessionHeading(1, 2), true);
});

test("read and write pinned ids through a storage double", () => {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
  };

  assert.deepEqual(readPinnedSessionIds(storage), []);
  writePinnedSessionIds(["z", "z", "y"], storage);
  assert.deepEqual(readPinnedSessionIds(storage), ["z", "y"]);
  writePinnedSessionIds(["not-json"] as unknown as string[], {
    getItem: () => "{",
    setItem: () => {
      throw new Error("blocked");
    },
  });
  assert.deepEqual(readPinnedSessionIds({ getItem: () => "{", setItem: () => undefined }), []);
});
