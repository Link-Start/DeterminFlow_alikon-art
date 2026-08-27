import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const source = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "NodeMessageDrawer.tsx"),
  "utf8",
);

test("node message drawer follows output inside its own viewport", () => {
  assert.match(source, /useAutoFollowOutput/);
  assert.match(source, /reasoningViewportRef/);
  assert.match(source, /conversation-output-scroll/);
  assert.equal(source.includes("scrollIntoView"), false);
});
