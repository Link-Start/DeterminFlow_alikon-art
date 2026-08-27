import assert from "node:assert/strict";
import test from "node:test";

import {
  appendSeenAnnouncementKey,
  collectAnnouncementsToQueue,
  createBrowserAnnouncementStore,
  createDesktopAnnouncementStore,
  createSeenAnnouncementState,
  extensionAnnouncementKey,
  normalizeSeenAnnouncementKeys,
  readSeenAnnouncementKeys,
  rememberAnnouncementKey,
  resolveAnnouncementStateStore,
  type PendingExtensionAnnouncement,
} from "./extension-announcement-state";

class MemoryStorage {
  private readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

function createDeferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function announcement(
  overrides: Partial<PendingExtensionAnnouncement> = {},
): PendingExtensionAnnouncement {
  return {
    id: "notice-1",
    title: "维护通知",
    body: "公益模型将于今晚维护。",
    level: "maintenance",
    published_at: "2026-08-27T02:00:00.000Z",
    extensionId: "public-api",
    extensionName: "公益模型",
    ...overrides,
  };
}

test("stores only stable extension and announcement identities", () => {
  const storage = new MemoryStorage();
  const first = extensionAnnouncementKey("public-api", "notice-1");
  const second = extensionAnnouncementKey("public-api", "notice-2");

  rememberAnnouncementKey(storage, first);
  rememberAnnouncementKey(storage, second);
  rememberAnnouncementKey(storage, first);

  assert.deepEqual([...readSeenAnnouncementKeys(storage)], [second, first]);
});

test("fails open when persisted state is unavailable", () => {
  const blockedStorage = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
  };

  assert.deepEqual([...readSeenAnnouncementKeys(blockedStorage)], []);
  assert.doesNotThrow(() => rememberAnnouncementKey(blockedStorage, "public-api:notice-1"));
});

test("keeps a bounded history of seen announcements", () => {
  const storage = new MemoryStorage();
  for (let index = 0; index < 201; index += 1) {
    rememberAnnouncementKey(storage, `public-api:notice-${index}`);
  }

  const seen = [...readSeenAnnouncementKeys(storage)];
  assert.equal(seen.length, 200);
  assert.equal(seen[0], "public-api:notice-1");
  assert.equal(seen[199], "public-api:notice-200");
  assert.deepEqual(
    appendSeenAnnouncementKey(["public-api:notice-1"], ""),
    ["public-api:notice-1"],
  );
  assert.deepEqual(
    normalizeSeenAnnouncementKeys(["public-api:notice-1", 2, null, "", "public-api:notice-1"]),
    ["public-api:notice-1"],
  );
});

test("web mode persists confirmed announcements through localStorage", async () => {
  const storage = new MemoryStorage();
  const store = resolveAnnouncementStateStore({
    desktopRuntime: false,
    storage,
  });
  const state = createSeenAnnouncementState(store);

  await state.whenReady();
  await state.remember("public-api:notice-1");

  assert.deepEqual([...readSeenAnnouncementKeys(storage)], ["public-api:notice-1"]);
  assert.deepEqual(
    await createBrowserAnnouncementStore(storage).load(),
    ["public-api:notice-1"],
  );
});

test("desktop mode reads and writes the stable Tauri command payload", async () => {
  const calls: Array<{ command: string; args?: Record<string, unknown> }> = [];
  const store = createDesktopAnnouncementStore(async (command, args) => {
    calls.push({ command, args });
    if (command === "get_desktop_announcement_state") return ["public-api:notice-1"];
    return undefined;
  });

  assert.deepEqual(await store.load(), ["public-api:notice-1"]);
  await store.save(["public-api:notice-2"]);

  assert.deepEqual(calls, [
    { command: "get_desktop_announcement_state", args: undefined },
    {
      command: "set_desktop_announcement_state",
      args: { keys: ["public-api:notice-2"] },
    },
  ]);
});

test("desktop runtime does not fall back to origin-scoped localStorage", async () => {
  const storage = new MemoryStorage();
  rememberAnnouncementKey(storage, "public-api:notice-web");
  const calls: string[] = [];
  const store = resolveAnnouncementStateStore({
    desktopRuntime: true,
    storage,
    invoke: async (command) => {
      calls.push(command);
      return ["public-api:notice-desktop"];
    },
  });

  assert.deepEqual(await store.load(), ["public-api:notice-desktop"]);
  assert.deepEqual(calls, ["get_desktop_announcement_state"]);
  assert.deepEqual([...readSeenAnnouncementKeys(storage)], ["public-api:notice-web"]);
});

test("does not enqueue announcements until persisted state has loaded", () => {
  const items = [announcement()];
  const queued = collectAnnouncementsToQueue(items, new Set(), new Set(), false);

  assert.deepEqual(queued, []);
});

test("skips announcements already confirmed or already queued", () => {
  const older = announcement({
    id: "notice-older",
    published_at: "2026-08-26T02:00:00.000Z",
  });
  const newer = announcement({
    id: "notice-newer",
    published_at: "2026-08-27T04:00:00.000Z",
  });
  const seen = announcement({ id: "notice-seen" });
  const skipped = announcement({ id: "notice-skipped" });

  const queued = collectAnnouncementsToQueue(
    [older, seen, skipped, newer, newer],
    new Set(["public-api:notice-seen"]),
    new Set(["public-api:notice-skipped"]),
    true,
  );

  assert.deepEqual(queued.map((item) => item.id), ["notice-newer", "notice-older"]);
});

test("merges confirmations that arrive while desktop state is still loading", async () => {
  const load = createDeferred<unknown>();
  const saves: string[][] = [];
  const state = createSeenAnnouncementState({
    load: () => load.promise,
    async save(keys) {
      saves.push([...keys]);
    },
  });

  const remembered = state.remember("public-api:notice-1");
  assert.deepEqual([...state.snapshot()], ["public-api:notice-1"]);
  assert.equal(
    collectAnnouncementsToQueue(
      [announcement()],
      state.snapshot(),
      new Set(),
      false,
    ).length,
    0,
  );

  load.resolve(["public-api:notice-0"]);
  await state.whenReady();
  await remembered;

  assert.deepEqual([...state.snapshot()], ["public-api:notice-0", "public-api:notice-1"]);
  assert.deepEqual(saves.at(-1), ["public-api:notice-0", "public-api:notice-1"]);
});

test("serializes overlapping writes so the latest snapshot keeps every key", async () => {
  const saves: string[][] = [];
  const state = createSeenAnnouncementState({
    async load() {
      return [];
    },
    async save(keys) {
      await new Promise((resolve) => setTimeout(resolve, 5));
      saves.push([...keys]);
    },
  });

  await state.whenReady();
  await Promise.all([
    state.remember("public-api:notice-1"),
    state.remember("public-api:notice-2"),
  ]);

  assert.deepEqual(saves.at(-1), ["public-api:notice-1", "public-api:notice-2"]);
});

test("load failures fail open without dropping in-session confirmations", async () => {
  const saves: string[][] = [];
  const state = createSeenAnnouncementState({
    async load() {
      throw new Error("unreadable");
    },
    async save(keys) {
      saves.push([...keys]);
    },
  });

  await state.whenReady();
  assert.deepEqual([...state.snapshot()], []);
  await state.remember("public-api:notice-1");

  assert.deepEqual([...state.snapshot()], ["public-api:notice-1"]);
  assert.deepEqual(saves.at(-1), ["public-api:notice-1"]);
});

test("save failures keep the current session from showing the same announcement", async () => {
  const state = createSeenAnnouncementState({
    async load() {
      return [];
    },
    async save() {
      throw new Error("read-only");
    },
  });

  await state.whenReady();
  await assert.doesNotReject(() => state.remember("public-api:notice-1"));
  assert.equal(state.snapshot().has("public-api:notice-1"), true);
  assert.deepEqual(
    collectAnnouncementsToQueue(
      [announcement()],
      state.snapshot(),
      new Set(),
      true,
    ),
    [],
  );
});
