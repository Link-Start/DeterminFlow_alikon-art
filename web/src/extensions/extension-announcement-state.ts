import { isDesktopRuntime } from "../lib/desktop-update";

import type { ExtensionAnnouncement } from "./header-status-model";

const STORAGE_KEY = "determinflow:extension-announcements:v1";
const MAX_SEEN_ANNOUNCEMENTS = 200;

interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

type InvokeDesktop = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

export interface PendingExtensionAnnouncement extends ExtensionAnnouncement {
  extensionId: string;
  extensionName: string;
}

export interface AnnouncementStateStore {
  load(): Promise<unknown>;
  save(keys: string[]): Promise<void>;
}

export interface SeenAnnouncementState {
  whenReady(): Promise<void>;
  snapshot(): Set<string>;
  remember(key: string): Promise<void>;
}

export function extensionAnnouncementKey(extensionId: string, announcementId: string): string {
  return `${extensionId}:${announcementId}`;
}

export function normalizeSeenAnnouncementKeys(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const ordered: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || item.length === 0) continue;
    const existing = ordered.indexOf(item);
    if (existing >= 0) ordered.splice(existing, 1);
    ordered.push(item);
  }
  return ordered.length > MAX_SEEN_ANNOUNCEMENTS
    ? ordered.slice(-MAX_SEEN_ANNOUNCEMENTS)
    : ordered;
}

export function appendSeenAnnouncementKey(keys: readonly string[], key: string): string[] {
  return normalizeSeenAnnouncementKeys([...keys, key]);
}

export function readSeenAnnouncementKeys(storage: StorageLike | null): Set<string> {
  if (!storage) return new Set();
  try {
    return new Set(normalizeSeenAnnouncementKeys(JSON.parse(storage.getItem(STORAGE_KEY) ?? "[]")));
  } catch {
    return new Set();
  }
}

export function rememberAnnouncementKey(storage: StorageLike | null, key: string): void {
  if (!storage) return;
  try {
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify(appendSeenAnnouncementKey([...readSeenAnnouncementKeys(storage)], key)),
    );
  } catch {
    // A blocked localStorage must not prevent announcements from being displayed.
  }
}

export function browserStorage(): StorageLike | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

async function invokeDesktop(
  command: string,
  args?: Record<string, unknown>,
): Promise<unknown> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke(command, args);
}

export function createBrowserAnnouncementStore(
  storage: StorageLike | null,
): AnnouncementStateStore {
  return {
    async load() {
      if (!storage) return [];
      return JSON.parse(storage.getItem(STORAGE_KEY) ?? "[]");
    },
    async save(keys) {
      if (!storage) return;
      storage.setItem(STORAGE_KEY, JSON.stringify(keys));
    },
  };
}

export function createDesktopAnnouncementStore(
  invoke: InvokeDesktop = invokeDesktop,
): AnnouncementStateStore {
  return {
    async load() {
      return invoke("get_desktop_announcement_state");
    },
    async save(keys) {
      await invoke("set_desktop_announcement_state", { keys });
    },
  };
}

export function resolveAnnouncementStateStore(options?: {
  desktopRuntime?: boolean;
  storage?: StorageLike | null;
  invoke?: InvokeDesktop;
}): AnnouncementStateStore {
  if (options?.desktopRuntime ?? isDesktopRuntime()) {
    return createDesktopAnnouncementStore(options?.invoke ?? invokeDesktop);
  }
  return createBrowserAnnouncementStore(
    options && "storage" in options ? options.storage ?? null : browserStorage(),
  );
}

export function createSeenAnnouncementState(
  store: AnnouncementStateStore,
): SeenAnnouncementState {
  let keys: string[] = [];
  let writeChain = Promise.resolve();

  const loadPromise = (async () => {
    try {
      const loaded = normalizeSeenAnnouncementKeys(await store.load());
      keys = normalizeSeenAnnouncementKeys([...loaded, ...keys]);
    } catch {
      keys = normalizeSeenAnnouncementKeys(keys);
    }
  })();

  const persist = (): Promise<void> => {
    writeChain = writeChain.then(async () => {
      await loadPromise;
      try {
        await store.save(keys);
      } catch {
        // A failed write must not re-open announcements in the current session.
      }
    });
    return writeChain;
  };

  return {
    whenReady() {
      return loadPromise;
    },
    snapshot() {
      return new Set(keys);
    },
    remember(key: string) {
      keys = appendSeenAnnouncementKey(keys, key);
      return persist();
    },
  };
}

export function collectAnnouncementsToQueue(
  items: PendingExtensionAnnouncement[],
  seen: ReadonlySet<string>,
  skip: ReadonlySet<string>,
  ready: boolean,
): PendingExtensionAnnouncement[] {
  if (!ready) return [];
  const additions: PendingExtensionAnnouncement[] = [];
  const queued = new Set<string>();
  for (const item of items) {
    const key = extensionAnnouncementKey(item.extensionId, item.id);
    if (seen.has(key) || skip.has(key) || queued.has(key)) continue;
    queued.add(key);
    additions.push(item);
  }
  additions.sort((left, right) => Date.parse(right.published_at) - Date.parse(left.published_at));
  return additions;
}
