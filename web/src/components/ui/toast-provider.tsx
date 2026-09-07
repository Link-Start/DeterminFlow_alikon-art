import * as React from "react";
import { X } from "lucide-react";
import { ToastContext, useToastState, Toast } from "./use-toast";
import { cn } from "@/lib/utils";

export interface ToastProviderProps {
  children: React.ReactNode;
}

export function ToastProvider({ children }: ToastProviderProps) {
  const { toasts, addToast, removeToast } = useToastState();

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
      {/* Toast Container - aria-live for screen reader announcements */}
      <div
        aria-live="polite"
        aria-label="通知"
        className="fixed top-16 right-4 z-50 flex flex-col gap-2"
      >
        {toasts.map((toast) => (
          <ToastItem
            key={toast.id}
            toast={toast}
            onDismiss={() => removeToast(toast.id)}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: () => void;
}) {
  const variantStyles = {
    default: "bg-card border-border text-foreground",
    success: "bg-card border-success text-success",
    error: "bg-card border-destructive text-destructive",
    destructive: "bg-card border-destructive text-destructive",
    warning: "bg-card border-warning text-warning",
  };

  const style = variantStyles[toast.variant || "default"];

  return (
    <div
      role="alert"
      aria-label={toast.title || "通知消息"}
      className={cn(
        "relative w-72 rounded-lg border p-4 shadow-lg animate-in slide-in-from-right-full",
        style
      )}
    >
      {toast.title && (
        <div className="text-sm font-semibold">{toast.title}</div>
      )}
      {toast.description && (
        <div className="mt-1 text-sm opacity-90">{toast.description}</div>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="关闭通知"
        className="absolute right-2 top-2 rounded-sm opacity-70 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
