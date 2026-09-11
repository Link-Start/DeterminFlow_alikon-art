export const PINNED_SESSION_STORAGE_KEY = "determinflow.pinned-session-ids";

interface PinStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function browserStorage(): PinStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function normalizePinnedSessionIds(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of value) {
    if (typeof item !== "string" || item.length === 0 || seen.has(item)) continue;
    seen.add(item);
    result.push(item);
  }
  return result;
}

export function togglePinnedSessionId(ids: readonly string[], sessionId: string): string[] {
  if (!sessionId) return [...ids];
  if (ids.includes(sessionId)) return ids.filter((id) => id !== sessionId);
  return [sessionId, ...ids];
}

export function prunePinnedSessionIds(
  ids: readonly string[],
  knownIds: Iterable<string>,
): string[] {
  const known = new Set(knownIds);
  return ids.filter((id) => known.has(id));
}

export function collectPinnedItems<T>(
  items: readonly T[],
  getId: (item: T) => string,
  pinnedIds: readonly string[],
): T[] {
  const byId = new Map(items.map((item) => [getId(item), item]));
  const collected: T[] = [];
  for (const id of pinnedIds) {
    const item = byId.get(id);
    if (item) collected.push(item);
  }
  return collected;
}

export function readPinnedSessionIds(storage: PinStorage | null = browserStorage()): string[] {
  if (!storage) return [];
  try {
    return normalizePinnedSessionIds(JSON.parse(storage.getItem(PINNED_SESSION_STORAGE_KEY) ?? "[]"));
  } catch {
    return [];
  }
}

export function shouldShowRegularSessionHeading(
  pinnedCount: number,
  regularCount: number,
): boolean {
  return pinnedCount > 0 && regularCount > 0;
}

export function writePinnedSessionIds(
  ids: readonly string[],
  storage: PinStorage | null = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(PINNED_SESSION_STORAGE_KEY, JSON.stringify(normalizePinnedSessionIds(ids)));
  } catch {
    // Pin changes still apply for the current session when storage is unavailable.
  }
}
