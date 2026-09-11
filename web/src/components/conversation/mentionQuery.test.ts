import assert from "node:assert/strict";
import test from "node:test";

import { findMentionQuery, isSameMentionStart, isValidMentionTrigger } from "./mentionQuery";

test("emails and attached identifiers do not start a mention", () => {
  assert.equal(isValidMentionTrigger("user@example.com", 4), false);
  assert.equal(findMentionQuery("user@example.com"), null);
  assert.equal(findMentionQuery("report.v1@draft"), null);
});

test("whitespace, line start, CJK, and punctuation can start a mention", () => {
  assert.deepEqual(findMentionQuery("@skill"), { atIndex: 0, query: "skill" });
  assert.deepEqual(findMentionQuery("看 @搜索"), { atIndex: 2, query: "搜索" });
  assert.deepEqual(findMentionQuery("你好@规则"), { atIndex: 2, query: "规则" });
  assert.deepEqual(findMentionQuery("(@agent"), { atIndex: 1, query: "agent" });
});

test("caret in the middle of a line uses the current @query and ignores earlier lines", () => {
  assert.deepEqual(findMentionQuery("first line\n@foo"), { atIndex: 11, query: "foo" });
  assert.deepEqual(findMentionQuery("see @one @two"), { atIndex: 9, query: "two" });
});

test("dismissed mention identity stays bound to the same @ start", () => {
  const node = { data: "@foo" } as unknown as Text;
  const other = { data: "@foo" } as unknown as Text;
  assert.equal(
    isSameMentionStart({ startNode: node, startOffset: 0 }, { startNode: node, startOffset: 0 }),
    true,
  );
  assert.equal(
    isSameMentionStart({ startNode: node, startOffset: 0 }, { startNode: node, startOffset: 1 }),
    false,
  );
  assert.equal(
    isSameMentionStart({ startNode: node, startOffset: 0 }, { startNode: other, startOffset: 0 }),
    false,
  );
});
