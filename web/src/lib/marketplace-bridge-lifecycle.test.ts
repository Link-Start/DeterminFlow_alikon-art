import assert from "node:assert/strict";
import test from "node:test";
import { MarketplaceBridgeHost, inspectMarketplaceBridgeMessage } from "./marketplace-bridge";
import { envelope, trustedSkill } from "./marketplace-bridge-fixtures";

const origin = "https://determinflow.com";
const requestId = "11111111-1111-4111-8111-111111111111";
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

test("cancel only accepts a correlated request id and no extra data", () => {
  assert.deepEqual(inspectMarketplaceBridgeMessage(envelope({ type: "cancel", requestId, method: undefined, payload: undefined })), { action: "cancel", requestId });
  assert.notEqual(inspectMarketplaceBridgeMessage(envelope({ type: "cancel", requestId, payload: { url: "https://evil.example" } })).action, "cancel");
});

test("cancel closes confirmation and a late acceptance never installs", async () => {
  const frame = {};
  let accept!: (value: boolean) => void;
  let signal: AbortSignal | undefined;
  let installs = 0;
  const posted: Array<{ type?: string; error?: { code: string } }> = [];
  const host = new MarketplaceBridgeHost({
    expectedOrigin: origin, getContentWindow: () => frame,
    postMessage: (message) => posted.push(message as typeof posted[number]),
    invoke: async (method) => {
      if (method === "skills.get") return trustedSkill();
      installs++; return {};
    },
    confirm: (_method, _payload, context) => {
      signal = context.signal;
      return new Promise((resolve) => { accept = resolve; });
    },
    notify: () => undefined,
  });
  const send = (data: unknown) => host.handleMessage({ source: frame, origin, data });
  send(envelope({ type: "ready", requestId: undefined, method: undefined, payload: undefined }));
  send(envelope({ requestId, method: "skill.install", payload: { slug: "writing-helper" } }));
  await flush();
  assert.ok(signal);
  send(envelope({ type: "cancel", requestId, method: undefined, payload: undefined }));
  await flush();
  assert.equal(signal.aborted, true);
  accept(true);
  await flush();
  assert.equal(installs, 0);
  assert.equal(posted[posted.length - 1]?.error?.code, "cancelled");
  host.reset();
});

test("executing writes keep their result after 30 seconds and ignore cancellation", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const frame = {};
  let finish!: (value: unknown) => void;
  const posted: Array<{ type?: string; ok?: boolean; payload?: unknown }> = [];
  const host = new MarketplaceBridgeHost({
    expectedOrigin: origin, getContentWindow: () => frame,
    postMessage: (message) => posted.push(message as typeof posted[number]),
    invoke: () => new Promise((resolve) => { finish = resolve; }),
    confirm: async () => true, notify: () => undefined,
  });
  const send = (data: unknown) => host.handleMessage({ source: frame, origin, data });
  send(envelope({ type: "ready", requestId: undefined, method: undefined, payload: undefined }));
  send(envelope({ requestId, method: "favorite.set", payload: { slug: "writing-helper", favorited: true } }));
  await flush();
  t.mock.timers.tick(31_000);
  await flush();
  assert.equal(posted.some((item) => item.type === "response"), false);
  assert.equal(posted.some((item) => item.type === "progress"), true);
  send(envelope({ type: "cancel", requestId, method: undefined, payload: undefined }));
  finish({ favorited: true });
  await flush();
  assert.equal(posted[posted.length - 1]?.ok, true);
  host.reset();
});
