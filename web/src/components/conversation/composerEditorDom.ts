import { isMentionResourceType } from "../../types";
import {
  formatComposerMessage,
  type ComposerPart,
} from "./conversationComposerModel";

type CaretDocument = Document & {
  caretRangeFromPoint?: (x: number, y: number) => Range | null;
  caretPositionFromPoint?: (x: number, y: number) => {
    offsetNode: Node;
    offset: number;
  } | null;
};

const TOKEN_SELECTOR = "[data-file-token], [data-resource-token]";

export function nodeElement(node: Node): Element | null {
  return node.nodeType === Node.ELEMENT_NODE
    ? node as Element
    : node.parentElement;
}

export function isComposerToken(node: Node | null): node is HTMLElement {
  return node instanceof HTMLElement && Boolean(
    node.dataset.fileToken || node.dataset.resourceToken,
  );
}

function meaningfulText(value: string): string {
  return value.replace(/\u200b/g, "");
}

export function rangeAtPoint(editor: HTMLElement, x: number, y: number): Range | null {
  const pointElement = document.elementFromPoint(x, y);
  const token = pointElement?.closest<HTMLElement>(TOKEN_SELECTOR);
  if (token && editor.contains(token)) {
    const range = document.createRange();
    const bounds = token.getBoundingClientRect();
    if (x < bounds.left + bounds.width / 2) range.setStartBefore(token);
    else range.setStartAfter(token);
    range.collapse(true);
    return range;
  }

  const caretDocument = document as CaretDocument;
  let range = caretDocument.caretRangeFromPoint?.(x, y) ?? null;
  if (!range) {
    const position = caretDocument.caretPositionFromPoint?.(x, y);
    if (position) {
      range = document.createRange();
      range.setStart(position.offsetNode, position.offset);
      range.collapse(true);
    }
  }
  if (range && editor.contains(nodeElement(range.startContainer))) return range;

  range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  return range;
}

export function selectionRange(editor: HTMLElement): Range {
  const selection = window.getSelection();
  const current = selection?.rangeCount ? selection.getRangeAt(0) : null;
  if (current && editor.contains(nodeElement(current.startContainer))) {
    return current.cloneRange();
  }
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  return range;
}

export function placeCaretAfter(node: Node) {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.setStartAfter(node);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

export function insertText(editor: HTMLElement, text: string) {
  const range = selectionRange(editor);
  range.deleteContents();
  const node = document.createTextNode(text);
  range.insertNode(node);
  placeCaretAfter(node);
}

function hasVisibleContentAfter(node: Node): boolean {
  for (let current = node.nextSibling; current; current = current.nextSibling) {
    if (current.nodeType === Node.TEXT_NODE) {
      if (meaningfulText(current.textContent ?? "")) return true;
      continue;
    }
    if (!(current instanceof HTMLElement)) continue;
    if (current.tagName === "BR") return true;
    if (current.dataset.fileToken || current.dataset.resourceToken) return true;
    if (meaningfulText(current.textContent ?? "") || current.querySelector(TOKEN_SELECTOR)) {
      return true;
    }
  }
  return false;
}

export function insertNewline(editor: HTMLElement) {
  const range = selectionRange(editor);
  range.deleteContents();
  const newline = document.createTextNode("\n");
  range.insertNode(newline);
  // A trailing newline in contenteditable + pre-wrap does not create a visible
  // empty line unless something follows it. Zero-width space is stripped on send.
  if (!hasVisibleContentAfter(newline)) {
    newline.after(document.createTextNode("\u200b"));
  }
  placeCaretAfter(newline);
}

export function collectComposerParts(node: Node, parts: ComposerPart[]) {
  if (node.nodeType === Node.TEXT_NODE) {
    parts.push({ type: "text", value: node.textContent ?? "" });
    return;
  }
  if (!(node instanceof HTMLElement)) return;

  if (node.dataset.fileToken) {
    const name = node.querySelector<HTMLElement>("[data-file-name]")?.textContent ?? "文件";
    parts.push({
      type: "file",
      name,
      path: node.dataset.attachmentStatus === "ready"
        ? node.dataset.absolutePath ?? null
        : null,
    });
    return;
  }
  if (node.dataset.resourceToken) {
    const resourceType = node.dataset.resourceType ?? "";
    if (!isMentionResourceType(resourceType)) return;
    const name = node.querySelector<HTMLElement>("[data-resource-name]")?.textContent
      ?? node.dataset.resourceName
      ?? "资源";
    parts.push({
      type: "resource",
      name: name.replace(/^@/, ""),
      resource_type: resourceType,
      resource_id: node.dataset.resourceId ?? "",
      reference_text: node.dataset.referenceText ?? "",
    });
    return;
  }
  if (node.tagName === "BR") {
    parts.push({ type: "text", value: "\n" });
    return;
  }

  Array.from(node.childNodes).forEach((child) => collectComposerParts(child, parts));
  if ((node.tagName === "DIV" || node.tagName === "P") && node.nextSibling) {
    parts.push({ type: "text", value: "\n" });
  }
}

export function readComposerMessage(editor: HTMLElement) {
  const parts: ComposerPart[] = [];
  Array.from(editor.childNodes).forEach((node) => collectComposerParts(node, parts));
  return formatComposerMessage(parts);
}

export function hasEditorContent(editor: HTMLElement): boolean {
  return Boolean(
    editor.querySelector(TOKEN_SELECTOR)
    || editor.textContent?.replace(/\u200b/g, "").trim(),
  );
}

export function pointInside(element: HTMLElement, x: number, y: number): boolean {
  const bounds = element.getBoundingClientRect();
  return x >= bounds.left && x <= bounds.right && y >= bounds.top && y <= bounds.bottom;
}

export function insertTokenAtRange(range: Range, token: HTMLElement): Range {
  range.insertNode(token);
  range.setStartAfter(token);
  range.collapse(true);
  return range;
}

export function replaceRangeWithToken(range: Range, token: HTMLElement) {
  range.deleteContents();
  range.insertNode(token);
  placeCaretAfter(token);
}

export function moveTokenByKeyboard(token: HTMLElement, direction: "left" | "right") {
  const sibling = direction === "left" ? token.previousSibling : token.nextSibling;
  if (!sibling) return;
  if (direction === "left") sibling.before(token);
  else sibling.after(token);
  token.focus();
}

function skipEmptyText(node: Node | null, direction: "backward" | "forward"): Node | null {
  let current = node;
  while (
    current
    && current.nodeType === Node.TEXT_NODE
    && !meaningfulText(current.textContent ?? "")
  ) {
    current = direction === "backward" ? current.previousSibling : current.nextSibling;
  }
  return current;
}

export function findAdjacentToken(
  editor: HTMLElement,
  direction: "backward" | "forward",
): HTMLElement | null {
  const range = selectionRange(editor);
  if (!range.collapsed) return null;

  const container = range.startContainer;
  const offset = range.startOffset;
  let candidate: Node | null = null;

  if (container.nodeType === Node.TEXT_NODE) {
    const text = container.textContent ?? "";
    const side = direction === "backward" ? text.slice(0, offset) : text.slice(offset);
    if (meaningfulText(side)) return null;
    candidate = direction === "backward" ? container.previousSibling : container.nextSibling;
    if (!candidate && container.parentNode && container.parentNode !== editor) {
      candidate = direction === "backward"
        ? container.parentNode.previousSibling
        : container.parentNode.nextSibling;
    }
  } else {
    const index = direction === "backward" ? offset - 1 : offset;
    candidate = container.childNodes[index] ?? null;
  }

  candidate = skipEmptyText(candidate, direction);
  return isComposerToken(candidate) ? candidate : null;
}
