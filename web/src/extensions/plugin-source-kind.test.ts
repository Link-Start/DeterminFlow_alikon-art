import assert from "node:assert/strict";
import test from "node:test";

import {
  isOfficialPluginSource,
  pluginSourceKindLabel,
} from "./plugin-source-kind.ts";

test("only official sources skip third-party risk confirmation", () => {
  assert.equal(isOfficialPluginSource("official"), true);
  assert.equal(isOfficialPluginSource("community"), false);
  assert.equal(isOfficialPluginSource("custom"), false);
  assert.equal(isOfficialPluginSource(undefined), false);
});

test("source kind labels keep official and community distinct", () => {
  assert.equal(pluginSourceKindLabel("official"), "官方");
  assert.equal(pluginSourceKindLabel("community"), "社区");
  assert.equal(pluginSourceKindLabel("custom"), "第三方");
  assert.equal(pluginSourceKindLabel("official", "builtin"), "内置官方");
  assert.equal(pluginSourceKindLabel("community", "builtin"), "内置社区");
  assert.equal(pluginSourceKindLabel("custom", "builtin"), "第三方");
});
