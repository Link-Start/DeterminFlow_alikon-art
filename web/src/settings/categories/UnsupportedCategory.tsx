import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import type { SettingsSection } from "../types";

export function UnsupportedCategory({ section }: { section: SettingsSection }) {
  return (
    <SettingsCategoryPanel sectionId={section.id} title={section.title} description={section.description}>
      <p className="text-sm text-muted-foreground">此版本客户端暂不支持该分类。</p>
    </SettingsCategoryPanel>
  );
}
