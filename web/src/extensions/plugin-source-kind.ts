export type PluginSourceKind = "official" | "community" | "custom";

export function isOfficialPluginSource(kind: PluginSourceKind | undefined): boolean {
  return kind === "official";
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
