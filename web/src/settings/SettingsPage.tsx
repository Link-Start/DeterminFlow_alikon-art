import { Fragment, useCallback, useEffect, useState } from "react";

import { useUrlParam } from "@/hooks/useUrlParam";
import { fetchSettingsSections } from "./api";
import { CoreConfigProvider } from "./core-config-context";
import { SettingsPluginsProvider } from "./plugins-context";
import { parseApiError } from "./parse-api-error";
import { renderSettingsCategory } from "./registry";
import {
  CORE_FALLBACK_SECTIONS,
  resolveSelectedSection,
} from "./section-model";
import { SettingsCategoryPanel } from "./SettingsCategoryPanel";
import { SettingsSectionTargetContext } from "./section-target-context";
import { SettingsToolbar } from "./SettingsToolbar";
import { SettingsWorkspace } from "./SettingsWorkspace";
import type { SettingsSection } from "./types";

function SettingsPageBody() {
  const [requestedSection] = useUrlParam("section");
  const [sections, setSections] = useState<SettingsSection[]>(CORE_FALLBACK_SECTIONS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const selected = resolveSelectedSection(sections, requestedSection);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSections(await fetchSettingsSections());
    } catch (loadError) {
      setSections(CORE_FALLBACK_SECTIONS);
      setError(parseApiError(loadError, "无法加载配置分类，已使用内置分类"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto w-full max-w-4xl min-w-0 px-4 pb-6 sm:px-6">
      <SettingsToolbar />
      <div className="space-y-6 pt-3">
        {error ? (
          <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-sm text-warning" role="status">
            {error}
          </div>
        ) : null}
        <SettingsSectionTargetContext.Provider value={!loading && requestedSection ? selected?.id ?? null : null}>
          {loading && sections.length === 0 ? (
            <SettingsCategoryPanel sectionId="loading" title="配置" loading>
              {null}
            </SettingsCategoryPanel>
          ) : sections.length > 0 ? (
            sections.map((section) => (
              <Fragment key={section.id}>{renderSettingsCategory(section)}</Fragment>
            ))
          ) : (
            <p className="text-sm text-muted-foreground">没有可显示的配置分类。</p>
          )}
        </SettingsSectionTargetContext.Provider>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <SettingsWorkspace>
      <SettingsPluginsProvider>
        <CoreConfigProvider>
          <SettingsPageBody />
        </CoreConfigProvider>
      </SettingsPluginsProvider>
    </SettingsWorkspace>
  );
}
