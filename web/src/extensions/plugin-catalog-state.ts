import type {
  PluginCatalogResponse,
  PluginCatalogSource,
  PluginRepositorySource,
} from "./plugin-types";

export function catalogFromRepositorySources(
  sources: PluginRepositorySource[],
): PluginCatalogResponse {
  return {
    sources: sources.map((source) => ({
      ...source,
      resolved_commit: "",
      plugin_count: 0,
      error: "",
      selected_url: "",
      transport: "",
    })),
    plugins: [],
    refreshing: true,
  };
}

export function mergePluginCatalog(
  current: PluginCatalogResponse,
  incoming: PluginCatalogResponse,
): PluginCatalogResponse {
  if (incoming.refreshing && incoming.sources.length === 0 && current.sources.length > 0) {
    return { ...current, refreshing: true };
  }
  if (incoming.refreshing && incoming.plugins.length === 0 && current.plugins.length > 0) {
    return { ...current, refreshing: true };
  }
  return incoming;
}

export function isPluginSourceCatalogReady(source: PluginCatalogSource): boolean {
  return Boolean(source.error || source.resolved_commit || source.transport);
}

export function pluginRepositoryCountLabel(
  sourceCount: number,
  sourceCountKnown: boolean,
): string {
  return sourceCountKnown ? String(sourceCount) : "";
}
