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

import { dirtyStores, saveDirtyCategories, saveOutcomeCopy } from "./save-coordinator";
import type { CategorySaveResult, SettingsCategoryStore } from "./types";

interface SettingsWorkspaceValue {
  stores: SettingsCategoryStore[];
  upsert: (store: SettingsCategoryStore) => void;
  remove: (id: string) => void;
  adminToken: string;
  setAdminToken: (value: string) => void;
  revealAdminToken: boolean;
  setRevealAdminToken: (value: boolean) => void;
  dirty: boolean;
  saving: boolean;
  outcome: ReturnType<typeof saveOutcomeCopy>;
  categoryErrors: Record<string, string>;
  saveAll: () => Promise<CategorySaveResult[]>;
  discardAll: () => void;
}

const SettingsWorkspaceContext = createContext<SettingsWorkspaceValue | null>(null);

export function SettingsWorkspace({ children }: { children: ReactNode }) {
  const [storeMap, setStoreMap] = useState<Record<string, SettingsCategoryStore>>({});
  const [adminToken, setAdminToken] = useState("");
  const [revealAdminToken, setRevealAdminToken] = useState(false);
  const [saving, setSaving] = useState(false);
  const [results, setResults] = useState<CategorySaveResult[]>([]);
  const storesRef = useRef<SettingsCategoryStore[]>([]);
  const stores = useMemo(
    () => Object.values(storeMap).sort((left, right) => left.id.localeCompare(right.id)),
    [storeMap],
  );
  storesRef.current = stores;

  const upsert = useCallback((store: SettingsCategoryStore) => {
    setStoreMap((current) => ({ ...current, [store.id]: store }));
  }, []);

  const remove = useCallback((id: string) => {
    setStoreMap((current) => {
      if (!(id in current)) return current;
      const next = { ...current };
      delete next[id];
      return next;
    });
  }, []);

  const saveAll = useCallback(async () => {
    setSaving(true);
    try {
      const nextResults = await saveDirtyCategories(storesRef.current);
      setResults(nextResults);
      return nextResults;
    } finally {
      setSaving(false);
    }
  }, []);

  const discardAll = useCallback(() => {
    for (const store of dirtyStores(storesRef.current)) store.discard();
    setResults([]);
  }, []);

  const categoryErrors = useMemo(() => (
    Object.fromEntries(
      results.filter((result) => !result.ok && result.error).map((result) => [result.id, result.error || ""]),
    )
  ), [results]);

  const value = useMemo<SettingsWorkspaceValue>(() => ({
    stores,
    upsert,
    remove,
    adminToken,
    setAdminToken,
    revealAdminToken,
    setRevealAdminToken,
    dirty: stores.some((store) => store.dirty),
    saving,
    outcome: saveOutcomeCopy(results),
    categoryErrors,
    saveAll,
    discardAll,
  }), [
    adminToken,
    categoryErrors,
    discardAll,
    revealAdminToken,
    results,
    saveAll,
    saving,
    stores,
    upsert,
    remove,
  ]);

  return (
    <SettingsWorkspaceContext.Provider value={value}>
      {children}
    </SettingsWorkspaceContext.Provider>
  );
}

export function useSettingsWorkspace(): SettingsWorkspaceValue {
  const value = useContext(SettingsWorkspaceContext);
  if (!value) throw new Error("useSettingsWorkspace requires SettingsWorkspace");
  return value;
}

export function useRegisterSettingsStore(store: SettingsCategoryStore): void {
  const { upsert, remove } = useSettingsWorkspace();
  const saveRef = useRef(store.save);
  const discardRef = useRef(store.discard);
  saveRef.current = store.save;
  discardRef.current = store.discard;

  useEffect(() => {
    upsert({
      id: store.id,
      title: store.title,
      dirty: store.dirty,
      requiresAdminToken: store.requiresAdminToken,
      save: () => saveRef.current(),
      discard: () => discardRef.current(),
    });
  }, [store.id, store.title, store.dirty, store.requiresAdminToken, upsert]);

  useEffect(() => () => remove(store.id), [remove, store.id]);
}
