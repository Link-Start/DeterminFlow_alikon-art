import assert from "node:assert/strict";
import test from "node:test";

import {
  AccountApiError,
  ACCOUNT_STATUS_EVENT,
  cancelAccountLogin,
  fetchAccountStatus,
  isAccountLoginPending,
  loginAccount,
  logoutAccount,
  requestAccountLogin,
} from "./account";

test("account endpoints use the Core-wide local contract", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; method: string }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({
      url: String(input),
      method: String(init?.method ?? "GET"),
    });
    return new Response(JSON.stringify({ configured: true, signed_in: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    assert.deepEqual(await fetchAccountStatus(), { configured: true, signed_in: true });
    await loginAccount();
    await logoutAccount();
    assert.deepEqual(requests, [
      { url: "/api/account/status", method: "GET" },
      { url: "/api/account/login", method: "POST" },
      { url: "/api/account/logout", method: "POST" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rapid login requests share both the confirmation and one browser authorization request", async () => {
  const originalFetch = globalThis.fetch;
  let prompts = 0;
  let requests = 0;
  let allow!: (value: boolean) => void;
  let complete!: (value: Response) => void;
  let requested!: () => void;
  const started = new Promise<void>((resolve) => { requested = resolve; });
  const confirmation = new Promise<boolean>((resolve) => { allow = resolve; });
  globalThis.fetch = async () => {
    requests += 1;
    const pending = new Promise<Response>((resolve) => { complete = resolve; });
    requested();
    return pending;
  };
  try {
    const prompt = () => { prompts += 1; return confirmation; };
    const waits = Array.from({ length: 20 }, () => requestAccountLogin(prompt));
    assert.ok(waits.every((wait) => wait === waits[0]));
    await Promise.resolve();
    assert.equal(prompts, 1);
    assert.equal(requests, 0);
    allow(true);
    await started;
    assert.equal(requests, 1);
    const direct = loginAccount();
    assert.equal(requests, 1);
    complete(new Response(JSON.stringify({ configured: true, signed_in: true })));
    assert.ok((await Promise.all([...waits, direct])).every((status) => status.signed_in));
  } finally { globalThis.fetch = originalFetch; }
});

test("declining login does not open the browser and does not queue later authorizations", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return new Response(JSON.stringify({ configured: true, signed_in: true })); };
  try {
    await assert.rejects(requestAccountLogin(async () => false), (error: unknown) => error instanceof AccountApiError && error.code === "cancelled");
    assert.equal(calls, 0);
    assert.equal((await requestAccountLogin(async () => true)).signed_in, true);
    assert.equal(calls, 1);
  } finally { globalThis.fetch = originalFetch; }
});

test("account errors preserve safe server messages", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { code: "authorization_denied", message: "账号登录已取消" },
  }), { status: 400, headers: { "content-type": "application/json" } });
  try {
    await assert.rejects(
      loginAccount(),
      (error: unknown) => error instanceof AccountApiError
        && error.code === "authorization_denied"
        && error.statusCode === 400
        && error.message === "账号登录已取消",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("cancel targets its attempt, ignores late success, and allows one fresh retry", async () => {
  const originalFetch = globalThis.fetch;
  const ids: string[] = [];
  let cancelledId = "";
  let finishOld!: (value: Response) => void;
  const response = (signedIn: boolean) => new Response(JSON.stringify({ configured: true, signed_in: signedIn }));
  globalThis.fetch = async (input, init) => {
    const id = JSON.parse(String(init?.body)).attempt_id;
    if (String(input).endsWith("/cancel")) {
      cancelledId = id;
      return response(false);
    }
    ids.push(id);
    if (ids.length === 1) return new Promise<Response>((resolve) => { finishOld = resolve; });
    return response(true);
  };
  try {
    const first = loginAccount();
    const rejected = assert.rejects(first, (error: unknown) => error instanceof AccountApiError && error.code === "cancelled");
    assert.equal(isAccountLoginPending(), true);
    await cancelAccountLogin();
    await rejected;
    assert.equal(isAccountLoginPending(), false);
    assert.equal(cancelledId, ids[0]);
    assert.equal((await loginAccount()).signed_in, true);
    assert.notEqual(ids[0], ids[1]);
    finishOld(response(true));
    await Promise.resolve();
    assert.equal(isAccountLoginPending(), false);
  } finally { globalThis.fetch = originalFetch; }
});

test("the client deadline clears a hung request even when fetch ignores abort", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  const originalFetch = globalThis.fetch;
  let cancels = 0;
  globalThis.fetch = async (input) => {
    if (String(input).endsWith("/cancel")) {
      cancels += 1;
      return new Response(JSON.stringify({ configured: true, signed_in: false }));
    }
    return new Promise<Response>(() => {});
  };
  try {
    const rejected = assert.rejects(loginAccount(), (error: unknown) => error instanceof AccountApiError && error.code === "request_timeout");
    context.mock.timers.tick(190_000);
    await rejected;
    // Let the bounded cancellation response settle as well.
    for (let index = 0; index < 20 && isAccountLoginPending(); index += 1) await Promise.resolve();
    assert.equal(cancels, 1);
    assert.equal(isAccountLoginPending(), false);
  } finally {
    globalThis.fetch = originalFetch;
    context.mock.timers.reset();
  }
});

test("a failed cancellation must be acknowledged before another authorization starts", async () => {
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  let failCancellation = true;
  globalThis.fetch = async (input) => {
    const url = String(input);
    requests.push(url);
    if (url.endsWith("/cancel") && failCancellation) {
      failCancellation = false;
      return new Response(JSON.stringify({ detail: "暂时无法连接" }), { status: 503 });
    }
    if (requests.length === 1) return new Promise<Response>(() => {});
    return new Response(JSON.stringify({ configured: true, signed_in: !url.endsWith("/cancel") }));
  };
  try {
    const first = assert.rejects(loginAccount(), (error: unknown) => error instanceof AccountApiError && error.code === "cancelled");
    await assert.rejects(cancelAccountLogin(), /暂时无法连接/);
    await first;
    assert.equal((await loginAccount()).signed_in, true);
    assert.deepEqual(requests, ["/api/account/login", "/api/account/login/cancel", "/api/account/login/cancel", "/api/account/login"]);
  } finally { globalThis.fetch = originalFetch; }
});

test("cancelling a signed-out login does not publish an identity change that resets embeds", async () => {
  const originalFetch = globalThis.fetch;
  const originalWindow = globalThis.window;
  globalThis.window = new EventTarget() as unknown as Window & typeof globalThis;
  let changed = 0;
  window.addEventListener(ACCOUNT_STATUS_EVENT, () => { changed += 1; });
  globalThis.fetch = async (input) => String(input).endsWith("/cancel")
    ? new Response(JSON.stringify({ configured: true, signed_in: false }))
    : new Promise<Response>(() => {});
  try {
    const first = assert.rejects(loginAccount(), (error: unknown) => error instanceof AccountApiError && error.code === "cancelled");
    await cancelAccountLogin();
    await first;
    assert.equal(changed, 0);
  } finally {
    globalThis.fetch = originalFetch;
    globalThis.window = originalWindow;
  }
});

test("network failures clear pending login and expose an actionable message", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  try {
    await assert.rejects(loginAccount(), (error: unknown) => error instanceof AccountApiError
      && error.code === "network_unavailable" && error.message.includes("重试"));
    assert.equal(isAccountLoginPending(), false);
  } finally { globalThis.fetch = originalFetch; }
});
