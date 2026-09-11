import assert from "node:assert/strict";
import test from "node:test";

import {
  formatComposerMessage,
  formatComposerParts,
  getDroppedFileName,
  shouldOfferComposerExpansion,
} from "./conversationComposerModel";

test("file bubbles expand to absolute paths at their inline positions", () => {
  assert.equal(
    formatComposerParts([
      { type: "text", value: "比较" },
      { type: "file", name: "first.txt", path: "/workspace/attachments/first.txt" },
      { type: "text", value: "和" },
      { type: "file", name: "second.txt", path: "/workspace/attachments/second.txt" },
      { type: "text", value: "的差异" },
    ]),
    "比较 /workspace/attachments/first.txt 和 /workspace/attachments/second.txt 的差异",
  );
});

test("format preserves user whitespace and omits unresolved uploads", () => {
  assert.equal(
    formatComposerParts([
      { type: "text", value: "第一行\n" },
      { type: "file", name: "pending.md", path: null },
      { type: "file", name: "report.md", path: "/tmp/report.md" },
      { type: "text", value: "\n第二行\u200b" },
    ]),
    "第一行\n/tmp/report.md\n第二行",
  );
});

test("composer message keeps UI attachment metadata beside absolute-path content", () => {
  assert.deepEqual(
    formatComposerMessage([
      { type: "text", value: "检查" },
      { type: "file", name: "report final.md", path: "/tmp/report final.md" },
    ]),
    {
      content: "检查 /tmp/report final.md",
      attachments: [
        { name: "report final.md", absolute_path: "/tmp/report final.md" },
      ],
    },
  );
});

test("resource mentions expand to reference_text and keep resource metadata", () => {
  assert.deepEqual(
    formatComposerMessage([
      { type: "text", value: "用" },
      {
        type: "resource",
        name: "搜索",
        resource_type: "skill",
        resource_id: "skill-a",
        reference_text: "[skill:skill-a] 搜索",
      },
      { type: "text", value: "处理" },
    ]),
    {
      content: "用 [skill:skill-a] 搜索 处理",
      attachments: [
        {
          name: "搜索",
          resource_type: "skill",
          resource_id: "skill-a",
          reference_text: "[skill:skill-a] 搜索",
        },
      ],
    },
  );
});

test("mixed files and resources keep text order and do not copy resource into absolute_path", () => {
  const message = formatComposerMessage([
    { type: "file", name: "notes.md", path: "/tmp/notes.md" },
    { type: "text", value: "对照" },
    {
      type: "resource",
      name: "搜索",
      resource_type: "skill",
      resource_id: "skill-a",
      reference_text: "[skill:skill-a] 搜索",
    },
    { type: "text", value: "与" },
    {
      type: "resource",
      name: "搜索",
      resource_type: "skill",
      resource_id: "skill-b",
      reference_text: "[skill:skill-b] 搜索",
    },
  ]);
  assert.equal(
    message.content,
    "/tmp/notes.md 对照 [skill:skill-a] 搜索 与 [skill:skill-b] 搜索",
  );
  assert.deepEqual(message.attachments, [
    { name: "notes.md", absolute_path: "/tmp/notes.md" },
    {
      name: "搜索",
      resource_type: "skill",
      resource_id: "skill-a",
      reference_text: "[skill:skill-a] 搜索",
    },
    {
      name: "搜索",
      resource_type: "skill",
      resource_id: "skill-b",
      reference_text: "[skill:skill-b] 搜索",
    },
  ]);
  assert.equal(
    message.attachments.every((attachment) => !("absolute_path" in attachment && "resource_type" in attachment)),
    true,
  );
});

test("dropped file names support Unix and Windows paths", () => {
  assert.equal(getDroppedFileName("/Users/me/report.md"), "report.md");
  assert.equal(getDroppedFileName("C:\\Users\\me\\report.md"), "report.md");
});

test("composer expansion is offered only when collapsed content overflows the outer viewport", () => {
  assert.equal(shouldOfferComposerExpansion(128, 128), false);
  assert.equal(shouldOfferComposerExpansion(129, 128), false);
  assert.equal(shouldOfferComposerExpansion(130, 128), true);
  assert.equal(shouldOfferComposerExpansion(80, 128), false);
});
