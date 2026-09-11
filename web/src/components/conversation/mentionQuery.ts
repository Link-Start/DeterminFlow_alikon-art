import { isComposerToken, nodeElement, selectionRange } from "./composerEditorDom";

const EMAIL_PREFIX = /[A-Za-z0-9._]$/;

export interface MentionAnchorRect {
  top: number;
  bottom: number;
  left: number;
  right: number;
  height: number;
}

export interface MentionMatch {
  query: string;
  range: Range;
  startNode: Text;
  startOffset: number;
  anchor: MentionAnchorRect;
}

interface TextPiece {
  node: Text;
  from: number;
  to: number;
}

export function isValidMentionTrigger(text: string, atIndex: number): boolean {
  if (atIndex < 0 || atIndex >= text.length || text[atIndex] !== "@") return false;
  if (atIndex === 0) return true;
  const prev = text[atIndex - 1];
  if (prev === "\n" || prev === "\r") return true;
  return !EMAIL_PREFIX.test(prev);
}

export function findMentionQuery(textBeforeCaret: string): { atIndex: number; query: string } | null {
  const text = textBeforeCaret;
  const lastBreak = Math.max(text.lastIndexOf("\n"), text.lastIndexOf("\r"));
  for (let index = text.length - 1; index > lastBreak; index -= 1) {
    if (text[index] === "@" && isValidMentionTrigger(text, index)) {
      return { atIndex: index, query: text.slice(index + 1) };
    }
  }
  return null;
}

export function isSameMentionStart(
  left: { startNode: Text; startOffset: number } | null,
  right: { startNode: Text; startOffset: number } | null,
): boolean {
  return Boolean(
    left
    && right
    && left.startNode === right.startNode
    && left.startOffset === right.startOffset,
  );
}

function caretInsideToken(editor: HTMLElement, range: Range): boolean {
  const element = nodeElement(range.startContainer);
  const token = element?.closest<HTMLElement>("[data-file-token], [data-resource-token]");
  return Boolean(token && editor.contains(token));
}

function containingBlock(editor: HTMLElement, node: Node): HTMLElement {
  let current: Node | null = node;
  while (current && current !== editor) {
    if (
      current instanceof HTMLElement
      && (current.tagName === "DIV" || current.tagName === "P")
      && current.parentElement === editor
    ) {
      return current;
    }
    current = current.parentNode;
  }
  return editor;
}

function walkPrevious(editor: HTMLElement, scope: HTMLElement, node: Node): Node | null {
  if (node.previousSibling) return node.previousSibling;
  const parent = node.parentNode;
  if (!parent || parent === editor || parent === scope) return null;
  if (parent instanceof HTMLElement && (parent.tagName === "DIV" || parent.tagName === "P")) {
    return null;
  }
  return walkPrevious(editor, scope, parent);
}

function isLineBoundary(node: Node): boolean {
  if (isComposerToken(node)) return true;
  return node instanceof HTMLElement && (
    node.tagName === "BR" || node.tagName === "DIV" || node.tagName === "P"
  );
}

function trailingTextPieces(element: HTMLElement): TextPiece[] | null {
  const pieces: TextPiece[] = [];
  for (const child of Array.from(element.childNodes)) {
    if (isLineBoundary(child)) return null;
    if (child.nodeType === Node.TEXT_NODE) {
      const text = child as Text;
      if (text.data) pieces.push({ node: text, from: 0, to: text.data.length });
      continue;
    }
    if (child instanceof HTMLElement) {
      const nested = trailingTextPieces(child);
      if (!nested) return null;
      pieces.push(...nested);
    }
  }
  return pieces;
}

function caretTextContext(
  editor: HTMLElement,
  range: Range,
): { node: Text; offset: number } | null {
  if (range.startContainer.nodeType === Node.TEXT_NODE) {
    return { node: range.startContainer as Text, offset: range.startOffset };
  }
  const container = range.startContainer;
  const prev = container.childNodes[range.startOffset - 1] ?? null;
  if (prev?.nodeType === Node.TEXT_NODE) {
    const node = prev as Text;
    return { node, offset: node.data.length };
  }
  const next = container.childNodes[range.startOffset] ?? null;
  if (next?.nodeType === Node.TEXT_NODE) {
    return { node: next as Text, offset: 0 };
  }
  return null;
}

function collectLineTextPieces(editor: HTMLElement, range: Range): TextPiece[] {
  const caret = caretTextContext(editor, range);
  if (!caret) return [];
  const scope = containingBlock(editor, caret.node);
  const pieces: TextPiece[] = [{ node: caret.node, from: 0, to: caret.offset }];
  let sibling: Node | null = walkPrevious(editor, scope, caret.node);
  while (sibling) {
    if (isLineBoundary(sibling)) break;
    if (sibling.nodeType === Node.TEXT_NODE) {
      const node = sibling as Text;
      pieces.unshift({ node, from: 0, to: node.data.length });
      sibling = walkPrevious(editor, scope, sibling);
      continue;
    }
    if (sibling instanceof HTMLElement) {
      const nested = trailingTextPieces(sibling);
      if (!nested) break;
      pieces.unshift(...nested);
      sibling = walkPrevious(editor, scope, sibling);
      continue;
    }
    break;
  }
  return pieces.filter((piece) => piece.to > piece.from);
}

function firstClientRect(range: Range): MentionAnchorRect | null {
  const rects = range.getClientRects();
  const rect = rects.length > 0 ? rects[0] : range.getBoundingClientRect();
  if (!rect || (rect.width === 0 && rect.height === 0 && rect.top === 0 && rect.left === 0)) {
    return null;
  }
  return {
    top: rect.top,
    bottom: rect.bottom,
    left: rect.left,
    right: rect.right,
    height: rect.height,
  };
}

function fallbackAnchor(editor: HTMLElement, range: Range): MentionAnchorRect {
  return firstClientRect(range) ?? {
    top: editor.getBoundingClientRect().top,
    bottom: editor.getBoundingClientRect().bottom,
    left: editor.getBoundingClientRect().left + 8,
    right: editor.getBoundingClientRect().left + 8,
    height: 16,
  };
}

export function findMentionAtCaret(editor: HTMLElement): MentionMatch | null {
  const selection = window.getSelection();
  if (!selection?.anchorNode || !selection.focusNode
    || !editor.contains(selection.anchorNode) || !editor.contains(selection.focusNode)) return null;
  const caret = selectionRange(editor);
  if (!caret.collapsed || caretInsideToken(editor, caret)) return null;
  const pieces = collectLineTextPieces(editor, caret);
  const text = pieces.map((piece) => piece.node.data.slice(piece.from, piece.to)).join("");
  const found = findMentionQuery(text);
  if (!found) return null;

  let remaining = found.atIndex;
  for (const piece of pieces) {
    const length = piece.to - piece.from;
    if (remaining >= length) {
      remaining -= length;
      continue;
    }
    const startOffset = piece.from + remaining;
    const mentionRange = document.createRange();
    mentionRange.setStart(piece.node, startOffset);
    mentionRange.setEnd(caret.startContainer, caret.startOffset);
    const atRange = document.createRange();
    atRange.setStart(piece.node, startOffset);
    atRange.setEnd(piece.node, Math.min(piece.node.data.length, startOffset + 1));
    return {
      query: found.query,
      range: mentionRange,
      startNode: piece.node,
      startOffset,
      anchor: firstClientRect(atRange) ?? fallbackAnchor(editor, caret),
    };
  }
  return null;
}
