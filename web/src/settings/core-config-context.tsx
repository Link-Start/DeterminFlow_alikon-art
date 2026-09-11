import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { fetchConfig, updateConfig } from "../lib/api";
import { notifySettingsUpdated } from "../lib/navigation-settings";
import type { ConfigItemMeta } from "../types";
import { editedKeysForGroup, reconcileEditedAfterSave, updateEditedValue } from "./field-model";
import { parseApiError } from "./parse-api-error";
import type { SettingsScalar } from "./types";

interface CoreConfigContextValue {
  config: Record<string, SettingsScalar>;
  meta: ConfigItemMeta[];
  edited: Record<string, SettingsScalar>;
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  setValue: (key: string, value: SettingsScalar) => void;
  displayValue: (key: string) => SettingsScalar;
  groupDirty: (group: string) => boolean;
  saveGroup: (group: string) => Promise<void>;
  discardGroup: (group: string) => void;
}

const CoreConfigContext = createContext<CoreConfigContextValue | null>(null);

export function CoreConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Record<string, SettingsScalar>>({});
  const [meta, setMeta] = useState<ConfigItemMeta[]>([]);
  const [edited, setEdited] = useState<Record<string, SettingsScalar>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inFlightKeys = useRef(new Set<string>());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchConfig();
      setConfig(data.config);
      setMeta(data.meta);
      setEdited({});
    } catch (loadError) {
      setError(parseApiError(loadError, "加载配置失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setValue = useCallback((key: string, value: SettingsScalar) => {
    setEdited((current) => {
      return updateEditedValue(current, config, key, value, inFlightKeys.current);
    });
  }, [config]);

  const displayValue = useCallback((key: string) => (
    key in edited ? edited[key] : config[key]
  ), [config, edited]);

  const groupDirty = useCallback((group: string) => (
    editedKeysForGroup(edited, meta, group).length > 0
  ), [edited, meta]);

  const saveGroup = useCallback(async (group: string) => {
    const savedKeys = editedKeysForGroup(edited, meta, group);
    if (savedKeys.length === 0) return;
    const captured = Object.fromEntries(savedKeys.map((key) => [key, edited[key]]));
    savedKeys.forEach((key) => inFlightKeys.current.add(key));
    try {
      const data = await updateConfig(captured, true);
      if (!data.success) throw new Error("保存失败");
      setConfig(data.config);
      setEdited((current) => reconcileEditedAfterSave({
        edited: current,
        captured,
        nextConfig: data.config,
        savedKeys,
      }));
      notifySettingsUpdated();
    } finally {
      savedKeys.forEach((key) => inFlightKeys.current.delete(key));
    }
  }, [edited, meta]);

  const discardGroup = useCallback((group: string) => {
    setEdited((current) => {
      const next = { ...current };
      for (const key of editedKeysForGroup(current, meta, group)) delete next[key];
      return next;
    });
  }, [meta]);

  const value = useMemo<CoreConfigContextValue>(() => ({
    config,
    meta,
    edited,
    loading,
    error,
    load,
    setValue,
    displayValue,
    groupDirty,
    saveGroup,
    discardGroup,
  }), [
    config,
    discardGroup,
    displayValue,
    edited,
    error,
    groupDirty,
    load,
    loading,
    meta,
    saveGroup,
    setValue,
  ]);

  return (
    <CoreConfigContext.Provider value={value}>
      {children}
    </CoreConfigContext.Provider>
  );
}

export function useCoreConfig(): CoreConfigContextValue {
  const value = useContext(CoreConfigContext);
  if (!value) throw new Error("useCoreConfig requires CoreConfigProvider");
  return value;
}
