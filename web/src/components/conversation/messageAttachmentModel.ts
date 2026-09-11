import {
  isFileMessageAttachment,
  isMentionResourceType,
  isResourceMessageAttachment,
  type MentionResourceType,
  type MessageAttachment,
} from "../../types";

export type UserMessageContentPart =
  | { type: "text"; value: string }
  | { type: "file"; name: string; absolutePath: string }
  | {
      type: "resource";
      name: string;
      resourceType: MentionResourceType;
      resourceId: string;
      referenceText: string;
    };

export function normalizeMessageAttachment(value: unknown): MessageAttachment | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const name = typeof record.name === "string" ? record.name.trim() : "";
  if (!name) return null;
  const resourceType = typeof record.resource_type === "string" ? record.resource_type : "";
  const resourceId = typeof record.resource_id === "string" ? record.resource_id.trim() : "";
  const referenceText = typeof record.reference_text === "string" ? record.reference_text : "";
  if (isMentionResourceType(resourceType) && resourceId && referenceText) {
    return {
      name,
      resource_type: resourceType,
      resource_id: resourceId,
      reference_text: referenceText,
    };
  }
  const absolutePath = typeof record.absolute_path === "string" ? record.absolute_path : "";
  if (absolutePath) {
    return { name, absolute_path: absolutePath };
  }
  return null;
}

export function attachmentContentNeedle(attachment: MessageAttachment): string | null {
  if (isResourceMessageAttachment(attachment)) {
    return attachment.reference_text || null;
  }
  if (isFileMessageAttachment(attachment)) {
    return attachment.absolute_path || null;
  }
  return null;
}

export function attachmentsRemainingInContent(
  attachments: MessageAttachment[] | undefined,
  content: string,
): MessageAttachment[] | undefined {
  if (!attachments?.length) return undefined;
  const next = attachments.filter((attachment) => {
    const needle = attachmentContentNeedle(attachment);
    return Boolean(needle) && content.includes(needle as string);
  });
  return next.length > 0 ? next : undefined;
}

function fileNameFromPath(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  return normalized.slice(normalized.lastIndexOf("/") + 1) || path;
}

function splitStructuredAttachments(
  content: string,
  attachments: MessageAttachment[],
): UserMessageContentPart[] | null {
  const parts: UserMessageContentPart[] = [];
  let cursor = 0;
  let matched = false;

  const remaining = [...attachments];
  while (remaining.length > 0) {
    // Editing can reorder references without reordering their stored metadata.
    const next = remaining.map((attachment, attachmentIndex) => {
      const needle = attachmentContentNeedle(attachment);
      return { attachment, attachmentIndex, needle, index: needle ? content.indexOf(needle, cursor) : -1 };
    }).filter((match) => match.index >= 0).sort((a, b) => a.index - b.index)[0];
    if (!next?.needle) break;
    const { attachment, needle, index } = next;
    remaining.splice(next.attachmentIndex, 1);
    if (index > cursor) {
      parts.push({ type: "text", value: content.slice(cursor, index) });
    }
    if (isResourceMessageAttachment(attachment)) {
      parts.push({
        type: "resource",
        name: attachment.name,
        resourceType: attachment.resource_type,
        resourceId: attachment.resource_id,
        referenceText: attachment.reference_text,
      });
    } else {
      parts.push({
        type: "file",
        name: attachment.name || fileNameFromPath(needle),
        absolutePath: needle,
      });
    }
    cursor = index + needle.length;
    matched = true;
  }

  if (!matched) return null;
  if (cursor < content.length) {
    parts.push({ type: "text", value: content.slice(cursor) });
  }
  return parts;
}

function legacyWorkspaceAttachment(line: string): UserMessageContentPart | null {
  const path = line.trim();
  const normalized = path.replace(/\\/g, "/");
  const absolute = normalized.startsWith("/") || /^[A-Za-z]:\//.test(normalized);
  const hasFileExtension = /\.[^./\s]+$/.test(normalized);
  if (!absolute || !normalized.includes("/attachments/") || !hasFileExtension) {
    return null;
  }
  return {
    type: "file",
    name: fileNameFromPath(path),
    absolutePath: path,
  };
}

function splitLegacyInlineAttachments(line: string): UserMessageContentPart[] {
  const pathPattern = /(?:[A-Za-z]:[\\/]|\/)[^\s\r\n]*[\\/]attachments[\\/][^\s\r\n]+/g;
  const parts: UserMessageContentPart[] = [];
  let cursor = 0;

  for (const match of line.matchAll(pathPattern)) {
    const path = match[0];
    const index = match.index;
    if (index > cursor) {
      parts.push({ type: "text", value: line.slice(cursor, index) });
    }
    parts.push({
      type: "file",
      name: fileNameFromPath(path),
      absolutePath: path,
    });
    cursor = index + path.length;
  }

  if (parts.length === 0) return [{ type: "text", value: line }];
  if (cursor < line.length) {
    parts.push({ type: "text", value: line.slice(cursor) });
  }
  return parts;
}

function splitLegacyWorkspaceAttachments(content: string): UserMessageContentPart[] {
  const parts = content.split(/(\r?\n)/).flatMap((segment) => {
    if (/^\r?\n$/.test(segment)) {
      return [{ type: "text", value: segment } as const];
    }
    const wholeLineAttachment = legacyWorkspaceAttachment(segment);
    return wholeLineAttachment
      ? [wholeLineAttachment]
      : splitLegacyInlineAttachments(segment);
  });
  return parts.some((part) => part.type === "file")
    ? parts
    : [{ type: "text", value: content }];
}

export function splitUserMessageAttachments(
  content: string,
  attachments: MessageAttachment[] | undefined,
): UserMessageContentPart[] {
  if (attachments?.length) {
    const structured = splitStructuredAttachments(content, attachments);
    if (structured) return structured;
  }
  return splitLegacyWorkspaceAttachments(content);
}
