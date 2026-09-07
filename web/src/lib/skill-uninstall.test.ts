import assert from "node:assert/strict";
import test from "node:test";

import { uninstallLocalSkill } from "./skill-uninstall";

test("uninstall uses the existing local Skill API and requires a confirmed success", async () => {
  const original = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  try {
    globalThis.fetch = async (input, init) => {
      requests.push({ url: String(input), init });
      return Response.json({ success: true, message: "Skill writing-helper 已删除" });
    };
    await uninstallLocalSkill("writing-helper");
    assert.equal(requests[0]?.url, "/api/skills/writing-helper");
    assert.equal(requests[0]?.init?.method, "DELETE");
  } finally {
    globalThis.fetch = original;
  }
});

test("uninstall keeps a recoverable error when the write is not confirmed", async () => {
  const original = globalThis.fetch;
  try {
    for (const response of [
      new Response("failure", { status: 500 }),
      Response.json({ detail: "没有权限卸载该 Skill。" }, { status: 403 }),
      Response.json({ success: false }),
      Response.json({}),
    ]) {
      globalThis.fetch = async () => response;
      await assert.rejects(uninstallLocalSkill("writing-helper"));
    }
    globalThis.fetch = async () => {
      throw new Error("offline");
    };
    await assert.rejects(uninstallLocalSkill("writing-helper"));
  } finally {
    globalThis.fetch = original;
  }
});

test("uninstall encodes the local skill id and surfaces a missing resource", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (input) => {
      assert.equal(String(input), "/api/skills/writing%2Fhelper");
      return Response.json({ detail: "未找到 skill: writing/helper" }, { status: 404 });
    };
    await assert.rejects(
      uninstallLocalSkill("writing/helper"),
      /未找到 skill: writing\/helper/,
    );
  } finally {
    globalThis.fetch = original;
  }
});
