import type { MentionResourceType, MessageAttachment } from "../../types";

export type ComposerPart =
  | { type: "text"; value: string }
  | { type: "file"; name: string; path: string | null }
  | {
      type: "resource";
      name: string;
      resource_type: MentionResourceType;
      resource_id: string;
      reference_text: string;
    };

export interface ComposerMessage {
  content: string;
  attachments: MessageAttachment[];
}

export function shouldOfferComposerExpansion(
  scrollHeight: number,
  clientHeight: number,
): boolean {
  return scrollHeight > clientHeight + 1;
}

const ZERO_WIDTH_SPACE = /\u200b/g;

export function getDroppedFileName(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  return normalized.slice(normalized.lastIndexOf("/") + 1) || path;
}

function nextVisibleText(parts: ComposerPart[], index: number): string {
  const nextText = parts.slice(index + 1).find(
    (candidate): candidate is Extract<ComposerPart, { type: "text" }> =>
      candidate.type === "text" && candidate.value.replace(ZERO_WIDTH_SPACE, "").length > 0,
  );
  return nextText ? nextText.value.replace(ZERO_WIDTH_SPACE, "") : "";
}

function appendInlineToken(content: string, tokenText: string, followingText: string): string {
  let next = content;
  if (next && !/\s$/.test(next)) next += " ";
  next += tokenText;
  if (followingText && !/^\s/.test(followingText)) next += " ";
  return next;
}

export function formatComposerParts(parts: ComposerPart[]): string {
  let content = "";

  for (let index = 0; index < parts.length; index += 1) {
    const part = parts[index];
    if (part.type === "text") {
      content += part.value.replace(ZERO_WIDTH_SPACE, "");
      continue;
    }
    const tokenText = part.type === "file" ? part.path : part.reference_text;
    if (!tokenText) continue;
    content = appendInlineToken(content, tokenText, nextVisibleText(parts, index));
  }

  return content;
}

export function formatComposerMessage(parts: ComposerPart[]): ComposerMessage {
  return {
    content: formatComposerParts(parts),
    attachments: parts.flatMap((part): MessageAttachment[] => {
      if (part.type === "file" && part.path) {
        return [{ name: part.name, absolute_path: part.path }];
      }
      if (part.type === "resource" && part.reference_text) {
        return [{
          name: part.name,
          resource_type: part.resource_type,
          resource_id: part.resource_id,
          reference_text: part.reference_text,
        }];
      }
      return [];
    }),
  };
}
