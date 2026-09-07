import assert from "node:assert/strict";
import test from "node:test";

import { readToolSchemaView, summarizeToolContract } from "./tool-schema-view";

function openaiTool(parameters: unknown, extra?: { name?: string; description?: string }) {
  return {
    name: extra?.name ?? "demo_tool",
    description: extra?.description ?? "工具说明",
    schema: {
      type: "function" as const,
      function: {
        name: extra?.name ?? "demo_tool",
        description: extra?.description ?? "工具说明",
        parameters,
      },
    },
  };
}

test("keeps the tool name and full description while translating parameters", () => {
  const view = readToolSchemaView(openaiTool({
    type: "object",
    properties: {
      path: { type: "string", description: "相对于 workspace 的路径" },
      offset: { type: "integer", description: "起始行号", default: 0 },
    },
    required: ["path"],
  }, { name: "read_file", description: "读取工作区内的文件内容，可指定行范围。" }));

  assert.equal(view.name, "read_file");
  assert.equal(view.description, "读取工作区内的文件内容，可指定行范围。");
  assert.equal(view.actions.length, 0);
  assert.equal(view.actionDescription, "");
  assert.equal(view.parameterCount, 2);
  assert.equal(view.requiredCount, 1);
  assert.deepEqual(view.fields.map((field) => field.name), ["path", "offset"]);
  assert.equal(view.fields[0].typeLabel, "string");
  assert.equal(view.fields[0].required, true);
  assert.equal(view.fields[0].description, "相对于 workspace 的路径");
  assert.equal(view.fields[1].required, false);
  assert.deepEqual(view.fields[1].constraints, ["默认 0"]);
  assert.equal(summarizeToolContract(view), "2 个参数");
});

test("extracts discrete action values without duplicating the action field", () => {
  const view = readToolSchemaView(openaiTool({
    type: "object",
    properties: {
      action: {
        type: "string",
        description: "要执行的操作",
        enum: ["create", "list", "remove"],
      },
      job_id: {
        anyOf: [{ type: "string" }, { type: "null" }],
        description: "任务 ID",
        default: null,
      },
    },
    required: ["action"],
  }));

  assert.deepEqual(view.actions.map((action) => action.value), ["create", "list", "remove"]);
  assert.equal(view.actionDescription, "要执行的操作");
  assert.equal(view.fields.some((field) => field.name === "action"), false);
  assert.equal(view.fields.length, 1);
  assert.equal(view.fields[0].name, "job_id");
  assert.equal(view.fields[0].typeLabel, "string | null");
  assert.equal(view.fields[0].required, false);
  assert.equal(summarizeToolContract(view), "3 个操作 · 1 个参数");
});

test("keeps a free-form action field among parameters", () => {
  const view = readToolSchemaView(openaiTool({
    type: "object",
    properties: {
      action: { type: "string", description: "操作类型: create / list" },
      name: { type: "string", description: "名称" },
    },
    required: ["action"],
  }));

  assert.equal(view.actions.length, 0);
  assert.deepEqual(view.fields.map((field) => field.name), ["action", "name"]);
  assert.equal(view.fields[0].required, true);
  assert.equal(view.fields[0].description, "操作类型: create / list");
});

test("uses oneOf const descriptions as action labels", () => {
  const view = readToolSchemaView(openaiTool({
    type: "object",
    properties: {
      action: {
        oneOf: [
          { const: "create", description: "创建资源" },
          { const: "list", description: "列出资源" },
        ],
      },
    },
    required: ["action"],
  }));

  assert.deepEqual(view.actions, [
    { value: "create", description: "创建资源" },
    { value: "list", description: "列出资源" },
  ]);
  assert.equal(view.fields.length, 0);
  assert.equal(summarizeToolContract(view), "2 个操作");
});

test("renders nested objects, arrays and additional properties", () => {
  const view = readToolSchemaView(openaiTool({
    type: "object",
    properties: {
      query: {
        type: "object",
        description: "查询条件",
        properties: {
          term: { type: "string", description: "关键词" },
          paging: {
            type: "object",
            properties: {
              limit: { type: "integer", minimum: 1, maximum: 100 },
            },
            required: ["limit"],
          },
        },
        required: ["term"],
      },
      tags: {
        type: "array",
        description: "标签",
        items: {
          type: "object",
          properties: {
            name: { type: "string" },
          },
          required: ["name"],
        },
        minItems: 1,
        uniqueItems: true,
      },
      extras: {
        type: "object",
        additionalProperties: { type: "string", description: "扩展值" },
      },
    },
    required: ["query"],
  }));

  const query = view.fields.find((field) => field.name === "query");
  const tags = view.fields.find((field) => field.name === "tags");
  const extras = view.fields.find((field) => field.name === "extras");
  assert.equal(query?.typeLabel, "object");
  assert.equal(query?.required, true);
  assert.deepEqual(query?.children.map((child) => child.name), ["term", "paging"]);
  assert.equal(query?.children[0].required, true);
  assert.equal(query?.children[1].children[0].name, "limit");
  assert.deepEqual(query?.children[1].children[0].constraints, ["≥ 1", "≤ 100"]);
  assert.equal(tags?.typeLabel, "array<object>");
  assert.equal(tags?.children[0].name, "元素");
  assert.equal(tags?.children[0].children[0].name, "name");
  assert.deepEqual(tags?.constraints, ["至少 1 项", "元素唯一"]);
  assert.equal(extras?.children[0].name, "*");
  assert.equal(extras?.children[0].typeLabel, "string");
});

test("resolves $ref, allOf and circular definitions", () => {
  const view = readToolSchemaView(openaiTool({
    type: "object",
    properties: {
      filter: { $ref: "#/$defs/Filter" },
      tree: { $ref: "#/$defs/Node" },
    },
    required: ["filter"],
    $defs: {
      Filter: {
        allOf: [
          { type: "object", properties: { field: { type: "string" } }, required: ["field"] },
          { properties: { op: { type: "string", enum: ["eq", "gt"] } }, required: ["op"] },
        ],
      },
      Node: {
        type: "object",
        properties: {
          name: { type: "string" },
          child: { $ref: "#/$defs/Node" },
        },
      },
    },
  }));

  const filter = view.fields[0];
  assert.equal(filter.required, true);
  assert.deepEqual(filter.children.map((child) => child.name), ["field", "op"]);
  assert.deepEqual(filter.children[1].allowedValues, ["eq", "gt"]);
  const tree = view.fields[1];
  assert.equal(tree.children[1].name, "child");
  assert.equal(tree.children[1].typeLabel, "Node");
  assert.equal(tree.children[1].children.length, 0);
});

test("surfaces allowed values and string constraints", () => {
  const view = readToolSchemaView(openaiTool({
    type: "object",
    properties: {
      kind: { type: "string", enum: ["file", "dir"] },
      slug: {
        type: "string",
        minLength: 2,
        maxLength: 32,
        pattern: "^[a-z0-9-]+$",
        format: "slug",
      },
    },
  }));

  assert.deepEqual(view.fields[0].allowedValues, ["file", "dir"]);
  assert.deepEqual(view.fields[1].constraints, [
    "长度 ≥ 2",
    "长度 ≤ 32",
    "匹配 ^[a-z0-9-]+$",
    "格式 slug",
  ]);
});

test("falls back to flattened parameters when the function schema is missing", () => {
  const view = readToolSchemaView({
    name: "legacy_tool",
    description: "兼容旧摘要",
    parameters: {
      title: { type: "string", description: "标题", required: true },
      count: { type: "integer", description: "数量", required: false },
    },
  });

  assert.equal(view.name, "legacy_tool");
  assert.deepEqual(view.fields.map((field) => [field.name, field.required, field.typeLabel]), [
    ["title", true, "string"],
    ["count", false, "integer"],
  ]);
});

test("presents root oneOf object variants as nested groups", () => {
  const view = readToolSchemaView(openaiTool({
    oneOf: [
      {
        type: "object",
        properties: {
          action: { const: "create" },
          title: { type: "string", description: "标题" },
        },
        required: ["action", "title"],
      },
      {
        type: "object",
        properties: {
          action: { const: "list" },
          limit: { type: "integer", default: 20 },
        },
        required: ["action"],
      },
    ],
  }));

  assert.deepEqual(view.fields.map((field) => field.name), ["create", "list"]);
  assert.equal(view.fields[0].children.find((child) => child.name === "title")?.required, true);
  assert.equal(view.fields[1].children.find((child) => child.name === "limit")?.constraints[0], "默认 20");
});

test("does not invent product-specific fields and reports empty contracts", () => {
  const view = readToolSchemaView(openaiTool({ type: "object" }, {
    name: "noop",
    description: "没有参数的工具",
  }));

  assert.equal(view.name, "noop");
  assert.equal(view.description, "没有参数的工具");
  assert.equal(view.actions.length, 0);
  assert.equal(view.fields.length, 0);
  assert.equal(summarizeToolContract(view), "无参数");
  assert.equal(view.rawParameters && typeof view.rawParameters === "object", true);
});
