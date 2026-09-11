import assert from "node:assert/strict";
import test from "node:test";

import {
  catalogFromRepositorySources,
  isPluginSourceCatalogReady,
  mergePluginCatalog,
  pluginRepositoryCountLabel,
} from "./plugin-catalog-state.ts";
import type {
  PluginCatalogEntry,
  PluginCatalogResponse,
  PluginCatalogSource,
  PluginRepositorySource,
} from "./plugin-types.ts";

const official: PluginRepositorySource = {
  id: "determinflow-official",
  name: "DeterminFlow 官方插件",
  url: "https://github.com/alikon-art/DeterminFlow-Plugins.git",
  ref: "main",
  kind: "official",
  builtin: true,
  mirrors: [],
  registry: null,
};

function catalogSource(
  overrides: Partial<PluginCatalogSource> = {},
): PluginCatalogSource {
  return {
    ...official,
    resolved_commit: "e69aa37b",
    plugin_count: 2,
    error: "",
    selected_url: official.url,
    transport: "git",
    ...overrides,
  };
}

function catalogEntry(): PluginCatalogEntry {
  return {
    id: "public-api",
    name: "Public API",
    version: "0.1.0",
    description: "",
    source_id: official.id,
    source_name: official.name,
    source: official.url,
    source_kind: "official",
    ref: "main",
    resolved_commit: "e69aa37b",
    subdirectory: "plugins/public-api",
  };
}

test("seeds catalog rows from persisted repository sources", () => {
  const seeded = catalogFromRepositorySources([official]);
  assert.equal(seeded.sources.length, 1);
  assert.equal(seeded.sources[0]?.id, official.id);
  assert.equal(seeded.plugins.length, 0);
  assert.equal(seeded.refreshing, true);
  assert.equal(isPluginSourceCatalogReady(seeded.sources[0]!), false);
});

test("keeps known repositories when a concurrent refresh returns an empty placeholder", () => {
  const current: PluginCatalogResponse = {
    sources: [catalogSource()],
    plugins: [catalogEntry()],
  };
  const merged = mergePluginCatalog(current, {
    sources: [],
    plugins: [],
    refreshing: true,
  });
  assert.equal(merged.sources.length, 1);
  assert.equal(merged.plugins.length, 1);
  assert.equal(merged.refreshing, true);
});

test("does not replace a finished catalog with a pending source-only snapshot", () => {
  const current: PluginCatalogResponse = {
    sources: [catalogSource()],
    plugins: [catalogEntry()],
  };
  const merged = mergePluginCatalog(current, {
    ...catalogFromRepositorySources([official]),
    refreshing: true,
  });
  assert.equal(merged.plugins.length, 1);
  assert.equal(merged.sources[0]?.resolved_commit, "e69aa37b");
  assert.equal(merged.refreshing, true);
});

test("accepts a finished catalog after a seeded placeholder", () => {
  const incoming: PluginCatalogResponse = {
    sources: [catalogSource()],
    plugins: [catalogEntry()],
  };
  const merged = mergePluginCatalog(catalogFromRepositorySources([official]), incoming);
  assert.deepEqual(merged, incoming);
});

test("omits the repository count until the persisted list is known", () => {
  assert.equal(pluginRepositoryCountLabel(0, false), "");
  assert.equal(pluginRepositoryCountLabel(0, true), "0");
  assert.equal(pluginRepositoryCountLabel(2, true), "2");
});
