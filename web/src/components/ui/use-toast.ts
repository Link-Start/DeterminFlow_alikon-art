import * as React from "react";

export interface Toast {
  id: string;
  title?: string;
  description?: string;
  variant?: "default" | "success" | "error" | "warning" | "destructive";
  duration?: number;
}

export const MAX_VISIBLE_TOASTS = 3;

export function enqueueToast(current: Toast[], next: Toast): Toast[] {
  const withoutDuplicate = current.filter((item) => (
    item.title !== next.title
    || item.description !== next.description
    || item.variant !== next.variant
  ));
  return [...withoutDuplicate, next].slice(-MAX_VISIBLE_TOASTS);
}

export interface ToastContextType {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
}

const ToastContext = React.createContext<ToastContextType | undefined>(undefined);

export function useToast() {
  const context = React.useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return {
    toast: context.addToast,
    toasts: context.toasts,
    dismiss: context.removeToast,
  };
}

export function useToastState() {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const addToast = React.useCallback((toast: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).substr(2, 9);
    const newToast = { ...toast, id };
    setToasts((prev) => enqueueToast(prev, newToast));

    // Auto remove after duration
    const duration = toast.duration || 3000;
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, duration);
  }, []);

  const removeToast = React.useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, addToast, removeToast };
}

export { ToastContext };
export type { ToastContextType as ToastProviderProps };
