import assert from "node:assert/strict";
import test from "node:test";

import {
  attachmentsRemainingInContent,
  normalizeMessageAttachment,
  splitUserMessageAttachments,
} from "./messageAttachmentModel";

test("edited reference order and repeated references do not depend on metadata order", () => {
  const skill = { name: "审查", resource_type: "skill" as const,
    resource_id: "review", reference_text: "Skill「审查」（get_skills(skill_id=\"review\")）" };
  const parts = splitUserMessageAttachments(
    `${skill.reference_text} /tmp/a.txt ${skill.reference_text}`,
    [{ name: "a.txt", absolute_path: "/tmp/a.txt" }, skill, skill],
  );
  assert.deepEqual(parts.filter((part) => part.type !== "text").map((part) => part.type),
    ["resource", "file", "resource"]);
});

test("history restores resource chips from reference_text without using absolute_path", () => {
  const parts = splitUserMessageAttachments(
    "用 [skill:skill-a] 搜索 处理",
    [{
      name: "搜索",
      resource_type: "skill",
      resource_id: "skill-a",
      reference_text: "[skill:skill-a] 搜索",
    }],
  );
  assert.deepEqual(parts, [
    { type: "text", value: "用 " },
    {
      type: "resource",
      name: "搜索",
      resourceType: "skill",
      resourceId: "skill-a",
      referenceText: "[skill:skill-a] 搜索",
    },
    { type: "text", value: " 处理" },
  ]);
});

test("same display names with different ids stay distinct in mixed file history", () => {
  const parts = splitUserMessageAttachments(
    "/tmp/notes.md 对照 [skill:skill-a] 搜索 与 [skill:skill-b] 搜索",
    [
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
    ],
  );
  assert.deepEqual(
    parts.filter((part) => part.type !== "text"),
    [
      { type: "file", name: "notes.md", absolutePath: "/tmp/notes.md" },
      {
        type: "resource",
        name: "搜索",
        resourceType: "skill",
        resourceId: "skill-a",
        referenceText: "[skill:skill-a] 搜索",
      },
      {
        type: "resource",
        name: "搜索",
        resourceType: "skill",
        resourceId: "skill-b",
        referenceText: "[skill:skill-b] 搜索",
      },
    ],
  );
});

test("normalizeMessageAttachment prefers resource fields over a forged absolute_path", () => {
  assert.deepEqual(
    normalizeMessageAttachment({
      name: "搜索",
      resource_type: "skill",
      resource_id: "skill-a",
      reference_text: "[skill:skill-a] 搜索",
      absolute_path: "/tmp/should-not-use",
    }),
    {
      name: "搜索",
      resource_type: "skill",
      resource_id: "skill-a",
      reference_text: "[skill:skill-a] 搜索",
    },
  );
});

test("edit filtering keeps resources whose reference_text remains in content", () => {
  const remaining = attachmentsRemainingInContent(
    [
      { name: "notes.md", absolute_path: "/tmp/notes.md" },
      {
        name: "搜索",
        resource_type: "skill",
        resource_id: "skill-a",
        reference_text: "[skill:skill-a] 搜索",
      },
    ],
    "只保留 [skill:skill-a] 搜索",
  );
  assert.deepEqual(remaining, [{
    name: "搜索",
    resource_type: "skill",
    resource_id: "skill-a",
    reference_text: "[skill:skill-a] 搜索",
  }]);
});
