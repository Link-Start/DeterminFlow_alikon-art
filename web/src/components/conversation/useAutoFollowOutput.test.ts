import assert from "node:assert/strict";
import test from "node:test";

import {
  applyFollowOutputScroll,
  distanceFromBottom,
  followStateAfterScroll,
  isNearBottom,
  maxScrollTop,
} from "./useAutoFollowOutput.ts";

test("auto-follow stays enabled only when the viewport is near the bottom", () => {
  assert.equal(distanceFromBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 200 }), 100);
  assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 200 }, 120), true);
  assert.equal(isNearBottom({ scrollHeight: 1000, scrollTop: 500, clientHeight: 200 }, 120), false);
});

test("distance clamps negative layout values to zero", () => {
  assert.equal(distanceFromBottom({ scrollHeight: 100, scrollTop: 20, clientHeight: 120 }), 0);
});

test("follow output stops at the last visible pixel instead of scrollHeight", () => {
  assert.equal(maxScrollTop({ scrollHeight: 1000, clientHeight: 200 }), 800);
  assert.equal(maxScrollTop({ scrollHeight: 100, clientHeight: 120 }), 0);

  const viewport = { scrollHeight: 1000, scrollTop: 12, clientHeight: 200 };
  assert.equal(applyFollowOutputScroll(viewport), 800);
  assert.equal(viewport.scrollTop, 800);
});

test("programmatic follow scrolls do not disable auto-follow", () => {
  const awayFromBottom = { scrollHeight: 1000, scrollTop: 100, clientHeight: 200 };
  assert.equal(
    followStateAfterScroll({
      wasFollowing: true,
      programmatic: true,
      metrics: awayFromBottom,
      threshold: 120,
    }),
    true,
  );
  assert.equal(
    followStateAfterScroll({
      wasFollowing: true,
      programmatic: false,
      metrics: awayFromBottom,
      threshold: 120,
    }),
    false,
  );
});
