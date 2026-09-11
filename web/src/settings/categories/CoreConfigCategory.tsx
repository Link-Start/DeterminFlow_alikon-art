import { fieldSpecFromConfigMeta } from "../field-model";
import { useCoreConfig } from "../core-config-context";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import { SettingsFieldList, SettingsFieldRow } from "../SettingsFieldControl";
import { useRegisterSettingsStore } from "../SettingsWorkspace";
import type { SettingsSection } from "../types";

export function CoreConfigCategory({ section }: { section: SettingsSection }) {
  const {
    meta,
    loading,
    error,
    load,
    setValue,
    displayValue,
    groupDirty,
    saveGroup,
    discardGroup,
  } = useCoreConfig();
  const items = meta.filter((item) => item.group === section.id);

  useRegisterSettingsStore({
    id: section.id,
    title: section.title,
    dirty: groupDirty(section.id),
    save: () => saveGroup(section.id),
    discard: () => discardGroup(section.id),
  });

  return (
    <SettingsCategoryPanel
      sectionId={section.id}
      title={section.title}
      loading={loading}
      loadError={error}
      onRetry={() => void load()}
    >
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">没有可配置项。</p>
      ) : (
        <SettingsFieldList>
          {items.map((item) => (
            <SettingsFieldRow
              key={item.key}
              spec={fieldSpecFromConfigMeta(item)}
              value={displayValue(item.key)}
              onChange={(value) => {
                if (value === undefined) return;
                setValue(item.key, value as string | number | boolean);
              }}
            />
          ))}
        </SettingsFieldList>
      )}
    </SettingsCategoryPanel>
  );
}
