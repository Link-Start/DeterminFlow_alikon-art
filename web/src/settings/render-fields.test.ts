import assert from "node:assert/strict";
import test from "node:test";
import React, { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { parsePluginSettingsSchema, schemaHasConfigurableFields } from "../extensions/plugin-model.ts";
import { SettingsCategoryPanel } from "./SettingsCategoryPanel.tsx";
import { SettingsFieldList, SettingsFieldRow } from "./SettingsFieldControl.tsx";
import { SettingsWorkspace } from "./SettingsWorkspace.tsx";
import { PluginSettingsFields } from "./PluginSettingsFields.tsx";

test("numeric plugin values render and deprecated migration fields stay hidden", () => {
  // The Node test runner uses the classic JSX transform; Vite uses automatic JSX.
  Object.assign(globalThis, { React });
  const parsed = parsePluginSettingsSchema({type: "object", properties: {
    timeout: {type: "number", title: "超时", default: 60},
    retries: {type: "integer", title: "重试", default: 3},
    legacy: {type: "string", title: "旧配置", deprecated: true},
  }});
  assert.equal(parsed.ok, true);
  if (!parsed.ok) return;
  const html = renderToStaticMarkup(createElement(PluginSettingsFields, {
    schema: parsed.schema, settings: {timeout: 2.5, legacy: "first"}, errors: {}, onChange: () => {},
  }));
  assert.match(html, /value="2.5"/);
  assert.match(html, /value="3"/);
  assert.doesNotMatch(html, /旧配置|value="first"/);
  assert.equal(schemaHasConfigurableFields({type: "object", properties: {legacy: parsed.schema.properties.legacy}}), false);
});


test("cards render independent disclosure controls while retaining collapsed field values", () => {
  Object.assign(globalThis, { React });
  const html = renderToStaticMarkup(createElement(SettingsWorkspace, null,
    ...["appearance", "models", "memory", "plugin:demo:settings"].map((id) =>
      createElement(SettingsCategoryPanel, { key: id, sectionId: id, title: id },
        createElement("input", { defaultValue: `draft-${id}` }),
      ),
    ),
  ));
  assert.equal((html.match(/aria-expanded="true"/g) || []).length, 2);
  assert.equal((html.match(/aria-expanded="false"/g) || []).length, 2);
  assert.match(html, /id="memory-content" hidden=""/);
  assert.match(html, /value="draft-memory"/);
  assert.match(html, /id="plugin:demo:settings-content" hidden=""/);
  assert.match(html, /value="draft-plugin:demo:settings"/);
  assert.doesNotMatch(html, /<nav/);
});


test("category icons preserve established colors without tinting titles", () => {
  Object.assign(globalThis, { React });
  for (const [id, color] of Object.entries({
    agent: "text-info", roundtable: "text-success", coding: "text-destructive",
    compression: "text-warning", system: "text-warning",
  })) {
    const html = renderToStaticMarkup(createElement(SettingsWorkspace, null,
      createElement(SettingsCategoryPanel, { sectionId: id, title: id }),
    ));
    assert.match(html, new RegExp(`<svg[^>]+class="[^"]*shrink-0 ${color}"`));
    assert.match(html, new RegExp(`<span class="text-base font-semibold text-foreground">${id}</span>`));
  }
});

test("shared field rows use an unboxed continuous surface with quiet separators", () => {
  Object.assign(globalThis, { React });
  const html = renderToStaticMarkup(createElement(SettingsFieldList, null,
    ...["workspace", "command"].map((id) => createElement(SettingsFieldRow, {
      key: id, spec: { id, label: id, kind: "string" }, value: `${id}-value`, onChange: () => {},
    })),
  ));
  assert.match(html, /divide-y divide-border\/30/);
  assert.doesNotMatch(html, /odd:bg-|even:bg-|rounded-lg border/);
  assert.equal((html.match(/sm:items-center/g) || []).length, 2);
  for (const id of ["workspace", "command"]) {
    assert.match(html, new RegExp(`for="${id}"`));
    assert.match(html, new RegExp(`id="${id}"`));
    assert.match(html, new RegExp(`value="${id}-value"`));
  }
});
