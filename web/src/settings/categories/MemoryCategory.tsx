import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { MemoryJobsStatus } from "./MemoryJobsStatus";
import { fetchMemorySettings, updateMemorySettings } from "../api";
import { cloneJson, valuesEqual } from "../field-model";
import { memoryFieldGroups } from "../memory-fields";
import {
  describeMemoryEnableGate,
  memoryActivationCopy,
} from "../memory-model";
import { isPluginAuthError, parseApiError } from "../parse-api-error";
import { useSettingsPlugins } from "../plugins-context";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import { SettingsFieldGroups } from "../SettingsFieldGroups";
import { useRegisterSettingsStore, useSettingsWorkspace } from "../SettingsWorkspace";
import type { MemorySettings, MemorySettingsResponse, SettingsFieldGroup, SettingsSection } from "../types";

export function MemoryCategory({ section }: { section: SettingsSection }) {
  const plugins = useSettingsPlugins();
  const { adminToken, setRevealAdminToken } = useSettingsWorkspace();
  const [snapshot, setSnapshot] = useState<MemorySettingsResponse | null>(null);
  const [draft, setDraft] = useState<MemorySettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const draftRef = useRef<MemorySettings | null>(null);
  draftRef.current = draft;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const loaded = await fetchMemorySettings();
      setSnapshot(loaded);
      setDraft(cloneJson(loaded.settings));
    } catch (loadError) {
      setError(parseApiError(loadError, "无法加载记忆配置"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = useCallback(async () => {
    const captured = draftRef.current;
    if (!captured) return;
    try {
      const saved = await updateMemorySettings(captured, adminToken);
      setSnapshot(saved);
      setDraft((current) => current && !valuesEqual(current, captured) ? current : cloneJson(saved.settings));
    } catch (saveError) {
      if (isPluginAuthError(saveError)) setRevealAdminToken(true);
      throw saveError;
    }
  }, [adminToken, setRevealAdminToken]);

  const discard = useCallback(() => {
    if (snapshot) setDraft(cloneJson(snapshot.settings));
  }, [snapshot]);

  useRegisterSettingsStore({
    id: section.id,
    title: section.title,
    dirty: Boolean(snapshot && draft && !valuesEqual(snapshot.settings, draft)),
    requiresAdminToken: true,
    save,
    discard,
  });

  const groups = useMemo<SettingsFieldGroup[]>(() => {
    const next = memoryFieldGroups(snapshot?.schema);
    const providerField = next.flatMap((group) => group.fields).find((field) => field.id === "provider_id");
    if (providerField) {
      providerField.kind = "select";
      providerField.options = (snapshot?.providers || []).map((provider) => ({
        value: provider.id,
        label: provider.name || provider.id,
      }));
    }
    return next;
  }, [snapshot]);

  const gate = draft && snapshot
    ? describeMemoryEnableGate({
      settings: draft,
      providers: snapshot.providers,
      plugins: plugins.plugins,
    })
    : null;
  const selectedPlugin = plugins.plugins.find((plugin) => plugin.id === draft?.provider_id);
  const enableGate = draft && snapshot ? describeMemoryEnableGate({
    settings: { ...draft, enabled: true, external_enabled: true },
    providers: snapshot.providers,
    plugins: plugins.plugins,
  }) : null;
  const activation = snapshot
    ? memoryActivationCopy({
      effectiveEnabled: snapshot.effective_enabled,
      reason: snapshot.reason,
      plugin: selectedPlugin,
    })
    : null;

  return (
    <SettingsCategoryPanel
      sectionId={section.id}
      title={section.title}
      description={section.description}
      loading={loading}
      loadError={error}
      onRetry={() => void load()}
    >
      {draft && snapshot && activation ? (
        <div className="flex flex-col gap-6">
          <div className="rounded-lg border border-border bg-card px-4 py-3">
            <p className="text-sm font-medium text-foreground">{activation.label}</p>
            {activation.detail ? (
              <p className="mt-1 text-xs text-muted-foreground">{activation.detail}</p>
            ) : null}
            {(gate?.blocked || enableGate?.blocked) ? (
              <p className="mt-2 text-sm text-warning" role="status">{gate?.reason || enableGate?.reason}</p>
            ) : null}
          </div>
          {snapshot.providers.length > 0 ? (
            <ul className="flex flex-col gap-2">
              {snapshot.providers.map((provider) => (
                <li key={provider.id} className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2">
                  <div>
                    <p className="text-sm text-foreground">{provider.name}</p>
                    <p className="mt-0.5 font-mono text-xs text-muted-foreground">{provider.id}</p>
                  </div>
                  <p className={provider.healthy ? "text-xs text-success" : "text-xs text-destructive"}>
                    {provider.healthy ? "健康" : provider.reason || provider.status}
                  </p>
                </li>
              ))}
            </ul>
          ) : null}
          <MemoryJobsStatus enabled={snapshot.effective_enabled && snapshot.settings.auto_consolidate_enabled} />
          <SettingsFieldGroups
            groups={groups}
            isFieldDisabled={(id) => Boolean(enableGate?.blocked && (
              (id === "external_enabled" && !draft.external_enabled)
              || (id === "enabled" && !draft.enabled && draft.external_enabled)
            ))}
            values={draft as unknown as Record<string, unknown>}
            onChange={(fieldId, value) => setDraft((current) => (
              current ? { ...current, [fieldId]: value } as MemorySettings : current
            ))}
          />
        </div>
      ) : null}
    </SettingsCategoryPanel>
  );
}
