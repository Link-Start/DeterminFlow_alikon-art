import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ModelContextDetails from "./ModelContextDetails";

(globalThis as typeof globalThis & { React: typeof React }).React = React;

function render(context: Record<string, unknown>) {
  return renderToStaticMarkup(React.createElement(ModelContextDetails, { context }));
}

test("empty successful recall has an explicit field separate from product context", () => {
  const context = { locale: "zh-CN", long_term_memory: { items: [], trust: "low" } };
  const html = render(context);
  assert.match(html, /长期记忆：<\/span><code>\[\]<\/code>/);
  assert.match(html, /产品上下文/);
  assert.match(html, /zh-CN/);
  assert.doesNotMatch(html, /long_term_memory|trust|耗时/);
  assert.deepEqual(context.long_term_memory, { items: [], trust: "low" });
});

test("recalled memories retain their content and source without duplication", () => {
  const html = render({ long_term_memory: {
    items: [{ id: "m1", text: "remembered fact", provenance: "source-message" }],
  } });
  assert.match(html, /长期记忆：/);
  assert.equal(html.match(/remembered fact/g)?.length, 1);
  assert.match(html, /source-message/);
  assert.doesNotMatch(html, /产品上下文/);
});

test("missing or malformed recall never becomes an empty success", () => {
  for (const context of [
    { locale: "zh-CN" },
    { long_term_memory: null },
    { long_term_memory: { items: null } },
    { long_term_memory: { items: "invalid" } },
  ]) {
    assert.doesNotMatch(render(context), /长期记忆：/);
  }
});

test("memory text is escaped rather than interpreted as markup", () => {
  const html = render({ long_term_memory: { items: [{ text: "<script>unsafe</script>" }] } });
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});


test("workspace disclosure keeps file references and excludes routing identities", () => {
  const html = render({ workspace: { status: "available", _binding: "private-marker", scope: "private-scope",
    documents: [{ path: "notes/INDEX.md", version: "v1", text: "User project" }], files: [], policy: "private-policy" } });
  assert.match(html, /工作区/);
  assert.match(html, /User project/);
  assert.match(html, /notes\/INDEX.md/);
  assert.doesNotMatch(html, /private-marker|private-scope|private-policy|产品上下文/);
  assert.match(render({ workspace: { status: "available", files: [], documents: [] } }), /<code>\[\]<\/code>/);
  assert.match(render({ workspace: { status: "unavailable" } }), /暂不可用/);
});
