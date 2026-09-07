import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { CORE_PAGE_SCROLL_MODE, CORE_TAB_IDS } from "../core-tabs";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..");

test("every core page declares exactly one shell scroll mode", () => {
  assert.deepEqual(Object.keys(CORE_PAGE_SCROLL_MODE), [...CORE_TAB_IDS]);
  assert.ok(Object.values(CORE_PAGE_SCROLL_MODE).includes("contained"));
  assert.ok(Object.values(CORE_PAGE_SCROLL_MODE).includes("document"));

  const appSource = readFileSync(join(srcRoot, "App.tsx"), "utf8");
  assert.match(appSource, /<main className="min-h-0 min-w-0 flex-1 overflow-hidden pt-14"/);
  assert.match(appSource, /data-page-scroll-mode=\{pageScrollMode\}/);
});

test("contained core pages do not repeat viewport height arithmetic", () => {
  const containedPages = [
    "ChatPage.tsx",
    "DashboardPage.tsx",
    "GraphPage.tsx",
    "RoundtablePage.tsx",
    "OrchestrationPage.tsx",
    "WorkflowPage.tsx",
    "ResourceMarketplacePage.tsx",
  ];

  for (const page of containedPages) {
    const source = readFileSync(join(srcRoot, "pages", page), "utf8");
    assert.equal(source.includes("100dvh-3.5rem"), false, page);
  }

  const workflowFillSource = readFileSync(
    join(srcRoot, "components/workflow/TaskParamFill.tsx"),
    "utf8",
  );
  assert.equal(workflowFillSource.includes("100dvh-3.5rem"), false);
});

test("shared ScrollArea contains intrinsic width and scroll chaining", () => {
  const source = readFileSync(join(srcRoot, "components/ui/scroll-area.tsx"), "utf8");
  assert.match(source, /relative min-h-0 min-w-0 overflow-hidden/);
  assert.match(source, /min-h-0 min-w-0 overscroll-contain/);
  assert.match(source, /\[&>div\]:!block/);
  assert.match(source, /\[&>div\]:!min-w-0/);
  assert.match(source, /\[&>div\]:!w-full/);

  const previewSource = readFileSync(
    join(srcRoot, "components/orchestration/PreviewPanel.tsx"),
    "utf8",
  );
  assert.equal(previewSource.includes("data-radix-scroll-area-viewport"), false);
});

test("prompt inspection content wraps locally and uses accurate labels", () => {
  const promptSource = readFileSync(join(srcRoot, "components/PromptPanel.tsx"), "utf8");
  const messageSource = readFileSync(join(srcRoot, "components/MessageItem.tsx"), "utf8");
  const pageSource = readFileSync(join(srcRoot, "pages/SystemPromptPage.tsx"), "utf8");

  assert.match(promptSource, /当前有效入模上下文/);
  assert.match(promptSource, /label: "入模消息"/);
  assert.equal(promptSource.includes("这是 LLM 实际看到的会话历史"), false);
  assert.match(promptSource, /\[overflow-wrap:anywhere\]/);
  assert.match(messageSource, /min-w-0/);
  assert.match(messageSource, /\[overflow-wrap:anywhere\]/);
  assert.match(pageSource, /LLM 提示词与工具/);
  assert.equal(pageSource.includes("会话元信息"), false);
  assert.equal(pageSource.includes("当前入模消息"), false);
  assert.equal(pageSource.includes("promptData.messages.map"), false);
  assert.match(pageSource, /ToolDefinitionList/);
  assert.equal(pageSource.includes("bind_tools"), false);
  assert.equal(pageSource.includes("OpenAI Function Calling"), false);
  assert.equal(pageSource.includes("JSON.stringify(tool.schema"), false);
});

test("system prompt tool definitions translate schema without exposing raw JSON", () => {
  const listSource = readFileSync(join(srcRoot, "components/ToolDefinitionList.tsx"), "utf8");

  assert.match(listSource, /readToolSchemaView/);
  assert.match(listSource, /aria-expanded/);
  assert.match(listSource, /role="region"/);
  assert.match(listSource, /divide-y/);
  assert.match(listSource, /<Wrench/);
  assert.match(listSource, /min-h-14/);
  assert.match(listSource, /\[overflow-wrap:anywhere\]/);
  assert.match(listSource, /min-w-0/);
  assert.equal(listSource.includes("<details"), false);
  assert.equal(listSource.includes("<article"), false);
  assert.equal(listSource.includes("原始 JSON"), false);
  assert.equal(listSource.includes("JSON.stringify"), false);
  assert.equal(listSource.includes("line-clamp-1"), false);
  assert.equal(listSource.includes("bind_tools"), false);
  assert.equal(listSource.includes("novelbuilt"), false);
  assert.equal(listSource.includes("Portal"), false);
});
