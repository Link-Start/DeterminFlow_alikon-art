import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import MentionPicker from "./MentionPicker";
import { MENTION_FILE_OPTION, MENTION_TYPE_OPTIONS } from "./mentionCatalog";

(globalThis as typeof globalThis & { React: typeof React }).React = React;
const { createElement } = React;

const unused = {
  onActiveIndexChange: () => undefined,
  onSelectType: () => undefined,
  onSelectResource: () => undefined,
  onPreviewType: () => undefined,
  typeOptions: [MENTION_FILE_OPTION, ...MENTION_TYPE_OPTIONS],
  selectedType: null,
  onRetry: () => undefined,
  onLoadMore: () => undefined,
};

test("type layer lists a direct file action before the six local resource classes", () => {
  const html = renderToStaticMarkup(createElement(MentionPicker, {
    open: true,
    layer: "types",
    resourceType: null,
    sessionId: "s1",
    anchor: { top: 40, bottom: 60, left: 24, right: 40, height: 20 },
    items: [],
    status: "idle",
    error: null,
    hasMore: false,
    activeIndex: 0,
    listboxId: "mention-list",
    ...unused,
  }));

  assert.match(html, /role="listbox"/);
  assert.ok(html.indexOf("文件附件") < html.indexOf("Prompt 提示词"));
  assert.match(html, /Prompt 提示词/);
  assert.match(html, /Agent 智能体/);
  assert.match(html, /Skill 技能/);
  assert.match(html, /Rule 规则/);
  assert.match(html, /Workflow 工作流/);
  assert.match(html, />会话</);
  assert.doesNotMatch(html, /正在加载|没有匹配的资源/);
});

test("resource layer shows unavailable reason and does not invent an action button", () => {
  const html = renderToStaticMarkup(createElement(MentionPicker, {
    open: true,
    layer: "resources",
    resourceType: "skill",
    sessionId: "s1",
    anchor: { top: 40, bottom: 60, left: 24, right: 40, height: 20 },
    items: [{
      resource_type: "skill",
      resource_id: "skill-offline",
      name: "离线技能",
      description: "查找",
      source: "core",
      reference_text: "[skill:skill-offline] 离线技能",
      available: false,
      unavailable_reason: "未启用",
    }],
    status: "ready",
    error: null,
    hasMore: true,
    activeIndex: 0,
    listboxId: "mention-list",
    ...unused,
  }));

  assert.match(html, /离线技能/);
  assert.match(html, /未启用/);
  assert.match(html, /aria-disabled="true"/);
  assert.match(html, /加载更多/);
  assert.equal((html.match(/role="listbox"/g) ?? []).length, 2);
  assert.match(html, /Prompt 提示词/);
  assert.match(html, /aria-expanded="true"/);
});

test("empty, loading and error states stay recoverable", () => {
  const loading = renderToStaticMarkup(createElement(MentionPicker, {
    open: true,
    layer: "resources",
    resourceType: "agent",
    sessionId: "s1",
    anchor: { top: 10, bottom: 30, left: 8, right: 20, height: 20 },
    items: [],
    status: "loading",
    error: null,
    hasMore: false,
    activeIndex: 0,
    listboxId: "mention-list",
    ...unused,
  }));
  const empty = renderToStaticMarkup(createElement(MentionPicker, {
    open: true,
    layer: "resources",
    resourceType: "agent",
    sessionId: "s1",
    anchor: { top: 10, bottom: 30, left: 8, right: 20, height: 20 },
    items: [],
    status: "empty",
    error: null,
    hasMore: false,
    activeIndex: 0,
    listboxId: "mention-list",
    ...unused,
  }));
  const failed = renderToStaticMarkup(createElement(MentionPicker, {
    open: true,
    layer: "resources",
    resourceType: "agent",
    sessionId: "s1",
    anchor: { top: 10, bottom: 30, left: 8, right: 20, height: 20 },
    items: [],
    status: "error",
    error: "资源列表加载失败",
    hasMore: false,
    activeIndex: 0,
    listboxId: "mention-list",
    ...unused,
  }));

  assert.match(loading, /正在搜索/);
  assert.match(empty, /没有匹配的资源/);
  assert.match(failed, /资源列表加载失败/);
  assert.match(failed, /重试/);
});
