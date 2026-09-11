export const MENTION_SEARCH_DEBOUNCE_MS = 180;

export function isAbortError(cause: unknown): boolean {
  return Boolean(
    cause
    && typeof cause === "object"
    && "name" in cause
    && (cause as { name: string }).name === "AbortError",
  );
}
