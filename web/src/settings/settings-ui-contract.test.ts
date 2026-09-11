import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..");

function readSrc(...parts: string[]): string {
  return readFileSync(join(srcRoot, ...parts), "utf8");
}

test("settings page uses a sticky unified save toolbar and a category registry", () => {
  const page = readSrc("settings", "SettingsPage.tsx");
  const toolbar = readSrc("settings", "SettingsToolbar.tsx");
  const registry = readSrc("settings", "registry.tsx");

  assert.match(toolbar, /sticky top-0/);
  assert.match(toolbar, /bg-background/);
  assert.equal(toolbar.includes("backdrop-blur"), false);
  assert.match(page, /SettingsToolbar/);
  assert.match(page, /max-w-4xl/);
  assert.doesNotMatch(page, /SettingsNav|md:flex-row|hidden=|aria-hidden=/);
  assert.match(page, /SettingsSectionTargetContext.Provider/);
  assert.match(toolbar, /<h1[^>]*>系统配置<\/h1>/);
  assert.match(page, /renderSettingsCategory/);
  assert.match(registry, /PluginCategory/);
  assert.match(registry, /MemoryCategory/);
  assert.match(registry, /CompressionCategory/);
  assert.equal(registry.toLowerCase().includes("hindsight"), false);
});

test("plugin drawer deep-links into settings instead of embedding a config form", () => {
  const details = readSrc("components", "extensions", "PluginDetails.tsx");
  assert.equal(details.includes("PluginConfigForm"), false);
  assert.match(details, /tab: "settings"/);
  assert.match(details, /section:/);
  assert.match(details, /在配置中编辑/);
});

test("category save bars are not duplicated in compression, models, or plugin editors", () => {
  const compression = readSrc("settings", "categories", "CompressionCategory.tsx");
  const models = readSrc("components", "ModelProviderCard.tsx");
  const plugin = readSrc("settings", "categories", "PluginCategory.tsx");
  const settingsDir = readSrc("settings", "SettingsPage.tsx");

  assert.equal(compression.includes("保存配置"), false);
  assert.equal(models.includes("保存供应商配置"), false);
  assert.match(plugin, /savePluginConfig/);
  assert.match(plugin, /adminToken/);
  assert.match(settingsDir, /CoreConfigProvider/);
});

test("settings module stays provider-neutral", () => {
  const files = [
    readSrc("settings", "memory-model.ts"),
    readSrc("settings", "memory-fields.ts"),
    readSrc("settings", "registry.tsx"),
    readSrc("settings", "categories", "MemoryCategory.tsx"),
    readSrc("settings", "categories", "PluginCategory.tsx"),
  ].join("\n").toLowerCase();
  assert.equal(files.includes("hindsight"), false);
});


test("card layout retains mounted drafts and deep links reveal the target", () => {
  const panel = readSrc("settings", "SettingsCategoryPanel.tsx");
  const desktop = readSrc("settings", "categories", "DesktopCategory.tsx");
  assert.match(panel, /aria-expanded=\{expanded\}/);
  assert.match(panel, /aria-controls=\{contentId\}/);
  assert.match(panel, /hidden=\{!expanded\}/);
  assert.doesNotMatch(panel, /expanded && children|expanded \? children/);
  assert.match(panel, /targetId !== sectionId/);
  assert.match(panel, /scrollIntoView/);
  assert.match(panel, /if \(saveError \|\| loadError\) setExpanded\(true\)/);
  assert.match(desktop, /if \(!enabled\) return null/);
});


test("all configuration forms share the same field list surfaces", () => {
  const fields = readSrc("settings", "SettingsFieldControl.tsx");
  const list = fields.slice(fields.indexOf("export function SettingsFieldList"), fields.indexOf("export function SettingsFieldRow"));
  assert.doesNotMatch(list, /overflow-hidden|overflow-clip/, "Field lists must not clip inline select menus or focus rings");
  for (const path of [
    ["settings", "categories", "CoreConfigCategory.tsx"],
    ["settings", "SettingsFieldGroups.tsx"],
    ["settings", "PluginSettingsFields.tsx"],
  ]) {
    assert.match(readSrc(...path), /<SettingsFieldList>/);
  }
});
