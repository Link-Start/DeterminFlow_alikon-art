import assert from "node:assert/strict";
import test from "node:test";
import { MarketplaceBridgeHost, inspectMarketplaceBridgeMessage, marketplaceConfirmPrompt } from "./marketplace-bridge";
import { envelope, trustedSkill } from "./marketplace-bridge-fixtures";
import { readCompletedUpdate } from "./marketplace-install";
import { marketplaceSkillEmbedUrl, navigateToMarketplaceSkill, updateMarketplaceSkill } from "./skill-marketplace";

const pin = { expected_version_id: "11111111-1111-4111-8111-111111111111", expected_sha256: "a".repeat(64) };

test("update bridge accepts only pinned resource identity, never a download URL", () => {
  for (const extra of [{ url: "https://evil.example" }, { path: "/tmp/skill" }, { token: "secret" }, { expected_sha256: "invalid" }]) {
    assert.equal(inspectMarketplaceBridgeMessage(envelope({ method: "skill.updatePinned", payload: { slug: "writing-helper", ...pin, ...extra } })).action, "reject");
  }
  assert.equal(inspectMarketplaceBridgeMessage(envelope({ method: "skill.updatePinned", payload: { slug: "writing-helper", ...pin } })).action, "request");
});

for (const scenario of ["success", "cancelled", "latest", "stale"] as const) {
  test(`update bridge ${scenario} checks fresh local state before confirming`, async () => {
    const contentWindow = {};
    const posted: unknown[] = [];
    const calls: string[] = [];
    const host = new MarketplaceBridgeHost({
      expectedOrigin: "https://determinflow.com", getContentWindow: () => contentWindow,
      postMessage: (message) => posted.push(message), notify: () => {},
      confirm: async (method, payload) => {
        calls.push("confirm");
        assert.equal(method, "skill.updatePinned");
        assert.equal(payload.display_name, "Trusted Name");
        assert.equal(marketplaceConfirmPrompt(method, payload).confirmLabel, "更新");
        return scenario !== "cancelled";
      },
      invoke: async (method, payload) => {
        calls.push(method);
        if (method === "skills.get") return trustedSkill({
          name: "Trusted Name", ...(scenario === "stale" ? { sha256: "b".repeat(64) } : {}),
          installation: { status: "installed", version: "1.0.0", enabled: false, update_available: scenario !== "latest" },
        });
        assert.equal(method, "skill.updatePinned");
        assert.deepEqual(payload, { slug: "writing-helper", ...pin });
        return { installed: true, updated: true, enabled: false, skill_id: "writing-helper" };
      },
    });
    host.handleMessage({ source: contentWindow, origin: "https://determinflow.com", data: envelope({ type: "ready", method: undefined, requestId: undefined, payload: undefined }) });
    host.handleMessage({ source: contentWindow, origin: "https://determinflow.com", data: envelope({ method: "skill.updatePinned", payload: { slug: "writing-helper", ...pin } }) });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const response = posted[posted.length - 1] as { ok: boolean; payload?: { enabled: boolean }; error?: { code: string } };
    assert.deepEqual(calls, scenario === "success" ? ["skills.get", "confirm", "skill.updatePinned"] : scenario === "cancelled" ? ["skills.get", "confirm"] : ["skills.get"]);
    assert.equal(response.ok, scenario === "success");
    if (scenario === "success") assert.equal(response.payload?.enabled, false);
    if (scenario === "latest") assert.equal(response.error?.code, "update_unavailable");
    if (scenario === "stale") assert.equal(response.error?.code, "version_changed");
  });
}

test("update HTTP adapter retains disabled state and rejects incomplete receipts", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "/api/resource-marketplace/skills/writing-helper/update");
    assert.equal(init?.method, "POST");
    assert.deepEqual(JSON.parse(String(init?.body)), pin);
    return new Response(JSON.stringify({ installed: true, updated: true, enabled: false, skill_id: "writing-helper", installation: { status: "installed", enabled: false, version: "1.2.3", update_available: false } }));
  };
  try {
    const result = await updateMarketplaceSkill("writing-helper", pin);
    assert.equal(result.updated, true);
    assert.equal(result.enabled, false);
    assert.equal(result.installation?.update_available, false);
    for (const receipt of [null, { installed: true, enabled: true }, { installed: true, updated: true, enabled: false, skill_id: "other" }]) {
      assert.throws(() => readCompletedUpdate(receipt, "writing-helper"));
    }
  } finally { globalThis.fetch = originalFetch; }
});

test("update navigation preserves the local session and targets the approved embed", () => {
  const urls: string[] = [];
  const events: string[] = [];
  const runtime = { pathname: "/", search: "?session_id=current&tab=skills", hash: "", historyState: null,
    pushState: (_state: unknown, _unused: string, url: string) => urls.push(url),
    dispatchEvent: (event: Event) => { events.push(event.type); return true; } };
  navigateToMarketplaceSkill("writing-helper", runtime);
  const url = new URL(urls[0], "http://localhost");
  assert.equal(url.searchParams.get("session_id"), "current");
  assert.equal(url.searchParams.get("tab"), "marketplace");
  assert.equal(url.searchParams.get("marketplace_skill"), "writing-helper");
  assert.deepEqual(events, ["popstate"]);
  navigateToMarketplaceSkill("../other", runtime);
  assert.equal(urls.length, 1);
  assert.equal(marketplaceSkillEmbedUrl("https://determinflow.com/embed/marketplace", "writing-helper"), "https://determinflow.com/embed/marketplace?skill=writing-helper");
  assert.equal(marketplaceSkillEmbedUrl("https://determinflow.com/embed/marketplace", "https://evil.example"), "https://determinflow.com/embed/marketplace");
});
