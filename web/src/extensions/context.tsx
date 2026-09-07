import { useEffect, useState } from "react";

import { CORE_TAB_IDS } from "@/core-tabs";
import { fetchExtensions } from "@/lib/api";
import {
  EMPTY_EXTENSION_CONTEXT,
  ExtensionContext,
  type ExtensionContextValue,
} from "./context-value";
import { startExtensionActivationLoop } from "./activation-loop";
import { loadRunningFrontendExtensions } from "./registry";

async function loadExtensionContext(): Promise<ExtensionContextValue> {
  const data = await fetchExtensions();
  const statuses = data.extensions ?? [];
  const activation = await loadRunningFrontendExtensions(statuses, CORE_TAB_IDS);
  return { ...activation, statuses };
}

export function ExtensionProvider({ children }: { children: React.ReactNode }) {
  const [value, setValue] = useState<ExtensionContextValue>(EMPTY_EXTENSION_CONTEXT);

  useEffect(() => startExtensionActivationLoop({
    load: loadExtensionContext,
    onLoaded: setValue,
    onError: (error) => {
      setValue({
        extensions: [],
        statuses: [],
        errors: [{
          extensionId: "frontend",
          message: `Extension 状态加载失败: ${error instanceof Error ? error.message : String(error)}`,
        }],
      });
    },
  }), []);

  return <ExtensionContext.Provider value={value}>{children}</ExtensionContext.Provider>;
}
