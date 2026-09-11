import { DesktopUpdatePanel } from "@/desktop-updater/DesktopUpdatePanel";
import { useDesktopUpdate } from "@/desktop-updater/context-value";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import type { SettingsSection } from "../types";

export function DesktopCategory({ section }: { section: SettingsSection }) {
  const { enabled } = useDesktopUpdate();

  if (!enabled) return null;

  return (
    <SettingsCategoryPanel sectionId={section.id} title={section.title} description={section.description}>
      <DesktopUpdatePanel />
    </SettingsCategoryPanel>
  );
}
