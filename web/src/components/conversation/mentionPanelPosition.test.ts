import assert from "node:assert/strict";
import test from "node:test";
import { layoutMentionPanel } from "./mentionPanelPosition";

test("both panes stay above the composer at narrow widths and short heights", () => {
  for (const width of [320, 390, 1280]) {
    for (const top of [60, 150, 650]) {
      const viewport = { width, height: 800 };
      const layout = layoutMentionPanel({ top, bottom: top + 100, left: width - 40, right: width - 20, height: 20 }, viewport, true);
      const paneBottom = viewport.height - layout.bottom;
      assert.ok(paneBottom < top);
      assert.ok(paneBottom - layout.maxHeight >= 8);
      assert.ok(layout.left >= 8);
      assert.ok(layout.left + layout.typeWidth + 4 + layout.resourceWidth <= width - 8);
      assert.ok(layout.typeWidth < layout.resourceWidth);
    }
  }
});

test("the bottom anchor is stable as content height and submenu visibility change", () => {
  const anchor = { top: 400, bottom: 500, left: 30, right: 44, height: 20 };
  const closed = layoutMentionPanel(anchor, { width: 1000, height: 800 });
  const opened = layoutMentionPanel(anchor, { width: 1000, height: 800 }, true);
  assert.equal(closed.bottom, opened.bottom);
  assert.equal(closed.typeWidth, 176);
  for (const height of [32, 64, 240]) {
    const bottom = 800 - opened.bottom;
    assert.equal(bottom, 392);
    assert.ok(bottom - height >= 8);
  }
});
