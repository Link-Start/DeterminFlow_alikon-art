import type { ReactElement } from "react";

import { AppearanceCategory } from "./categories/AppearanceCategory";
import { CompressionCategory } from "./categories/CompressionCategory";
import { CoreConfigCategory } from "./categories/CoreConfigCategory";
import { DesktopCategory } from "./categories/DesktopCategory";
import { WorkspaceCategory } from "./categories/WorkspaceCategory";
import { MemoryCategory } from "./categories/MemoryCategory";
import { ModelsCategory } from "./categories/ModelsCategory";
import { PluginCategory } from "./categories/PluginCategory";
import { UnsupportedCategory } from "./categories/UnsupportedCategory";
import { isCoreSectionId } from "./section-model";
import type { SettingsSection } from "./types";

const CORE_RENDERERS: Record<string, (section: SettingsSection) => ReactElement> = {
  appearance: (section) => <AppearanceCategory section={section} />,
  desktop: (section) => <DesktopCategory section={section} />,
  models: (section) => <ModelsCategory section={section} />,
  agent: (section) => <CoreConfigCategory section={section} />,
  roundtable: (section) => <CoreConfigCategory section={section} />,
  coding: (section) => <CoreConfigCategory section={section} />,
  system: (section) => <CoreConfigCategory section={section} />,
  compression: (section) => <CompressionCategory section={section} />,
  memory: (section) => <MemoryCategory section={section} />,
  workspace: (section) => <WorkspaceCategory section={section} />,
};

export function renderSettingsCategory(section: SettingsSection): ReactElement {
  if (section.kind === "plugin") return <PluginCategory section={section} />;
  if (isCoreSectionId(section.id) && CORE_RENDERERS[section.id]) {
    return CORE_RENDERERS[section.id](section);
  }
  return <UnsupportedCategory section={section} />;
}
