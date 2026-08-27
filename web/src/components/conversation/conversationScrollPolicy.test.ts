import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

test("composer keeps overflow on an outer scroller, not the contenteditable editor", () => {
  const source = readFileSync(join(here, "ConversationComposer.tsx"), "utf8");
  assert.match(source, /ref=\{scrollRef\}/);
  assert.match(source, /conversation-composer-scroll/);
  assert.equal(
    /className=\{`conversation-composer-editor[\s\S]*?overflow-y-auto/.test(source),
    false,
  );
});

test("timeline follow uses a local overflow container", () => {
  const source = readFileSync(join(here, "ConversationTimeline.tsx"), "utf8");
  assert.match(source, /conversation-output-scroll/);
  assert.equal(source.includes("scrollIntoView"), false);
});
