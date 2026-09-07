import assert from "node:assert/strict";
import test from "node:test";
import {
  MARKETPLACE_BRIDGE_CHANNEL,
  MARKETPLACE_BRIDGE_VERSION,
  MarketplaceBridgeHost,
} from "./marketplace-bridge";

for (const reset of [false, true]) {
  test(`installed Skill navigation ${reset ? "ignores a response after account/frame reset" : "opens the locally verified Skill"}`, async () => {
    const opened: string[] = [];
    const posted: unknown[] = [];
    const contentWindow = {};
    let finish!: (result: unknown) => void;
    const pending = new Promise((resolve) => { finish = resolve; });
    const host = new MarketplaceBridgeHost({
      expectedOrigin: "https://determinflow.com",
      getContentWindow: () => contentWindow,
      postMessage: (message) => posted.push(message),
      invoke: async () => pending,
      confirm: async () => { throw new Error("navigation does not install or enable"); },
      notify: () => {},
      openInstalledSkill: (skillId) => opened.push(skillId),
    });
    const send = (payload: Record<string, unknown>) => host.handleMessage({
      origin: "https://determinflow.com", source: contentWindow,
      data: { channel: MARKETPLACE_BRIDGE_CHANNEL, version: MARKETPLACE_BRIDGE_VERSION, ...payload },
    });
    send({ type: "ready" });
    send({ type: "request", requestId: "open-1", method: "skill.openInstalled", payload: { slug: "sample" } });
    if (reset) host.reset();
    finish({ opened: true, skill_id: "sample" });
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.deepEqual(opened, reset ? [] : ["sample"]);
    assert.equal(posted.length, reset ? 0 : 1);
  });
}

test("installed Skill navigation rejects a malformed local response", async () => {
  const opened: string[] = [];
  const posted: Array<unknown> = [];
  const contentWindow = {};
  const host = new MarketplaceBridgeHost({
    expectedOrigin: "https://determinflow.com", getContentWindow: () => contentWindow,
    postMessage: (message) => posted.push(message),
    invoke: async () => ({ opened: true, skill_id: "../../settings" }),
    confirm: async () => false, notify: () => {}, openInstalledSkill: (skillId) => opened.push(skillId),
  });
  for (const payload of [{ type: "ready" }, { type: "request", requestId: "bad-open", method: "skill.openInstalled", payload: { slug: "sample" } }]) {
    host.handleMessage({ origin: "https://determinflow.com", source: contentWindow,
      data: { channel: MARKETPLACE_BRIDGE_CHANNEL, version: MARKETPLACE_BRIDGE_VERSION, ...payload } });
  }
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(opened, []);
  assert.equal((posted[0] as { ok: boolean }).ok, false);
});
