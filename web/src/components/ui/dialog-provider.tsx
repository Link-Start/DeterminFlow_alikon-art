import { useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { DialogController } from "@/lib/dialog-controller";
import { Button } from "./button";
import { Dialog } from "./dialog";
import { DialogContext, type GlobalDialog } from "./use-dialog";

interface Content { title: string; description?: string; render: () => ReactNode }

export function DialogProvider({ children }: { children: ReactNode }) {
  const controller = useMemo(() => new DialogController<Content>(), []);
  const active = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  const api = useMemo<GlobalDialog>(() => ({
    open: (options) => {
      const content: Content = {
        title: options.title,
        description: options.description,
        render: () => options.render({ resolve: (value) => controller.settle(options.key, value, content), cancel: () => controller.settle(options.key, null, content) }),
      };
      return controller.open(options.key, content);
    },
    confirm: async (options) => {
      const content: Content = {
        title: options.title,
        description: options.message,
        render: () => <div className="mt-6 flex justify-end gap-2">
          <Button data-dialog-autofocus type="button" variant="outline" className="min-h-11" onClick={() => controller.settle(options.key, false, content)}>取消</Button>
          <Button type="button" variant={options.destructive ? "destructive" : "default"} className="min-h-11" onClick={() => controller.settle(options.key, true, content)}>{options.confirmLabel || "确认"}</Button>
        </div>,
      };
      return (await controller.open<boolean>(options.key, content)) === true;
    },
    cancelMatching: (prefix) => controller.cancelMatching(prefix),
  }), [controller]);

  useEffect(() => () => controller.cancelMatching(""), [controller]);
  return <DialogContext.Provider value={api}>
    {children}
    {active ? <Dialog key={active.key} open title={active.content.title} description={active.content.description} onClose={() => controller.settle(active.key, null, active.content)}>{active.content.render()}</Dialog> : null}
  </DialogContext.Provider>;
}
