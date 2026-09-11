import { useCallback, useEffect, useRef, useState } from "react";

import { fetchCompressionConfig, updateCompressionConfig } from "../api";
import { COMPRESSION_FIELD_GROUPS, compressionValueAt, setCompressionValue } from "../compression-fields";
import { cloneJson, valuesEqual } from "../field-model";
import { parseApiError } from "../parse-api-error";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import { SettingsFieldGroups } from "../SettingsFieldGroups";
import { useRegisterSettingsStore } from "../SettingsWorkspace";
import type { CompressionConfig, SettingsSection } from "../types";

export function CompressionCategory({ section }: { section: SettingsSection }) {
  const [baseline, setBaseline] = useState<CompressionConfig | null>(null);
  const [draft, setDraft] = useState<CompressionConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const draftRef = useRef<CompressionConfig | null>(null);
  draftRef.current = draft;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const loaded = await fetchCompressionConfig();
      setBaseline(cloneJson(loaded));
      setDraft(cloneJson(loaded));
    } catch (loadError) {
      setError(parseApiError(loadError, "无法加载压缩配置"));
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
    await updateCompressionConfig(captured);
    setBaseline(cloneJson(captured));
  }, []);

  const discard = useCallback(() => {
    if (baseline) setDraft(cloneJson(baseline));
  }, [baseline]);

  useRegisterSettingsStore({
    id: section.id,
    title: section.title,
    dirty: Boolean(baseline && draft && !valuesEqual(baseline, draft)),
    save,
    discard,
  });

  return (
    <SettingsCategoryPanel
      sectionId={section.id}
      title={section.title}
      description={section.description}
      loading={loading}
      loadError={error}
      onRetry={() => void load()}
    >
      {draft ? (
        <SettingsFieldGroups
          groups={COMPRESSION_FIELD_GROUPS}
          values={draft as unknown as Record<string, unknown>}
          resolveValue={(fieldId) => compressionValueAt(draft, fieldId)}
          onChange={(fieldId, value) => setDraft((current) => (
            current
              ? setCompressionValue(current as unknown as Record<string, unknown>, fieldId, value) as unknown as CompressionConfig
              : current
          ))}
        />
      ) : null}
    </SettingsCategoryPanel>
  );
}
