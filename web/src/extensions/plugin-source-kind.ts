export type PluginSourceKind = "official" | "community" | "custom";

export function isOfficialPluginSource(kind: PluginSourceKind | undefined): boolean {
  return kind === "official";
}

export function requiresPluginInstallRiskConfirmation(
  kind: PluginSourceKind | undefined,
): boolean {
  return !isOfficialPluginSource(kind);
}

export function pluginSourceKindLabel(
  kind: PluginSourceKind | undefined,
  variant: "short" | "builtin" = "short",
): string {
  if (kind === "official") {
    return variant === "builtin" ? "内置官方" : "官方";
  }
  if (kind === "community") {
    return variant === "builtin" ? "内置社区" : "社区";
  }
  return "第三方";
}

export function pluginInstallRiskCopy(kind: PluginSourceKind | undefined): {
  title: string;
  description: string;
} {
  if (kind === "community") {
    return {
      title: "安装社区插件？",
      description: "该插件来自社区仓库，与 DeterminFlow 主进程以相同权限运行，可以访问本机资源。平台不提供沙箱隔离。安装风险由你承担。",
    };
  }
  return {
    title: "安装第三方插件？",
    description: "该插件来自你添加的仓库，与 DeterminFlow 主进程以相同权限运行，可以访问本机资源。平台不提供沙箱隔离。安装风险由你承担。",
  };
}
