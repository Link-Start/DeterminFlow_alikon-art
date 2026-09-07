import { createContext, useContext, type ReactNode } from "react";

export interface DialogActions<T> { resolve: (value: T) => void; cancel: () => void }
export interface GlobalDialog {
  open<T>(options: { key: string; title: string; description?: string; render: (actions: DialogActions<T>) => ReactNode }): Promise<T | null>;
  confirm(options: { key: string; title: string; message: string; confirmLabel?: string; destructive?: boolean }): Promise<boolean>;
  cancelMatching(prefix: string): void;
}

export const DialogContext = createContext<GlobalDialog | null>(null);
export function useDialog(): GlobalDialog {
  const dialog = useContext(DialogContext);
  if (!dialog) throw new Error("useDialog requires DialogProvider");
  return dialog;
}
