import assert from "node:assert/strict";
import { after, test } from "node:test";
import { Window } from "happy-dom";

const dom = new Window({ url: "http://localhost/" });
for (const name of ["window", "document", "Node", "HTMLElement", "Element", "Range"]) {
  Object.defineProperty(globalThis, name, {
    configurable: true,
    value: name === "window" ? dom : dom[name as keyof Window],
  });
}

const { insertNewline, readComposerMessage } = await import("./composerEditorDom");

after(async () => dom.happyDOM.abort());

function editorWith(text: string, offset = text.length) {
  const editor = document.createElement("div");
  editor.contentEditable = "true";
  editor.textContent = text;
  document.body.append(editor);
  const node = editor.firstChild ?? editor;
  const range = document.createRange();
  range.setStart(node, Math.min(offset, node.nodeType === Node.TEXT_NODE ? (node.textContent ?? "").length : 0));
  range.collapse(true);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  return editor;
}

test("Shift+Enter after text creates a visible empty line in one press", () => {
  const editor = editorWith("123");
  insertNewline(editor);
  assert.equal(readComposerMessage(editor).content, "123\n");
  assert.match(editor.textContent ?? "", /\n\u200b$/);
});

test("Shift+Enter in the middle of text does not add a spacer", () => {
  const editor = editorWith("hello", 3);
  insertNewline(editor);
  assert.equal(readComposerMessage(editor).content, "hel\nlo");
  assert.equal(editor.textContent?.includes("\u200b"), false);
});

test("Shift+Enter on an empty line still adds one newline", () => {
  const editor = editorWith("123\n");
  insertNewline(editor);
  assert.equal(readComposerMessage(editor).content, "123\n\n");
});
