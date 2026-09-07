import assert from "node:assert/strict";
import test from "node:test";

import { MarketplaceApiError } from "./skill-marketplace-http";
import {
  marketplaceSkillUpdateCanRetry,
  marketplaceSkillUpdateIsDisabled,
  marketplaceSkillUpdateLabel,
  marketplaceSkillUpdateStatusFromError,
  marketplaceSkillUpdateStatusFromSkill,
} from "./marketplace-skill-update";

test("installed catalog rows distinguish current and available updates", () => {
  assert.equal(
    marketplaceSkillUpdateStatusFromSkill({
      installation: { status: "installed", update_available: true },
    }),
    "available",
  );
  assert.equal(
    marketplaceSkillUpdateStatusFromSkill({
      installation: { status: "installed", update_available: false },
    }),
    "current",
  );
  assert.equal(
    marketplaceSkillUpdateStatusFromSkill({
      installation: { status: "conflict", update_available: true },
    }),
    "unavailable",
  );
});

test("missing or delisted resources are not treated as retryable network failures", () => {
  assert.equal(
    marketplaceSkillUpdateStatusFromError(new MarketplaceApiError("not_found", "Skill 不存在")),
    "missing",
  );
  assert.equal(marketplaceSkillUpdateLabel("missing"), "资源已下架");
  assert.equal(marketplaceSkillUpdateCanRetry("missing"), false);
  assert.equal(marketplaceSkillUpdateIsDisabled("missing"), true);
});

test("temporary marketplace failures remain retryable", () => {
  assert.equal(
    marketplaceSkillUpdateStatusFromError(new MarketplaceApiError("network_unavailable", "暂时无法连接资源广场")),
    "failed",
  );
  assert.equal(
    marketplaceSkillUpdateStatusFromError(new MarketplaceApiError("service_unavailable", "资源广场服务暂不可用")),
    "failed",
  );
  assert.equal(marketplaceSkillUpdateStatusFromError(new TypeError("Failed to fetch")), "failed");
  assert.equal(marketplaceSkillUpdateLabel("failed"), "重试检查");
  assert.equal(marketplaceSkillUpdateCanRetry("failed"), true);
  assert.equal(marketplaceSkillUpdateIsDisabled("failed"), false);
});
