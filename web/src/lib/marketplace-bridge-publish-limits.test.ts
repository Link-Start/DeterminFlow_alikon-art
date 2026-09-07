import assert from "node:assert/strict";
import test from "node:test";
import { inspectMarketplaceBridgeMessage } from "./marketplace-bridge-protocol";
import { envelope } from "./marketplace-bridge-fixtures";

const fields = { license: "MIT", display_name: "Helper", author_name: "Ada", summary: "简介", functional_category: "general", primary_locale: "zh", tags_csv: "", release_notes: "" };
const payload = { ...fields, skill_id: "shared-skill", resource_type: "skill", rights_confirmed: true, terms_confirmed: true, terms_version: "2026-09-06" };
for (const [field, limit] of Object.entries({ summary: 50, release_notes: 150, usage_guide: 1000 })) {
  test(`bridge enforces ${field} character limits while preserving drafts`, () => {
    const value = "𠮷".repeat(limit);
    for (const method of ["resource.publish", "resource.publishPinned", "resource.publishPrepared"]) {
      const extra = { expected_sha256: "a".repeat(64), publication_version: "1.1.0", target_slug: "shared-skill" };
      const request = method === "resource.publish" ? payload : method === "resource.publishPinned" ? { ...payload, expected_sha256: extra.expected_sha256 } : { ...payload, ...extra };
      assert.equal(inspectMarketplaceBridgeMessage(envelope({ method, payload: { ...request, [field]: value } })).action, "request");
      assert.equal(inspectMarketplaceBridgeMessage(envelope({ method, payload: { ...request, [field]: value + "字" } })).action, "reject");
    }
    assert.equal(inspectMarketplaceBridgeMessage(envelope({ method: "publishDraft.save", payload: { skill_id: "shared-skill", expected_revision: null, base_version: "1.0.0", base_sha256: "a".repeat(64), fields: { ...fields, [field]: value + "字" } } })).action, "request");
  });
}
