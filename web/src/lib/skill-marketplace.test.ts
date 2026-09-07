import assert from "node:assert/strict";
import test from "node:test";

import {
  MarketplaceApiError,
  deleteMarketplaceReview,
  deletePublishDraft,
  fetchCommunityReviewPage,
  fetchMarketplaceSkill,
  fetchMarketplaceSkillPage,
  fetchMarketplaceSkills,
  fetchMarketplaceStatus,
  fetchMySubmissions,
  getPublishDraft,
  installMarketplaceSkill,
  listAuthorResources,
  listFeedback,
  markFeedbackRead,
  navigateToCoreSkill,
  openInstalledMarketplaceSkill,
  previewLocalSkill,
  previewMarketplaceSkill,
  publishMarketplaceSkill,
  reportMarketplaceReview,
  resumeMarketplaceSkill,
  saveMarketplaceReview,
  savePublishDraft,
  withdrawMarketplaceSubmission,
} from "./skill-marketplace";

test("marketplace status preserves embed_url from the local contract", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    configured: true,
    signed_in: false,
    account_name: null,
    marketplace_url: "https://determinflow.com",
    embed_url: "https://determinflow.com/embed/marketplace",
    resource_types: ["skill", "prompt", "agent", "workflow", "rule"],
    publishable_resource_types: ["skill"],
    functional_categories: ["general", "novel", "comic-drama", "media", "development", "productivity", "business", "education", "other"],
  }), { status: 200, headers: { "content-type": "application/json" } });
  try {
    assert.deepEqual(await fetchMarketplaceStatus(), {
      configured: true,
      signed_in: false,
      account_name: null,
      marketplace_url: "https://determinflow.com",
      embed_url: "https://determinflow.com/embed/marketplace",
      resource_types: ["skill", "prompt", "agent", "workflow", "rule"],
      publishable_resource_types: ["skill"],
      functional_categories: ["general", "novel", "comic-drama", "media", "development", "productivity", "business", "education", "other"],
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("marketplace list normalizes the public contract", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    items: [{
      slug: "writing-helper",
      skill_name: "writing-helper",
      summary: "Useful guidance",
      usage_guide: "作者提供的使用说明",
      version: "1.0.0",
      license: "MIT",
    }],
  }), { status: 200, headers: { "content-type": "application/json" } });
  try {
    const [skill] = await fetchMarketplaceSkills("writing");
    assert.equal(skill.slug, "writing-helper");
    assert.equal(skill.resource.usage_guide, "作者提供的使用说明");
    assert.equal(skill.functional_category, "general");
    assert.equal(skill.resource.functional_category, "general");
    assert.equal(skill.resource.release.version, "1.0.0");
    assert.deepEqual(skill.payload, {
      type: "skill",
      name: "writing-helper",
      format_version: 1,
      sha256: null,
      size_bytes: null,
    });
    assert.equal(skill.installation, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("marketplace errors preserve safe server messages", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { code: "attachments_not_allowed", message: "带附件的 Skill 不允许上传" },
  }), { status: 422, headers: { "content-type": "application/json" } });
  try {
    await assert.rejects(
      publishMarketplaceSkill({
        skill_id: "with-assets",
        license: "MIT",
        rights_confirmed: true,
      }),
      (error: unknown) => error instanceof MarketplaceApiError
        && error.code === "attachments_not_allowed"
        && error.message === "带附件的 Skill 不允许上传",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("generic publishing maps editable metadata into the local API contract", async () => {
  const originalFetch = globalThis.fetch;
  let requestBody: Record<string, unknown> | null = null;
  globalThis.fetch = async (_input, init) => {
    requestBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return new Response(JSON.stringify({ status: "pending_review" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    await publishMarketplaceSkill({
      skill_id: "writing-helper",
      resource_type: "skill",
      license: "MIT",
      rights_confirmed: true,
      terms_confirmed: true,
      terms_version: "2026-09-03",
      display_name: "写作助手",
      author_name: "北辰",
      summary: "公开简介",
      usage_guide: "使用说明",
      functional_category: "novel",
      primary_locale: "zh-CN",
      tags_csv: "writing, release",
      release_notes: "首版",
    });
    assert.deepEqual(requestBody, {
      skill_id: "writing-helper",
      resource_type: "skill",
      license: "MIT",
      rights_confirmed: true,
      terms_confirmed: true,
      terms_version: "2026-09-03",
      metadata: {
        display_name: "写作助手",
        author_name: "北辰",
        summary: "公开简介",
      usage_guide: "使用说明",
        functional_category: "novel",
        primary_locale: "zh-CN",
        tags: ["writing", "release"],
        release_notes: "首版",
      },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("owner submissions use the authenticated local contract and drop invalid rows", async () => {
  const originalFetch = globalThis.fetch;
  const requested: string[] = [];
  globalThis.fetch = async (input) => {
    requested.push(String(input));
    return new Response(JSON.stringify({
      items: [
        {
          id: "11111111-1111-4111-8111-111111111111",
          slug: "shared-skill",
          name: "shared-skill",
          summary: "Helpful",
          version: "1.2.3",
          sha256: "a".repeat(64),
          size_bytes: 12,
          license: "MIT",
          status: "rejected",
          resource_status: "rejected",
          is_current: false,
          review_reason: "缺少来源说明",
          submitted_at: "2026-08-31T00:00:00Z",
          reviewed_at: "2026-08-31T01:00:00Z",
        },
        {
          id: "bad",
          slug: "ignored",
          status: "pending_review",
          resource_status: "pending_review",
        },
      ],
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const items = await fetchMySubmissions();
    assert.equal(requested[0], "/api/resource-marketplace/submissions");
    assert.equal(items.length, 1);
    assert.equal(items[0].id, "11111111-1111-4111-8111-111111111111");
    assert.equal(items[0].status, "rejected");
    assert.equal(items[0].review_reason, "缺少来源说明");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("withdraw and resume use fixed local lifecycle routes", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({ url: String(input), init });
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    await withdrawMarketplaceSubmission("11111111-1111-4111-8111-111111111111");
    await resumeMarketplaceSkill({
      slug: "shared-skill",
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      reason: "复核后恢复",
    });
    assert.equal(
      requests[0].url,
      "/api/resource-marketplace/submissions/11111111-1111-4111-8111-111111111111/withdraw",
    );
    assert.equal(requests[0].init?.method, "POST");
    assert.equal(requests[1].url, "/api/resource-marketplace/skills/shared-skill/resume");
    assert.deepEqual(JSON.parse(String(requests[1].init?.body)), {
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      reason: "复核后恢复",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("catalog details keep local installation state from Core", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    slug: "writing-helper",
    display_name: "Writing Helper",
    summary: "Useful guidance",
      usage_guide: "作者提供的使用说明",
    version: "1.0.0",
    version_id: "11111111-1111-4111-8111-111111111111",
    sha256: "a".repeat(64),
    installation: { status: "conflict", version: "0.9.0", enabled: true },
  }), { status: 200, headers: { "content-type": "application/json" } });
  try {
    const skill = await fetchMarketplaceSkill("writing-helper");
    assert.deepEqual(skill.installation, { status: "conflict", version: "0.9.0", enabled: true });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("install sends the pinned version digest and keeps installation on success", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({ url: String(input), init });
    return new Response(JSON.stringify({
      installed: true,
      skill_id: "writing-helper",
      version: "1.0.0",
      sha256: "a".repeat(64),
      enabled: true,
      installation: { status: "installed", version: "1.0.0", enabled: true },
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await installMarketplaceSkill("writing-helper", {
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    });
    assert.equal(requests[0].url, "/api/resource-marketplace/skills/writing-helper/install");
    assert.equal(requests[0].init?.method, "POST");
    assert.deepEqual(JSON.parse(String(requests[0].init?.body)), {
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    });
    assert.equal(result.installed, true);
    assert.equal(result.enabled, true);
    assert.deepEqual(result.installation, { status: "installed", version: "1.0.0", enabled: true });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("install does not treat a download receipt as success", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    downloaded: true,
    skill_id: "writing-helper",
    enabled: true,
  }), { status: 200, headers: { "content-type": "application/json" } });
  try {
    await assert.rejects(
      installMarketplaceSkill("writing-helper", {
        expected_version_id: "11111111-1111-4111-8111-111111111111",
        expected_sha256: "a".repeat(64),
      }),
      (error: unknown) => error instanceof MarketplaceApiError && error.code === "invalid_response",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("catalog page uses the local pagination contract and keeps installation state", async () => {
  const originalFetch = globalThis.fetch;
  const requested: string[] = [];
  globalThis.fetch = async (input) => {
    requested.push(String(input));
    return new Response(JSON.stringify({
      items: [{
        slug: "writing-helper",
        skill_name: "writing-helper",
        summary: "Useful guidance",
      usage_guide: "作者提供的使用说明",
        version: "1.0.0",
        installation: { status: "installed", version: "1.0.0", enabled: false },
      }],
      total: 40,
      page: 2,
      page_size: 24,
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const page = await fetchMarketplaceSkillPage({
      query: "writing",
      category: "novel",
      sort: "popular",
      page: 2,
      page_size: 24,
      favorites: true,
    });
    assert.equal(
      requested[0],
      "/api/resource-marketplace/catalog/skills?q=writing&category=novel&sort=popular&page=2&page_size=24&favorites=true",
    );
    assert.equal(page.total, 40);
    assert.equal(page.page, 2);
    assert.equal(page.items[0].installation?.status, "installed");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("preview sends install pins and returns only confirmed body fields", async () => {
  const originalFetch = globalThis.fetch;
  const requested: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requested.push({ url: String(input), init });
    return new Response(JSON.stringify({
      content: "# Instructions",
      version_id: "11111111-1111-4111-8111-111111111111",
      sha256: "a".repeat(64),
      path: "/secret",
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const preview = await previewMarketplaceSkill("writing-helper", {
      expected_version_id: "11111111-1111-4111-8111-111111111111",
      expected_sha256: "a".repeat(64),
    });
    assert.equal(
      requested[0].url,
      `/api/resource-marketplace/skills/writing-helper/preview?expected_version_id=11111111-1111-4111-8111-111111111111&expected_sha256=${"a".repeat(64)}`,
    );
    assert.deepEqual(preview, {
      content: "# Instructions",
      version_id: "11111111-1111-4111-8111-111111111111",
      sha256: "a".repeat(64),
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("openInstalled resolves the local slug without navigating before the host generation check", async () => {
  const originalFetch = globalThis.fetch;
  const requested: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requested.push({ url: String(input), init });
    return new Response(JSON.stringify({
      opened: true,
      skill_id: "writing-helper",
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const result = await openInstalledMarketplaceSkill("writing-helper");
    assert.equal(requested[0].url, "/api/resource-marketplace/skills/writing-helper/open-installed");
    assert.equal(requested[0].init?.method, "POST");
    assert.deepEqual(result, { opened: true, skill_id: "writing-helper" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("navigateToCoreSkill opens the Skills tab with the trusted skill id", () => {
  const urls: string[] = [];
  const events: string[] = [];
  navigateToCoreSkill("writing-helper", {
    pathname: "/",
    search: "?tab=marketplace",
    hash: "",
    historyState: null,
    pushState: (_state, _unused, url) => {
      urls.push(url);
    },
    dispatchEvent: (event) => {
      events.push(event.type);
      return true;
    },
  });
  const params = new URLSearchParams(urls[0]?.slice(urls[0].indexOf("?")) ?? "");
  assert.equal(params.get("tab"), "skills");
  assert.equal(params.get("skill"), "writing-helper");
  assert.deepEqual(events, ["popstate"]);
});

test("pinned publish sends expected_sha256 and old payloads omit it", async () => {
  const originalFetch = globalThis.fetch;
  const bodies: Record<string, unknown>[] = [];
  globalThis.fetch = async (_input, init) => {
    bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
    return new Response(JSON.stringify({ status: "pending_review" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    await publishMarketplaceSkill({
      skill_id: "writing-helper",
      resource_type: "skill",
      license: "MIT",
      rights_confirmed: true,
      terms_confirmed: true,
      terms_version: "2026-09-03",
      display_name: "写作助手",
      author_name: "北辰",
      summary: "公开简介",
      usage_guide: "使用说明",
      functional_category: "novel",
      primary_locale: "zh-CN",
      tags_csv: "writing",
      release_notes: "首版",
      expected_sha256: "a".repeat(64),
    });
    await publishMarketplaceSkill({
      skill_id: "writing-helper",
      resource_type: "skill",
      license: "MIT",
      rights_confirmed: true,
      terms_confirmed: true,
      terms_version: "2026-09-03",
      display_name: "写作助手",
      author_name: "北辰",
      summary: "公开简介",
      usage_guide: "使用说明",
      functional_category: "novel",
      primary_locale: "zh-CN",
      tags_csv: "writing",
      release_notes: "首版",
    });
    assert.equal(bodies[0]?.expected_sha256, "a".repeat(64));
    assert.equal("expected_sha256" in bodies[1], false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("author feedback and local draft adapters use the stage 3 local contract", async () => {
  const originalFetch = globalThis.fetch;
  const requested: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requested.push({ url: String(input), init });
    const url = String(input);
    if (url.includes("/author/resources?")) {
      return new Response(JSON.stringify({
        items: [{
          slug: "writing-helper",
          latest: {
            id: "11111111-1111-4111-8111-111111111111",
            slug: "writing-helper",
            status: "pending_review",
            resource_status: "pending_review",
          },
          current: null,
          candidate: {
            id: "11111111-1111-4111-8111-111111111111",
            slug: "writing-helper",
            status: "pending_review",
            resource_status: "pending_review",
          },
        }],
        total: 1,
        page: 1,
        page_size: 20,
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/feedback?")) {
      return new Response(JSON.stringify({
        items: [{
          id: "submission:11111111-1111-4111-8111-111111111111",
          kind: "submission",
          resource_slug: "writing-helper",
          resource_name: "写作助手",
          version: "1.2.3",
          status: "rejected",
          message: "缺少来源说明",
          updated_at: "2026-08-31T01:00:00Z",
          unread: true,
        }],
        total: 1,
        page: 1,
        page_size: 20,
        unread_total: 3,
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.endsWith("/feedback/read")) {
      return new Response(JSON.stringify({
        id: "submission:11111111-1111-4111-8111-111111111111",
        updated_at: "2026-08-31T01:00:00Z",
        unread: false,
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/publish-drafts/") && init?.method === "PUT") {
      return new Response(JSON.stringify({
        draft: {
          schema_version: 1,
          skill_id: "writing-helper",
          base_version: "1.2.3",
          base_sha256: "a".repeat(64),
          fields: {
            license: "MIT",
            display_name: "写作助手",
            author_name: "北辰",
            summary: "",
            functional_category: "novel",
            primary_locale: "zh-CN",
            tags_csv: "writing",
            release_notes: "",
          },
          revision: 1,
          updated_at: "2026-09-05T00:00:00Z",
        },
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/publish-drafts/") && init?.method === "DELETE") {
      return new Response(JSON.stringify({ deleted: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.includes("/publish-drafts/")) {
      return new Response(JSON.stringify({ draft: null }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.includes("/local-skills/")) {
      return new Response(JSON.stringify({
        content: "# Skill",
        sha256: "a".repeat(64),
        version: "1.2.3",
        skill_id: "writing-helper",
        path: "/secret",
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({}), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const resources = await listAuthorResources({ query: "writing", status: "pending" });
    assert.equal(resources.items[0].slug, "writing-helper");
    assert.equal(resources.items[0].current, null);
    assert.match(requested[0].url, /\/author\/resources\?q=writing&status=pending/);
    const feedback = await listFeedback({ unread_only: true });
    assert.equal(feedback.unread_total, 3);
    assert.equal(feedback.items[0].kind, "submission");
    const read = await markFeedbackRead({
      id: "submission:11111111-1111-4111-8111-111111111111",
      expected_updated_at: "2026-08-31T01:00:00Z",
    });
    assert.equal(read.unread, false);
    assert.deepEqual(await getPublishDraft("writing-helper"), { draft: null });
    const saved = await savePublishDraft({
      skill_id: "writing-helper",
      expected_revision: null,
      base_version: "1.2.3",
      base_sha256: "a".repeat(64),
      fields: {
        license: "MIT",
        display_name: "写作助手",
        author_name: "北辰",
        summary: "",
        functional_category: "novel",
        primary_locale: "zh-CN",
        tags_csv: "writing",
        release_notes: "",
      },
    });
    assert.equal(saved.draft.revision, 1);
    assert.deepEqual(await deletePublishDraft({ skill_id: "writing-helper", expected_revision: 1 }), {
      deleted: true,
    });
    const preview = await previewLocalSkill("writing-helper");
    assert.deepEqual(preview, {
      content: "# Skill",
      sha256: "a".repeat(64),
      version: "1.2.3",
      skill_id: "writing-helper",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("install preserves version_changed without treating it as a generic failure", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { code: "version_changed", message: "资源版本已变化，请刷新详情后重新确认安装" },
  }), { status: 409, headers: { "content-type": "application/json" } });
  try {
    await assert.rejects(
      installMarketplaceSkill("writing-helper", {
        expected_version_id: "11111111-1111-4111-8111-111111111111",
        expected_sha256: "a".repeat(64),
      }),
      (error: unknown) => error instanceof MarketplaceApiError
        && error.code === "version_changed"
        && error.message.includes("刷新详情"),
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

const REVIEW_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

test("own review normalizer keeps id visibility and moderation reason", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    slug: "writing-helper",
    viewer: {
      favorited: false,
      review: {
        id: REVIEW_ID,
        rating: 4,
        body: "实际使用正常",
        updated_at: "2026-08-31T01:00:00Z",
        visibility: "hidden",
        moderation_reason: "请补充使用说明",
        account_id: "acct_hidden",
      },
    },
  }), { status: 200, headers: { "content-type": "application/json" } });
  try {
    const skill = await fetchMarketplaceSkill("writing-helper");
    assert.deepEqual(skill.viewer?.review, {
      id: REVIEW_ID,
      rating: 4,
      body: "实际使用正常",
      updated_at: "2026-08-31T01:00:00Z",
      visibility: "hidden",
      moderation_reason: "请补充使用说明",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("review page delete and report use local contracts and drop private fields", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({ url: String(input), init });
    if (String(input).includes("/reviews/page")) {
      return new Response(JSON.stringify({
        items: [{
          id: REVIEW_ID,
          author_label: "社区成员 abc",
          rating: 5,
          body: "Useful",
          created_at: "2026-08-31T00:00:00Z",
          updated_at: "2026-08-31T01:00:00Z",
          account_id: "acct_hidden",
          visibility: "hidden",
          moderation_reason: "内部原因",
        }],
        total: 1,
        page: 2,
        page_size: 10,
      }), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (String(input).endsWith("/review") && init?.method === "DELETE") {
      return new Response(JSON.stringify({ deleted: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (String(input).includes("/report")) {
      return new Response(JSON.stringify({ reported: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(JSON.stringify({
      id: REVIEW_ID,
      rating: 4,
      body: "实际使用正常",
      updated_at: "2026-08-31T01:00:00Z",
      visibility: "visible",
      moderation_reason: null,
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const page = await fetchCommunityReviewPage("writing-helper", { page: 2, page_size: 10 });
    assert.equal(
      requests[0].url,
      "/api/resource-marketplace/skills/writing-helper/reviews/page?page=2&page_size=10",
    );
    assert.deepEqual(page.items[0], {
      id: REVIEW_ID,
      author_label: "社区成员 abc",
      rating: 5,
      body: "Useful",
      created_at: "2026-08-31T00:00:00Z",
      updated_at: "2026-08-31T01:00:00Z",
    });
    assert.equal(await saveMarketplaceReview("writing-helper", 4, "实际使用正常").then((row) => row.id), REVIEW_ID);
    assert.deepEqual(
      await deleteMarketplaceReview("writing-helper", REVIEW_ID, "2026-08-31T01:00:00Z"),
      { deleted: true },
    );
    assert.deepEqual(
      await reportMarketplaceReview("writing-helper", REVIEW_ID, "2026-08-31T01:00:00Z", "spam", "重复广告"),
      { reported: true },
    );
    assert.equal(requests[2].init?.method, "DELETE");
    assert.deepEqual(JSON.parse(String(requests[2].init?.body)), {
      review_id: REVIEW_ID,
      expected_updated_at: "2026-08-31T01:00:00Z",
    });
    assert.equal(
      requests[3].url,
      `/api/resource-marketplace/skills/writing-helper/reviews/${REVIEW_ID}/report`,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("marketplace errors keep retry_after_seconds from body and header", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: {
      code: "rate_limited",
      message: "评价提交过于频繁，请稍后重试",
      retry_after_seconds: 42,
    },
  }), { status: 429, headers: { "content-type": "application/json", "Retry-After": "42" } });
  try {
    await assert.rejects(
      saveMarketplaceReview("writing-helper", 5, "很好"),
      (error: unknown) => error instanceof MarketplaceApiError
        && error.code === "rate_limited"
        && error.retry_after_seconds === 42
        && error.message === "评价提交过于频繁，请稍后重试",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
