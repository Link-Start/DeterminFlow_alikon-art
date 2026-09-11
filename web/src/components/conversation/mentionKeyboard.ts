export function isComposingKeyEvent(event: {
  isComposing: boolean;
  keyCode: number;
  key: string;
}): boolean {
  return event.isComposing || event.keyCode === 229 || event.key === "Process";
}

export type ComposerKeyAction =
  | { type: "pass" }
  | { type: "send" }
  | { type: "newline" }
  | { type: "mention-move"; delta: number }
  | { type: "mention-confirm" }
  | { type: "mention-back" }
  | { type: "mention-close" }
  | { type: "mention-tab" }
  | { type: "delete-adjacent"; direction: "backward" | "forward" };

export function resolveComposerKey(input: {
  key: string;
  shiftKey: boolean;
  altKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  isComposing: boolean;
  keyCode: number;
  mentionOpen: boolean;
  mentionLayer: "types" | "resources" | null;
}): ComposerKeyAction {
  if (isComposingKeyEvent(input)) return { type: "pass" };
  if (input.metaKey || input.ctrlKey || input.altKey) return { type: "pass" };

  if (input.mentionOpen) {
    if (input.key === "ArrowDown") return { type: "mention-move", delta: 1 };
    if (input.key === "ArrowUp") return { type: "mention-move", delta: -1 };
    if (input.key === "Enter" && !input.shiftKey) return { type: "mention-confirm" };
    if (input.key === "ArrowRight" && input.mentionLayer === "types") return { type: "mention-confirm" };
    if (input.key === "ArrowLeft" && input.mentionLayer === "resources") return { type: "mention-back" };
    if (input.key === "Escape") {
      return input.mentionLayer === "resources"
        ? { type: "mention-back" }
        : { type: "mention-close" };
    }
    if (input.key === "Tab") return { type: "mention-tab" };
  }

  if (input.key === "Enter" && !input.shiftKey) return { type: "send" };
  if (input.key === "Enter" && input.shiftKey) return { type: "newline" };
  if (input.key === "Backspace") return { type: "delete-adjacent", direction: "backward" };
  if (input.key === "Delete") return { type: "delete-adjacent", direction: "forward" };
  return { type: "pass" };
}
