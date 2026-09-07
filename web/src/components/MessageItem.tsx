import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronRight } from "lucide-react";
import { safeJsonParse, prettyJson } from "../lib/utils-helpers";

interface MessageItemProps {
  message: {
    id?: string;
    type?: string;
    role?: string;
    content?: unknown;
    tool_calls?: Array<{ id: string; type: string; function: { name: string; arguments: string } }>;
    tool_call_id?: string;
    name?: string;
  };
  index: number;
}

export default function MessageItem({ message, index }: MessageItemProps) {
  const [expanded, setExpanded] = useState(false);
  const contentText = typeof message.content === "string"
    ? message.content
    : message.content == null
      ? ""
      : prettyJson(message.content);

  const roleColors: Record<string, string> = {
    system: "text-primary",
    user: "text-success",
    assistant: "text-primary",
    tool: "text-warning",
  };

  const roleLabels: Record<string, string> = {
    system: "System",
    user: "User",
    assistant: "Assistant",
    tool: "Tool",
  };

  const msgRole = message.type || message.role || "";
  const color = roleColors[msgRole] || "text-muted-foreground";
  const label = roleLabels[msgRole] || msgRole;

  return (
    <div className="min-w-0 bg-secondary/50 border border-border/50 rounded-lg px-2.5 py-2">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-label={`${label} 消息 #${index}${expanded ? "，收起详情" : "，展开详情"}`}
        className="flex min-h-[44px] min-w-0 w-full items-center gap-2 rounded text-left cursor-pointer transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <span className="text-xs text-muted-foreground font-mono">#{index}</span>
        <span className={`text-xs font-medium ${color}`}>{label}</span>
        {message.name && (
          <span className="text-xs text-muted-foreground">({message.name})</span>
        )}
        {message.tool_calls && message.tool_calls.length > 0 && (
          <Badge variant="outline" className="text-xs text-warning border-warning/30">
            {message.tool_calls.length} tool calls
          </Badge>
        )}
        {message.tool_call_id && (
          <Badge variant="outline" className="text-xs text-info border-info/30">
            result
          </Badge>
        )}
        <span className="text-xs text-muted-foreground ml-auto" aria-hidden="true">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </button>

      {expanded && (
        <div className="mt-2 min-w-0 space-y-2" role="list" aria-label="消息详情">
          {contentText && (
            <div className="max-h-48 min-w-0 overflow-auto rounded bg-card/60 p-2 text-xs text-foreground">
              <div className="text-xs text-muted-foreground mb-1">Content:</div>
              <div className="whitespace-pre-wrap [overflow-wrap:anywhere]">{contentText}</div>
            </div>
          )}
          {message.tool_calls && message.tool_calls.map((tc, i) => (
            <div key={i} className="min-w-0 bg-card/60 rounded p-2" role="listitem">
              <div className="break-all text-xs font-mono text-warning mb-1">{tc.function.name}</div>
              <div className="text-xs text-muted-foreground mb-0.5">Arguments:</div>
              <pre className="min-w-0 overflow-auto whitespace-pre-wrap text-xs text-muted-foreground [overflow-wrap:anywhere]">
                {prettyJson(safeJsonParse(tc.function.arguments))}
              </pre>
            </div>
          ))}
          {message.tool_call_id && (
            <div className="text-xs text-muted-foreground">
              Tool Call ID: <span className="font-mono text-info">{message.tool_call_id}</span>
            </div>
          )}
        </div>
      )}

      {!expanded && contentText && (
        <p className="mt-1 truncate text-xs text-muted-foreground" title={contentText}>
          {contentText.slice(0, 80)}
        </p>
      )}
    </div>
  );
}
