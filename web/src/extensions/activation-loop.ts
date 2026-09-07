const EXTENSION_STATUS_RETRY_MS = 3_000;

interface ExtensionActivationLoopOptions<T> {
  load: () => Promise<T>;
  onLoaded: (value: T) => void;
  onError: (error: unknown) => void;
  retryDelayMs?: number;
  scheduleRetry?: (callback: () => void, delayMs: number) => number;
  cancelRetry?: (handle: number) => void;
}

export function startExtensionActivationLoop<T>({
  load,
  onLoaded,
  onError,
  retryDelayMs = EXTENSION_STATUS_RETRY_MS,
  scheduleRetry = (callback, delayMs) => window.setTimeout(callback, delayMs),
  cancelRetry = (handle) => window.clearTimeout(handle),
}: ExtensionActivationLoopOptions<T>): () => void {
  let active = true;
  let retryHandle: number | undefined;

  async function activate(): Promise<void> {
    try {
      const nextValue = await load();
      if (active) onLoaded(nextValue);
    } catch (error) {
      if (!active) return;
      onError(error);
      retryHandle = scheduleRetry(() => {
        retryHandle = undefined;
        void activate();
      }, retryDelayMs);
    }
  }

  void activate();

  return () => {
    active = false;
    if (retryHandle !== undefined) cancelRetry(retryHandle);
  };
}
