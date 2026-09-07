import assert from "node:assert/strict";
import test from "node:test";

import { startExtensionActivationLoop } from "./activation-loop";

async function flushPromises(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

test("retries a failed extension status load and publishes the recovered value", async () => {
  const events: string[] = [];
  let retry: (() => void) | undefined;
  let attempts = 0;

  const stop = startExtensionActivationLoop({
    load: async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("Core unavailable");
      return "running";
    },
    onLoaded: (value) => events.push(`loaded:${value}`),
    onError: (error) => events.push(`error:${String(error)}`),
    scheduleRetry: (callback, delayMs) => {
      assert.equal(delayMs, 3_000);
      retry = callback;
      return 1;
    },
    cancelRetry: () => undefined,
  });

  await flushPromises();
  assert.deepEqual(events, ["error:Error: Core unavailable"]);
  assert.ok(retry);

  retry();
  await flushPromises();
  assert.deepEqual(events, ["error:Error: Core unavailable", "loaded:running"]);
  assert.equal(attempts, 2);
  stop();
});

test("cancels a scheduled retry when the provider unmounts", async () => {
  let retryHandle: number | undefined;
  let cancelledHandle: number | undefined;

  const stop = startExtensionActivationLoop({
    load: async () => {
      throw new Error("Core unavailable");
    },
    onLoaded: () => undefined,
    onError: () => undefined,
    scheduleRetry: () => {
      retryHandle = 7;
      return retryHandle;
    },
    cancelRetry: (handle) => {
      cancelledHandle = handle;
    },
  });

  await flushPromises();
  assert.equal(retryHandle, 7);
  stop();
  assert.equal(cancelledHandle, 7);
});
