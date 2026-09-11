import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchMentionResources, MENTION_PAGE_SIZE, type MentionResource,
} from "../../lib/mention-resources";
import type { MentionResourceType } from "../../types";
import { isAbortError, MENTION_SEARCH_DEBOUNCE_MS } from "./mentionSearch";

export type MentionResourceStatus = "idle" | "loading" | "ready" | "empty" | "error";
export interface MentionResourcesState {
  items: MentionResource[];
  hasMore: boolean;
  total: number;
  status: MentionResourceStatus;
  error: string | null;
  loadMore: () => void;
  retry: () => void;
}
interface PageState extends Omit<MentionResourcesState, "loadMore" | "retry"> {
  key: string | null;
  nextOffset: number;
}
const EMPTY: PageState = {
  key: null, items: [], hasMore: false, total: 0,
  status: "idle", error: null, nextOffset: 0,
};

export function useMentionResources(
  sessionId: string | null,
  resourceType: MentionResourceType | null,
  query: string,
  enabled: boolean,
): MentionResourcesState {
  const [page, setPage] = useState<PageState>(EMPTY);
  const [reload, setReload] = useState(0);
  const key = enabled && sessionId && resourceType
    ? JSON.stringify([sessionId, resourceType, query, reload]) : null;
  const keyRef = useRef(key);
  keyRef.current = key;
  // Mask stale rows during render, before the debounce or effect can run.
  const current = page.key === key ? page : {
    ...EMPTY, key, status: key ? "loading" as const : "idle" as const,
  };
  const pageRef = useRef(current);
  pageRef.current = current;
  const requestRef = useRef<{
    key: string; load: (offset: number, append: boolean) => Promise<void>;
  } | null>(null);
  const previousTypeRef = useRef<MentionResourceType | null>(null);
  const immediateRef = useRef(false);

  useEffect(() => {
    if (!key || !sessionId || !resourceType) {
      previousTypeRef.current = null;
      setPage(EMPTY);
      return;
    }
    const controller = new AbortController();
    const isCurrent = () => !controller.signal.aborted && keyRef.current === key;
    let pending = false;
    const load = async (offset: number, append: boolean) => {
      if (pending || !isCurrent()) return;
      pending = true;
      setPage((before) => ({
        ...(append && before.key === key ? before : EMPTY),
        key, status: "loading", error: null,
      }));
      try {
        const result = await fetchMentionResources(sessionId, {
          resourceType, q: query, offset, limit: MENTION_PAGE_SIZE,
        }, { signal: controller.signal });
        if (!isCurrent()) return;
        setPage((before) => {
          const existing = append && before.key === key ? before.items : [];
          const items = [...new Map([...existing, ...result.items].map(
            (item) => [item.resource_id, item],
          )).values()];
          return {
            key, items, total: result.total, hasMore: result.has_more,
            nextOffset: offset + result.items.length,
            status: items.length ? "ready" : "empty", error: null,
          };
        });
      } catch (cause) {
        if (!isCurrent() || isAbortError(cause)) return;
        setPage((before) => ({
          ...(before.key === key ? before : EMPTY),
          key, status: "error", error: "资源列表加载失败",
        }));
      } finally {
        pending = false;
      }
    };
    requestRef.current = { key, load };
    const immediate = previousTypeRef.current !== resourceType || immediateRef.current;
    previousTypeRef.current = resourceType;
    immediateRef.current = false;
    setPage({ ...EMPTY, key, status: "loading" });
    const timer = window.setTimeout(() => {
      void load(0, false);
    }, immediate ? 0 : MENTION_SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (requestRef.current?.key === key) requestRef.current = null;
    };
  }, [key, query, resourceType, sessionId]);

  const loadMore = useCallback(() => {
    const request = requestRef.current;
    const currentPage = pageRef.current;
    if (!request || request.key !== keyRef.current || !currentPage.hasMore) return;
    void request.load(currentPage.nextOffset, true);
  }, []);
  const retry = useCallback(() => {
    immediateRef.current = true;
    setReload((value) => value + 1);
  }, []);
  return { ...current, loadMore, retry };
}
