import assert from "node:assert/strict";
import test from "node:test";

import { resolveComposerKey } from "./mentionKeyboard";

const base = {
  shiftKey: false,
  altKey: false,
  metaKey: false,
  ctrlKey: false,
  isComposing: false,
  keyCode: 0,
  mentionOpen: false,
  mentionLayer: null as "types" | "resources" | null,
};

test("Enter sends only when the mention panel is closed and IME is idle", () => {
  assert.equal(resolveComposerKey({ ...base, key: "Enter" }).type, "send");
  assert.equal(
    resolveComposerKey({ ...base, key: "Enter", mentionOpen: true, mentionLayer: "types" }).type,
    "mention-confirm",
  );
  assert.equal(
    resolveComposerKey({ ...base, key: "Enter", isComposing: true }).type,
    "pass",
  );
  assert.equal(
    resolveComposerKey({
      ...base,
      key: "Enter",
      keyCode: 229,
      mentionOpen: true,
      mentionLayer: "resources",
    }).type,
    "pass",
  );
});

test("IME composition and keyCode 229 never intercept candidate selection", () => {
  for (const key of ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Enter", "Escape", "Tab"]) {
    assert.equal(
      resolveComposerKey({
        ...base,
        key,
        isComposing: true,
        mentionOpen: true,
        mentionLayer: "resources",
      }).type,
      "pass",
    );
    assert.equal(
      resolveComposerKey({
        ...base,
        key,
        keyCode: 229,
        mentionOpen: true,
        mentionLayer: "types",
      }).type,
      "pass",
    );
  }
});

test("horizontal arrows enter and leave the submenu without sending", () => {
  assert.equal(resolveComposerKey({
    ...base, key: "ArrowRight", mentionOpen: true, mentionLayer: "types",
  }).type, "mention-confirm");
  assert.equal(resolveComposerKey({
    ...base, key: "ArrowLeft", mentionOpen: true, mentionLayer: "resources",
  }).type, "mention-back");
  assert.equal(resolveComposerKey({
    ...base, key: "ArrowLeft", mentionOpen: false,
  }).type, "pass");
});

test("mention keyboard navigates, returns a layer, and does not trap Tab", () => {
  assert.deepEqual(
    resolveComposerKey({
      ...base,
      key: "ArrowDown",
      mentionOpen: true,
      mentionLayer: "types",
    }),
    { type: "mention-move", delta: 1 },
  );
  assert.equal(
    resolveComposerKey({
      ...base,
      key: "Escape",
      mentionOpen: true,
      mentionLayer: "resources",
    }).type,
    "mention-back",
  );
  assert.equal(
    resolveComposerKey({
      ...base,
      key: "Escape",
      mentionOpen: true,
      mentionLayer: "types",
    }).type,
    "mention-close",
  );
  assert.equal(
    resolveComposerKey({
      ...base,
      key: "Tab",
      mentionOpen: true,
      mentionLayer: "resources",
    }).type,
    "mention-tab",
  );
});

test("Shift+Enter inserts a newline even while the mention panel is open", () => {
  assert.equal(
    resolveComposerKey({
      ...base,
      key: "Enter",
      shiftKey: true,
      mentionOpen: true,
      mentionLayer: "types",
    }).type,
    "newline",
  );
});

test("Backspace and Delete request adjacent token removal", () => {
  assert.deepEqual(
    resolveComposerKey({ ...base, key: "Backspace" }),
    { type: "delete-adjacent", direction: "backward" },
  );
  assert.deepEqual(
    resolveComposerKey({ ...base, key: "Delete" }),
    { type: "delete-adjacent", direction: "forward" },
  );
});
