import assert from "node:assert/strict";
import test from "node:test";

import {
  isOfficialPluginSource,
  pluginInstallRiskCopy,
  pluginSourceKindLabel,
  requiresPluginInstallRiskConfirmation,
} from "./plugin-source-kind.ts";

test("only official sources skip third-party risk confirmation", () => {
  assert.equal(isOfficialPluginSource("official"), true);
  assert.equal(isOfficialPluginSource("community"), false);
  assert.equal(isOfficialPluginSource("custom"), false);
  assert.equal(isOfficialPluginSource(undefined), false);
  assert.equal(requiresPluginInstallRiskConfirmation("official"), false);
  assert.equal(requiresPluginInstallRiskConfirmation("community"), true);
  assert.equal(requiresPluginInstallRiskConfirmation("custom"), true);
});

test("community and custom installs use distinct risk dialog copy", () => {
  assert.deepEqual(pluginInstallRiskCopy("community"), {
    title: "安装社区插件？",
    description: "该插件来自社区仓库，与 DeterminFlow 主进程以相同权限运行，可以访问本机资源。平台不提供沙箱隔离。安装风险由你承担。",
  });
  assert.equal(pluginInstallRiskCopy("custom").title, "安装第三方插件？");
});

test("source kind labels keep official and community distinct", () => {
  assert.equal(pluginSourceKindLabel("official"), "官方");
  assert.equal(pluginSourceKindLabel("community"), "社区");
  assert.equal(pluginSourceKindLabel("custom"), "第三方");
  assert.equal(pluginSourceKindLabel("official", "builtin"), "内置官方");
  assert.equal(pluginSourceKindLabel("community", "builtin"), "内置社区");
  assert.equal(pluginSourceKindLabel("custom", "builtin"), "第三方");
});
