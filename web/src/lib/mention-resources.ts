import { request } from "./http-client";
import {
  isMentionResourceType,
  type MentionResourceType,
} from "../types";

export const MENTION_PAGE_SIZE = 50;

export interface MentionResource {
  resource_type: MentionResourceType;
  resource_id: string;
  name: string;
  description: string;
  source: string;
  reference_text: string;
  available: boolean;
  unavailable_reason?: string;
}

export interface MentionResourcePage {
  items: MentionResource[];
  total: number;
  has_more: boolean;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function parseMentionResource(
  value: unknown,
  expectedType: MentionResourceType,
): MentionResource | null {
  const record = asRecord(value);
  if (!record) return null;
  const resourceType = asString(record.resource_type);
  if (!isMentionResourceType(resourceType) || resourceType !== expectedType) {
    return null;
  }
  const resourceId = asString(record.resource_id).trim();
  const name = asString(record.name).trim();
  const referenceText = asString(record.reference_text);
  if (!resourceId || !name || !referenceText) return null;
  const unavailableReason = asString(record.unavailable_reason).trim();
  return {
    resource_type: resourceType,
    resource_id: resourceId,
    name,
    description: asString(record.description),
    source: asString(record.source),
    reference_text: referenceText,
    available: record.available === true,
    ...(unavailableReason ? { unavailable_reason: unavailableReason } : {}),
  };
}

export function parseMentionResourcePage(
  value: unknown,
  expectedType: MentionResourceType,
): MentionResourcePage {
  const record = asRecord(value);
  const rawItems = Array.isArray(record?.items) ? record.items : [];
  const items = rawItems.flatMap((item) => {
    const parsed = parseMentionResource(item, expectedType);
    return parsed ? [parsed] : [];
  });
  const total = typeof record?.total === "number" && Number.isFinite(record.total)
    ? Math.max(0, Math.trunc(record.total))
    : items.length;
  return {
    items,
    total,
    has_more: record?.has_more === true,
  };
}

export function mentionResourcesPath(
  sessionId: string,
  params: {
    resourceType: MentionResourceType;
    q?: string;
    offset?: number;
    limit?: number;
  },
): string {
  const query = new URLSearchParams({
    resource_type: params.resourceType,
    q: params.q ?? "",
    offset: String(params.offset ?? 0),
    limit: String(params.limit ?? MENTION_PAGE_SIZE),
  });
  return `/sessions/${encodeURIComponent(sessionId)}/mention-resources?${query}`;
}

export async function fetchMentionResources(
  sessionId: string,
  params: {
    resourceType: MentionResourceType;
    q?: string;
    offset?: number;
    limit?: number;
  },
  options?: { signal?: AbortSignal },
): Promise<MentionResourcePage> {
  const raw = await request<unknown>(mentionResourcesPath(sessionId, params), {
    signal: options?.signal,
  });
  return parseMentionResourcePage(raw, params.resourceType);
}
