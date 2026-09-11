import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { PluginListResponse, PluginRecord } from "../extensions/plugin-types";
import { fetchPlugins } from "../lib/plugin-api";
import { parseApiError } from "./parse-api-error";

interface SettingsPluginsContextValue {
  plugins: PluginRecord[];
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  replacePlugin: (plugin: PluginRecord) => void;
}

const SettingsPluginsContext = createContext<SettingsPluginsContextValue | null>(null);

export function SettingsPluginsProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<PluginListResponse>({
    plugins: [],
    restart_required: false,
    package_management_read_only: false,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchPlugins());
    } catch (loadError) {
      setError(parseApiError(loadError, "加载插件失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const replacePlugin = useCallback((plugin: PluginRecord) => {
    setData((current) => ({
      ...current,
      plugins: current.plugins.map((item) => item.id === plugin.id ? plugin : item),
    }));
  }, []);

  const value = useMemo<SettingsPluginsContextValue>(() => ({
    plugins: data.plugins,
    loading,
    error,
    load,
    replacePlugin,
  }), [data.plugins, error, load, loading, replacePlugin]);

  return (
    <SettingsPluginsContext.Provider value={value}>
      {children}
    </SettingsPluginsContext.Provider>
  );
}

export function useSettingsPlugins(): SettingsPluginsContextValue {
  const value = useContext(SettingsPluginsContext);
  if (!value) throw new Error("useSettingsPlugins requires SettingsPluginsProvider");
  return value;
}
