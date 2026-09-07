import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CircleDollarSign, ExternalLink, RefreshCw } from "lucide-react";

import { cn } from "@/lib/utils";
import { useExtensionStatuses } from "./context-value";
import {
  isActiveHeaderStatusSource,
  parseHeaderStatusResponse,
  unavailableHeaderStatus,
  type HeaderStatusAction,
  type HeaderStatusPayload,
} from "./header-status-model";
import { ExtensionAnnouncementDialog } from "./ExtensionAnnouncementDialog";
import { ExtensionHeaderPagePanel } from "./ExtensionHeaderPagePanel";
import {
  collectAnnouncementsToQueue,
  createSeenAnnouncementState,
  extensionAnnouncementKey,
  resolveAnnouncementStateStore,
  type PendingExtensionAnnouncement,
} from "./extension-announcement-state";
import type { ExtensionStatus } from "./types";

const POLL_INTERVAL_MS = 60_000;

interface ExtensionHeaderStatusSlotProps {
  onManage: (extensionId: string) => void;
}

interface StatusEntry {
  source: ExtensionStatus;
  payload: HeaderStatusPayload;
}

interface HeaderPageState {
  extensionId: string;
  title: string;
}

function responseError(body: unknown, fallback: string): string {
  if (
    typeof body === "object"
    && body !== null
    && "detail" in body
    && typeof body.detail === "string"
    && body.detail.trim()
  ) {
    return body.detail;
  }
  return fallback;
}

async function fetchHeaderStatus(
  source: ExtensionStatus,
  refresh = false,
): Promise<HeaderStatusPayload | null> {
  const endpoint = refresh
    ? source.header_status?.refresh_endpoint
    : source.header_status?.endpoint;
  if (!endpoint) return null;
  const response = await fetch(endpoint, {
    method: refresh ? "POST" : "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`Header status request failed: ${response.status}`);
  const body = await response.json();
  if (body?.header_status?.visible === false) return null;
  const payload = parseHeaderStatusResponse(body);
  if (!payload) throw new Error("插件状态响应无效");
  return payload;
}

export function ExtensionHeaderStatusSlot({ onManage }: ExtensionHeaderStatusSlotProps) {
  const statuses = useExtensionStatuses();
  const sources = useMemo(
    () => statuses.filter(isActiveHeaderStatusSource),
    [statuses],
  );
  const [entries, setEntries] = useState<Record<string, StatusEntry>>({});
  const [page, setPage] = useState<HeaderPageState | null>(null);
  const [announcementQueue, setAnnouncementQueue] = useState<PendingExtensionAnnouncement[]>([]);
  const queuedAnnouncementKeys = useRef(new Set<string>());
  const seenThisSession = useRef(new Set<string>());
  const seenState = useRef(createSeenAnnouncementState(resolveAnnouncementStateStore())).current;
  const [seenReady, setSeenReady] = useState(false);
  const closePage = useCallback(() => setPage(null), []);

  useEffect(() => {
    let active = true;
    void seenState.whenReady().then(() => {
      if (active) setSeenReady(true);
    });
    return () => {
      active = false;
    };
  }, [seenState]);

  const load = useCallback(async (source: ExtensionStatus, refresh = false) => {
    try {
      const payload = await fetchHeaderStatus(source, refresh);
      setEntries((current) => {
        if (!payload) {
          const next = { ...current };
          delete next[source.id];
          return next;
        }
        return { ...current, [source.id]: { source, payload } };
      });
      return Boolean(payload);
    } catch {
      setEntries((current) => ({ ...current, [source.id]: { source, payload: unavailableHeaderStatus(source) } }));
      return false;
    }
  }, []);

  const executeRequest = useCallback(async (
    source: ExtensionStatus,
    action: HeaderStatusAction,
  ) => {
    if (action.kind !== "request" || !action.endpoint || !action.method) return;
    const response = await fetch(action.endpoint, {
      method: action.method,
      headers: { Accept: "application/json" },
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(responseError(body, `插件操作失败：${response.status}`));
    }
    const payload = parseHeaderStatusResponse(body);
    if (payload) {
      setEntries((current) => ({
        ...current,
        [source.id]: { source, payload },
      }));
      return;
    }
    await load(source);
  }, [load]);

  useEffect(() => {
    let active = true;
    const poll = () => {
      if (!active) return;
      for (const source of sources) void load(source);
    };
    poll();
    const interval = window.setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [load, sources]);

  useEffect(() => {
    const items = Object.values(entries).flatMap((entry) => (
      entry.payload.announcements.map((announcement) => ({
        ...announcement,
        extensionId: entry.source.id,
        extensionName: entry.source.name,
      }))
    ));
    const additions = collectAnnouncementsToQueue(
      items,
      seenState.snapshot(),
      new Set([
        ...seenThisSession.current,
        ...queuedAnnouncementKeys.current,
      ]),
      seenReady,
    );
    for (const item of additions) {
      queuedAnnouncementKeys.current.add(extensionAnnouncementKey(item.extensionId, item.id));
    }
    if (additions.length > 0) {
      setAnnouncementQueue((current) => [...current, ...additions]);
    }
  }, [entries, seenReady, seenState]);

  const closeAnnouncement = useCallback(() => {
    setAnnouncementQueue((current) => {
      const active = current[0];
      if (!active) return current;
      const key = extensionAnnouncementKey(active.extensionId, active.id);
      seenThisSession.current.add(key);
      queuedAnnouncementKeys.current.delete(key);
      void seenState.remember(key);
      return current.slice(1);
    });
  }, [seenState]);

  const visible = sources
    .map((source) => entries[source.id])
    .filter((entry): entry is StatusEntry => Boolean(entry));
  if (visible.length === 0) return null;

  return (
    <>
      <div className="flex shrink-0 items-center gap-2" aria-label="插件状态">
        {visible.map((entry) => (
          <HeaderStatusItem
            key={entry.source.id}
            entry={entry}
            onManage={() => onManage(entry.source.id)}
            onLoad={load}
            onRequest={(action) => executeRequest(entry.source, action)}
            onOpenPage={(title) => setPage({ extensionId: entry.source.id, title })}
          />
        ))}
      </div>
      {page ? (
        <ExtensionHeaderPagePanel
          extensionId={page.extensionId}
          title={page.title}
          onClose={closePage}
        />
      ) : null}
      {announcementQueue[0] ? (
        <ExtensionAnnouncementDialog
          announcement={announcementQueue[0]}
          onClose={closeAnnouncement}
        />
      ) : null}
    </>
  );
}

function HeaderStatusItem({
  entry,
  onManage,
  onLoad,
  onRequest,
  onOpenPage,
}: {
  entry: StatusEntry;
  onManage: () => void;
  onLoad: (source: ExtensionStatus, refresh?: boolean) => Promise<boolean>;
  onRequest: (action: HeaderStatusAction) => Promise<void>;
  onOpenPage: (title: string) => void;
}) {
  const { payload } = entry;
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const suppressFocusOpenRef = useRef(false);
  const open = hovered || focused || pinned;
  const popoverId = `extension-header-status-${entry.source.id}`;

  const dismiss = useCallback((restoreTriggerFocus: boolean) => {
    setPinned(false);
    setHovered(false);
    setFocused(false);

    const root = rootRef.current;
    const trigger = root?.querySelector<HTMLButtonElement>("[data-status-trigger]");
    if (restoreTriggerFocus && trigger) {
      suppressFocusOpenRef.current = true;
      trigger.focus({ preventScroll: true });
      window.queueMicrotask(() => {
        suppressFocusOpenRef.current = false;
      });
      return;
    }
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement && root?.contains(activeElement)) {
      activeElement.blur();
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        dismiss(true);
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) dismiss(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [dismiss, open]);

  useEffect(() => {
    if (!payload.refresh_after_ms) return;
    const interval = window.setInterval(() => {
      void onLoad(entry.source);
    }, payload.refresh_after_ms);
    return () => window.clearInterval(interval);
  }, [entry.source, onLoad, payload.refresh_after_ms]);

  const toneClass = {
    normal: "border-success/35 text-success hover:bg-success/10",
    attention: "border-warning/40 text-warning hover:bg-warning/10",
    critical: "border-destructive/45 text-destructive hover:bg-destructive/10",
    stale: "border-border/60 text-foreground hover:bg-muted/60",
  }[payload.tone];
  const metricColumns = payload.metrics.length === 1
    ? "grid-cols-1"
    : payload.metrics.length === 2
      ? "grid-cols-2"
      : "grid-cols-3";

  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    await onLoad(entry.source, true);
    setRefreshing(false);
  };

  const request = async (action: HeaderStatusAction) => {
    if (actionBusy) return;
    setActionBusy(action.id);
    setActionError("");
    try {
      await onRequest(action);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "插件操作失败");
    } finally {
      setActionBusy(null);
    }
  };

  return (
    <div
      ref={rootRef}
      className="relative"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => {
        if (!suppressFocusOpenRef.current) setFocused(true);
      }}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false);
      }}
    >
      <button
        type="button"
        data-status-trigger
        className={cn(
          "flex h-9 items-center gap-1.5 rounded-md border bg-card/35 px-2.5 text-sm font-semibold tabular-nums transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
          toneClass,
        )}
        aria-expanded={open}
        aria-controls={popoverId}
        aria-label={`${payload.title} ${payload.value}`}
        onClick={() => setPinned((value) => !value)}
      >
        <CircleDollarSign className="h-4 w-4" aria-hidden="true" />
        <span className="hidden 2xl:inline">{payload.label}</span>
        <span>{payload.value}</span>
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-[70] w-[min(22rem,calc(100vw-2rem))] pt-2.5 max-sm:fixed max-sm:left-3 max-sm:right-3 max-sm:top-14 max-sm:w-auto max-sm:pt-0">
          <section
            id={popoverId}
            className="rounded-xl border border-border bg-background p-4 text-foreground shadow-2xl shadow-black/40"
            aria-label={payload.title}
          >
            <div>
              <h2 className="text-sm font-semibold">{payload.title}</h2>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {payload.summary_href ? (
                  <a
                    href={payload.summary_href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  >
                    {payload.summary}
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                ) : payload.summary}
              </p>
            </div>

            <dl className={cn("mt-4 grid gap-2", metricColumns)}>
              {payload.metrics.map((metric) => (
                <div key={metric.label} className="min-w-0 rounded-lg bg-card px-3 py-2.5">
                  <dt className="truncate text-[11px] text-muted-foreground">{metric.label}</dt>
                  <dd className="mt-1 truncate text-sm font-semibold tabular-nums text-foreground">{metric.value}</dd>
                </div>
              ))}
            </dl>

            <dl className="mt-4 space-y-2 border-t border-border pt-3 text-xs">
              {payload.metadata.map((item) => (
                <div key={item.label} className="flex items-center justify-between gap-4">
                  <dt className="text-muted-foreground">{item.label}</dt>
                  <dd className="text-right text-foreground">{item.value}</dd>
                </div>
              ))}
            </dl>

            <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-border pt-3">
              <button
                type="button"
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs text-foreground hover:bg-secondary disabled:opacity-50"
                onClick={() => void refresh()}
                disabled={refreshing}
              >
                <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} aria-hidden="true" />
                刷新
              </button>
              {payload.actions.map((action) => action.kind === "manage" ? (
                <button
                  key={action.id}
                  type="button"
                  className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-medium text-white hover:bg-primary"
                  onClick={onManage}
                >
                  {action.label}
                </button>
              ) : action.kind === "page" ? (
                <button
                  key={action.id}
                  type="button"
                  className="inline-flex h-8 items-center rounded-md border border-border px-3 text-xs font-medium text-foreground hover:bg-secondary"
                  onClick={() => {
                    dismiss(false);
                    onOpenPage(action.label);
                  }}
                >
                  {action.label}
                </button>
              ) : action.kind === "request" ? (
                <button
                  key={action.id}
                  type="button"
                  className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-medium text-white hover:bg-primary disabled:cursor-wait disabled:opacity-60"
                  onClick={() => void request(action)}
                  disabled={actionBusy !== null}
                >
                  {actionBusy === action.id ? "处理中…" : action.label}
                </button>
              ) : (
                <a
                  key={action.id}
                  href={action.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-white hover:bg-primary"
                >
                  {action.label}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                </a>
              ))}
            </div>
            {actionError ? (
              <p className="mt-2 text-right text-xs text-destructive" role="alert">
                {actionError}
              </p>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}
