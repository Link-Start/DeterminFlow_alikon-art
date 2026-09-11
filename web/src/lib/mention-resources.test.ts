import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchMentionResources,
  mentionResourcesPath,
  parseMentionResourcePage,
} from "./mention-resources";

test("mention resource requests use the frozen session catalog contract", () => {
  assert.equal(
    mentionResourcesPath("session 1", {
      resourceType: "skill",
      q: "search",
      offset: 0,
      limit: 50,
    }),
    "/sessions/session%201/mention-resources?resource_type=skill&q=search&offset=0&limit=50",
  );
});

test("catalog parsing keeps available items and drops invalid rows", () => {
  const page = parseMentionResourcePage({
    items: [
      {
        resource_type: "skill",
        resource_id: "skill-a",
        name: "搜索",
        description: "查找",
        source: "core",
        reference_text: "[skill:skill-a] 搜索",
        available: true,
      },
      {
        resource_type: "agent",
        resource_id: "wrong-type",
        name: "错类型",
        reference_text: "no",
        available: true,
      },
      {
        resource_type: "skill",
        resource_id: "skill-b",
        name: "离线",
        description: "",
        source: "",
        reference_text: "[skill:skill-b] 离线",
        available: false,
        unavailable_reason: "未启用",
      },
    ],
    total: 3,
    has_more: true,
  }, "skill");

  assert.equal(page.items.length, 2);
  assert.equal(page.items[1].available, false);
  assert.equal(page.items[1].unavailable_reason, "未启用");
  assert.equal(page.has_more, true);
});

test("fetchMentionResources sends query params and ignores stale extra fields", async (context) => {
  const requests: string[] = [];
  context.mock.method(globalThis, "fetch", async (input: RequestInfo | URL) => {
    requests.push(String(input));
    return new Response(JSON.stringify({
      items: [{
        resource_type: "prompt",
        resource_id: "p1",
        name: "写作",
        description: "desc",
        source: "user",
        reference_text: "[prompt:p1] 写作",
        available: true,
        extra: "ignore",
      }],
      total: 1,
      has_more: false,
    }), { status: 200, headers: { "content-type": "application/json" } });
  });

  const page = await fetchMentionResources("s1", { resourceType: "prompt", q: "写" });
  assert.equal(requests[0], "/api/sessions/s1/mention-resources?resource_type=prompt&q=%E5%86%99&offset=0&limit=50");
  assert.deepEqual(page.items[0], {
    resource_type: "prompt",
    resource_id: "p1",
    name: "写作",
    description: "desc",
    source: "user",
    reference_text: "[prompt:p1] 写作",
    available: true,
  });
});
