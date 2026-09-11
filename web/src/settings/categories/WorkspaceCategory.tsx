import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "../../lib/http-client";
import { cloneJson, valuesEqual } from "../field-model";
import { isPluginAuthError, parseApiError } from "../parse-api-error";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import { SettingsFieldGroups } from "../SettingsFieldGroups";
import { useRegisterSettingsStore, useSettingsWorkspace } from "../SettingsWorkspace";
import { readWorkspaceSettings, workspaceFieldGroups, type WorkspaceSettings, type WorkspaceSettingsResponse } from "../workspace-model";
import type { SettingsSection } from "../types";

export function WorkspaceCategory({ section }: { section: SettingsSection }) {
  const { adminToken, setRevealAdminToken } = useSettingsWorkspace();
  const [snapshot, setSnapshot] = useState<WorkspaceSettingsResponse | null>(null);
  const [draft, setDraft] = useState<WorkspaceSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = readWorkspaceSettings(await request<unknown>("/workspace/settings"));
      setSnapshot(result);
      setDraft(cloneJson(result.settings));
    } catch (failure) {
      setError(parseApiError(failure, "无法加载工作区配置"));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const save = useCallback(async () => {
    const captured = draftRef.current;
    if (!captured) return;
    try {
      const result = readWorkspaceSettings(await request<unknown>("/workspace/settings", {
        method: "PUT", body: JSON.stringify({ settings: captured }),
        headers: adminToken.trim() ? { Authorization: `Bearer ${adminToken.trim()}` } : undefined,
      }));
      setSnapshot(result);
      setDraft((current) => current && !valuesEqual(current, captured) ? current : cloneJson(result.settings));
    } catch (failure) {
      if (isPluginAuthError(failure)) setRevealAdminToken(true);
      throw failure;
    }
  }, [adminToken, setRevealAdminToken]);
  const discard = useCallback(() => { if (snapshot) setDraft(cloneJson(snapshot.settings)); }, [snapshot]);
  useRegisterSettingsStore({ id: section.id, title: section.title, requiresAdminToken: true,
    dirty: Boolean(snapshot && draft && !valuesEqual(snapshot.settings, draft)), save, discard });
  const provider = snapshot?.providers.find((item) => item.id === draft?.provider_id);
  return (
    <SettingsCategoryPanel sectionId={section.id} title={section.title} loading={loading} loadError={error} onRetry={() => void load()}>
      {snapshot && draft ? <div className="flex flex-col gap-5">
        <p className="text-sm text-muted-foreground" role="status">
          {snapshot.effective_enabled ? "已启用" : snapshot.reason}
        </p>
        {!provider?.healthy && provider?.reason !== snapshot.reason ? <p className="text-sm text-warning" role="status">
          {provider?.reason || "安装并配置工作区插件后可启用。"}
        </p> : null}
        <SettingsFieldGroups groups={workspaceFieldGroups(snapshot)}
          values={draft as unknown as Record<string, unknown>}
          isFieldDisabled={(id) => id === "enabled" && !draft.enabled && !provider?.healthy}
          onChange={(id, value) => setDraft((current) => current ? { ...current, [id]: value } : current)} />
      </div> : null}
    </SettingsCategoryPanel>
  );
}
