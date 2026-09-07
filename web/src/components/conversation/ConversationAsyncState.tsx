import { AlertTriangle, Loader2, MessageSquare, RefreshCw } from "lucide-react";

export type ConversationAsyncStateKind = "loading" | "empty" | "error";

export interface ConversationAsyncStateProps {
  kind: ConversationAsyncStateKind;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

const DEFAULT_MESSAGES: Record<ConversationAsyncStateKind, string> = {
  loading: "正在加载消息",
  empty: "暂无消息",
  error: "消息加载失败",
};

export default function ConversationAsyncState({
  kind,
  message,
  onRetry,
  className = "",
}: ConversationAsyncStateProps) {
  const visibleMessage = message || DEFAULT_MESSAGES[kind];
  const role = kind === "error" ? "alert" : "status";

  return (
    <div className={`flex min-h-40 flex-col items-center justify-center gap-3 px-4 py-8 text-center ${className}`} role={role}>
      {kind === "loading" && <Loader2 size={22} className="animate-spin text-primary motion-reduce:animate-none" aria-hidden="true" />}
      {kind === "empty" && <MessageSquare size={22} className="text-muted-foreground" aria-hidden="true" />}
      {kind === "error" && <AlertTriangle size={22} className="text-destructive" aria-hidden="true" />}
      <p className={`text-sm ${kind === "error" ? "text-destructive" : "text-muted-foreground"}`}>{visibleMessage}</p>
      {kind === "error" && onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex min-h-10 items-center gap-2 rounded-md border border-destructive/25 bg-destructive/10 px-3 text-sm text-destructive transition-colors hover:bg-destructive/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive/50"
        >
          <RefreshCw size={14} aria-hidden="true" />
          重试
        </button>
      )}
    </div>
  );
}
