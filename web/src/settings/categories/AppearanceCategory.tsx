import { Switch } from "@/components/ui/switch";
import { useTheme } from "@/theme-context";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import type { SettingsSection } from "../types";

export function AppearanceCategory({ section }: { section: SettingsSection }) {
  const { theme, setTheme } = useTheme();

  return (
    <SettingsCategoryPanel sectionId={section.id} title={section.title}>
      <div className="flex items-center justify-between gap-4 border-t border-border/50 pt-4">
        <div>
          <p className="text-sm font-medium text-foreground">界面主题</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{theme === "dark" ? "深色" : "浅色"}</p>
        </div>
        <Switch
          checked={theme === "light"}
          onCheckedChange={(checked) => setTheme(checked ? "light" : "dark")}
          aria-label="使用浅色主题"
        />
      </div>
    </SettingsCategoryPanel>
  );
}
