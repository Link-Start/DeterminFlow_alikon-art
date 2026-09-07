import assert from "node:assert/strict";
import test from "node:test";

import { skillContentLicense, skillUsageAuthorization } from "./skill-license";

test("marketplace usage authorization comes from the source record, not an undeclared package field", () => {
  const skill = {
    license: "",
    provenance: {
      source: { kind: "marketplace" as const },
      package: { license: "MIT" },
    },
  };
  assert.equal(skillContentLicense(skill), null);
  assert.deepEqual(skillUsageAuthorization(skill), {
    id: "MIT",
    label: "MIT",
    href: "https://opensource.org/license/mit",
  });
});

test("community use authorization keeps a readable name and public terms link", () => {
  const auth = skillUsageAuthorization({
    license: "",
    provenance: {
      source: { kind: "marketplace" },
      package: { license: "LicenseRef-DF-Community-1.0" },
    },
  });
  assert.equal(auth?.label, "社区使用授权 1.0");
  assert.equal(
    auth?.href,
    "https://determinflow.com/marketplace/terms?license=LicenseRef-DF-Community-1.0",
  );
});

test("undeclared marketplace packages do not fall back to 未声明", () => {
  const skill = {
    license: "",
    provenance: { source: { kind: "marketplace" }, package: {} },
  };
  assert.equal(skillContentLicense(skill), null);
  assert.equal(skillUsageAuthorization(skill), null);
});

test("local skills keep a declared package license and have no marketplace authorization record", () => {
  const skill = { license: "Apache-2.0", provenance: { source: { kind: "local" } } };
  assert.equal(skillContentLicense(skill), "Apache-2.0");
  assert.equal(skillUsageAuthorization(skill), null);
});
