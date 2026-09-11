import assert from "node:assert/strict";
import test from "node:test";

import {
  CORE_FALLBACK_SECTIONS,
  isCoreSectionId,
  parsePluginSectionId,
  pluginSectionId,
  readSettingsSections,
  resolveSelectedSection,
  settingsDeepLink,
} from "./section-model.ts";

test("reads settings sections and ignores arbitrary component or url fields", () => {
  const sections = readSettingsSections({
    sections: [
      {
        id: "memory",
        title: "记忆",
        owner: "core",
        kind: "core",
        order: 80,
        description: "召回与整理",
        component: "EvilComponent",
        url: "https://evil.example/settings",
      },
      {
        id: "plugin:demo:settings",
        title: "Demo",
        owner: "demo",
        kind: "plugin",
        plugin_id: "demo",
        order: 90,
        description: "",
      },
      {
        id: "models",
        title: "模型",
        owner: "core",
        kind: "core",
        order: 30,
        description: "",
      },
    ],
  });

  assert.deepEqual(sections.map((section) => section.id), [
    "models",
    "memory",
    "plugin:demo:settings",
  ]);
  assert.equal("component" in sections[1], false);
  assert.equal("url" in sections[1], false);
  assert.equal(sections[2].plugin_id, "demo");
});

test("plugin descriptor identity does not collide with core ids", () => {
  const sections = readSettingsSections({
    sections: [
      {
        id: "memory",
        title: "记忆",
        owner: "core",
        kind: "core",
        order: 80,
        description: "",
      },
      {
        id: "plugin:memory-pack:memory",
        title: "插件记忆",
        owner: "memory-pack",
        kind: "plugin",
        plugin_id: "memory-pack",
        order: 90,
        description: "",
      },
    ],
  });

  assert.equal(sections[0].kind, "core");
  assert.equal(isCoreSectionId(sections[0].id), true);
  assert.equal(sections[1].kind, "plugin");
  assert.equal(isCoreSectionId(sections[1].id), false);
  assert.deepEqual(parsePluginSectionId(sections[1].id), {
    pluginId: "memory-pack",
    localId: "memory",
  });
});

test("resolves plugin deep links by exact id or unique plugin id", () => {
  const sections = readSettingsSections({
    sections: [
      ...CORE_FALLBACK_SECTIONS,
      {
        id: pluginSectionId("demo-plugin", "memory"),
        title: "Demo",
        owner: "demo-plugin",
        kind: "plugin",
        plugin_id: "demo-plugin",
        order: 90,
        description: "",
      },
    ],
  });

  assert.equal(
    resolveSelectedSection(sections, "plugin:demo-plugin:memory")?.id,
    "plugin:demo-plugin:memory",
  );
  assert.equal(
    resolveSelectedSection(sections, "plugin:demo-plugin:settings")?.id,
    "plugin:demo-plugin:memory",
  );
  assert.deepEqual(settingsDeepLink("plugin:demo-plugin:memory"), {
    tab: "settings",
    section: "plugin:demo-plugin:memory",
  });
});

test("drops plugin descriptors without plugin_id", () => {
  const sections = readSettingsSections({
    sections: [
      {
        id: "plugin:orphan:settings",
        title: "Orphan",
        owner: "orphan",
        kind: "plugin",
        order: 1,
        description: "",
      },
    ],
  });
  assert.deepEqual(sections, []);
});
