import assert from "node:assert/strict";
import test from "node:test";

import type { Session } from "../types";
import { partitionSessions, sessionCategory } from "./session-catalog";

function session(overrides: Partial<Session>): Session {
  return {
    session_id: "session",
    type: "main",
    parent_id: null,
    status: "completed",
    task: "",
    message_count: 0,
    created_at: "2026-08-29T00:00:00Z",
    updated_at: "2026-08-29T00:00:00Z",
    last_message: "",
    ...overrides,
  };
}

test("session categories use persisted lifecycle metadata", () => {
  assert.equal(sessionCategory(session({ runtime_scope: "interactive" })), "main");
  assert.equal(sessionCategory(session({ runtime_scope: "workflow" })), "workflow");
  assert.equal(
    sessionCategory(session({
      type: "sub",
      lifecycle_profile: "detached_conversation",
      resource_owner: "example-assistant",
    })),
    "assistant",
  );
});

test("detached assistant sessions stay outside Main and Workflow trees", () => {
  const catalog = partitionSessions([
    session({ session_id: "main" }),
    session({ session_id: "workflow", runtime_scope: "workflow" }),
    session({ session_id: "child", type: "sub", parent_id: "main" }),
    session({
      session_id: "assistant",
      type: "sub",
      lifecycle_profile: "detached_conversation",
      resource_owner: "example-assistant",
    }),
  ]);

  assert.deepEqual(catalog.groups.map((group) => group.category), ["main", "workflow"]);
  assert.deepEqual(catalog.groups[0].subs.map((item) => item.session_id), ["child"]);
  assert.deepEqual(catalog.assistants.map((item) => item.session_id), ["assistant"]);
});
