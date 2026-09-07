import assert from "node:assert/strict";
import test from "node:test";

import { prepareMarketplaceInstall, readCompletedInstall, readTrustedInstallPin } from "./marketplace-install";
import { MarketplaceApiError, type MarketplaceSkill } from "./skill-marketplace";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function skill(overrides: Partial<MarketplaceSkill> = {}): MarketplaceSkill {
  return {
    slug: "writing-helper",
    name: "Writing Helper",
    description: "Helpful",
    version: "1.2.3",
    version_id: "11111111-1111-4111-8111-111111111111",
    sha256: "a".repeat(64),
    resource: {
      schema_version: 1,
      id: "resource-1",
      version_id: "11111111-1111-4111-8111-111111111111",
      resource_type: "skill",
      slug: "writing-helper",
      display_name: "Writing Helper",
      summary: "Helpful",
      functional_category: "general",
      primary_locale: "und",
      tags: [],
      author: { id: null, name: "" },
      release: {
        version: "1.2.3",
        license: "MIT",
        release_notes: "",
        published_at: null,
        created_at: null,
        updated_at: null,
      },
      links: { repository_url: null, homepage_url: null, support_url: null },
      compatibility: {
        determinflow_requires: "*",
        required_tools: [],
        required_plugins: [],
        required_apps: [],
      },
      community: {
        download_count: 0,
        downloads_30d: 0,
        favorite_count: 0,
        rating_average: null,
        rating_count: 0,
        review_count: 0,
      },
      lifecycle: { deprecated_at: null, replacement_slug: null, deprecation_message: null },
    },
    payload: {
      type: "skill",
      name: "writing-helper",
      format_version: 1,
      sha256: "a".repeat(64),
      size_bytes: 12,
    },
    resource_type: "skill",
    license: "MIT",
    publisher_name: "社区贡献者",
    author_name: "",
    author_description: "",
    category: "general",
    functional_category: "general",
    primary_locale: "und",
    tags: [],
    determinflow_requires: "*",
    required_tools: [],
    required_plugins: [],
    required_apps: [],
    repository_url: null,
    homepage_url: null,
    support_url: null,
    release_notes: "",
    published_at: null,
    created_at: null,
    updated_at: null,
    download_count: 0,
    downloads_30d: 0,
    favorite_count: 0,
    rating_average: null,
    rating_count: 0,
    review_count: 0,
    deprecated_at: null,
    replacement_slug: null,
    deprecation_message: null,
    viewer: null,
    ...overrides,
  } as MarketplaceSkill;
}

test("trusted install pin comes from fetched skill fields", () => {
  assert.deepEqual(readTrustedInstallPin(skill()), {
    slug: "writing-helper",
    displayName: "Writing Helper",
    version: "1.2.3",
    expected_version_id: "11111111-1111-4111-8111-111111111111",
    expected_sha256: "a".repeat(64),
  });
});

test("legacy skill.install waits for trusted details before building confirm copy", async () => {
  const pending = deferred<MarketplaceSkill>();
  const task = prepareMarketplaceInstall(
    async () => pending.promise,
    "skill.install",
    { slug: "writing-helper" },
  );
  pending.resolve(skill({ version: "2.0.0", name: "Trusted Name" }));
  const prepared = await task;
  assert.deepEqual(prepared.confirmPayload, {
    slug: "writing-helper",
    display_name: "Trusted Name",
    version: "2.0.0",
  });
  assert.deepEqual(prepared.invokePayload, {
    slug: "writing-helper",
    expected_version_id: "11111111-1111-4111-8111-111111111111",
    expected_sha256: "a".repeat(64),
  });
});

test("skill.installPinned rejects stale pins without using incoming display strings", async () => {
  await assert.rejects(
    prepareMarketplaceInstall(
      async () => skill({ version: "2.0.0" }),
      "skill.installPinned",
      {
        slug: "writing-helper",
        expected_version_id: "22222222-2222-4222-8222-222222222222",
        expected_sha256: "b".repeat(64),
        display_name: "Attacker Title",
        version: "9.9.9",
      },
    ),
    (error: unknown) => error instanceof MarketplaceApiError && error.code === "version_changed",
  );

  const prepared = await prepareMarketplaceInstall(
    async () => skill({ version: "2.0.0", name: "Fetched Name" }),
    "skill.installPinned",
    {
      slug: "writing-helper",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
      display_name: "Attacker Title",
      version: "9.9.9",
    },
  );
  assert.equal(prepared.confirmPayload.display_name, "Fetched Name");
  assert.equal(prepared.confirmPayload.version, "2.0.0");
  assert.equal(prepared.confirmPayload.display_name.includes("Attacker"), false);
});

test("completed install requires persisted enabled state, not a download receipt", () => {
  assert.deepEqual(
    readCompletedInstall({
      installed: true,
      skill_id: "writing-helper",
      enabled: true,
      downloaded: true,
    }),
    { installed: true, skill_id: "writing-helper", enabled: true },
  );
  for (const result of [
    { downloaded: true, skill_id: "writing-helper" },
    { installed: true, skill_id: "writing-helper" },
    { installed: true, skill_id: "writing-helper", enabled: false },
    { installed: true, skill_id: "../settings", enabled: true },
  ]) {
    assert.throws(
      () => readCompletedInstall(result),
      (error: unknown) => error instanceof MarketplaceApiError && error.code === "invalid_response",
    );
  }
});

test("completed install rejects a receipt for a different skill", () => {
  assert.throws(
    () => readCompletedInstall({ installed: true, skill_id: "another-skill", enabled: true }, "writing-helper"),
    (error: unknown) => error instanceof MarketplaceApiError && error.code === "invalid_response",
  );
});
