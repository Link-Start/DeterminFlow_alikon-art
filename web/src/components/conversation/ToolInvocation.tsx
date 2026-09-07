import {
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleX,
  Loader2,
  Pencil,
} from "lucide-react";
import type { ToolInvocationModel, ToolInvocationStatus } from "./conversationTypes";
import TechnicalDisclosure from "./TechnicalDisclosure";

interface StatusPresentation {
  label: string;
  badgeClass: string;
  borderClass: string;
  icon: React.ReactNode;
}

const STATUS_PRESENTATION: Record<ToolInvocationStatus, StatusPresentation> = {
  pending: {
    label: "等待结果",
    badgeClass: "bg-muted-foreground/15 text-muted-foreground",
    borderClass: "border-border/50",
    icon: <CircleDashed size={16} className="text-muted-foreground" aria-hidden="true" />,
  },
  building: {
    label: "生成参数",
    badgeClass: "bg-warning/15 text-warning",
    borderClass: "border-warning/20",
    icon: <Pencil size={16} className="animate-pulse text-warning motion-reduce:animate-none" aria-hidden="true" />,
  },
  running: {
    label: "执行中",
    badgeClass: "bg-warning/15 text-warning",
    borderClass: "border-warning/25",
    icon: <Loader2 size={16} className="animate-spin text-warning motion-reduce:animate-none" aria-hidden="true" />,
  },
  succeeded: {
    label: "已完成",
    badgeClass: "bg-success/15 text-success",
    borderClass: "border-success/20",
    icon: <CheckCircle2 size={16} className="text-success" aria-hidden="true" />,
  },
  failed: {
    label: "执行失败",
    badgeClass: "bg-destructive/15 text-destructive",
    borderClass: "border-destructive/25",
    icon: <CircleX size={16} className="text-destructive" aria-hidden="true" />,
  },
  cancelled: {
    label: "已取消",
    badgeClass: "bg-muted-foreground/15 text-foreground",
    borderClass: "border-border/25",
    icon: <Ban size={16} className="text-muted-foreground" aria-hidden="true" />,
  },
};

export interface ToolInvocationProps {
  invocation: ToolInvocationModel;
  className?: string;
}

export default function ToolInvocation({ invocation, className = "" }: ToolInvocationProps) {
  const presentation = STATUS_PRESENTATION[invocation.status];
  const hasArguments = !!invocation.arguments && invocation.arguments.trim() !== "{}";
  const hasResult = invocation.result !== undefined;

  return (
    <article
      aria-label={`工具调用 ${invocation.name}，${presentation.label}`}
      className={`ml-10 rounded-lg border bg-secondary/50 px-3 py-2 ${presentation.borderClass} ${className}`}
    >
      <header className="flex min-h-8 items-center gap-2">
        {presentation.icon}
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-warning" title={invocation.name}>
          {invocation.name}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${presentation.badgeClass}`}
          role="status"
          aria-label={presentation.label}
        >
          {presentation.label}
        </span>
      </header>

      {hasArguments && (
        <TechnicalDisclosure label="参数" value={invocation.arguments} />
      )}
      {invocation.error && (
        <TechnicalDisclosure label="错误" value={invocation.error} tone="error" />
      )}
      {hasResult && (
        <TechnicalDisclosure
          label={invocation.status === "failed" ? "失败结果" : "结果"}
          value={invocation.result || ""}
          tone={invocation.status === "failed" ? "error" : "neutral"}
        />
      )}
    </article>
  );
}
