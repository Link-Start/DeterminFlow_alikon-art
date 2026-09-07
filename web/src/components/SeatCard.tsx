import { X, MessageCircle } from "lucide-react";
import { Seat } from "../types";
import { getSeatColor } from "../lib/seatColors";

interface SeatCardProps {
  seat: Seat;
  seatIndex: number;
  isDiscussing?: boolean;
  actionsDisabled?: boolean;
  onRemove?: (seatId: string) => void;
  onNominate?: (seatId: string) => void;
}

export default function SeatCard({
  seat,
  seatIndex,
  isDiscussing,
  actionsDisabled = false,
  onRemove,
  onNominate,
}: SeatCardProps) {
  const color = getSeatColor(seatIndex);
  const isSpeaking = seat.status === "speaking";
  const isThinking = seat.status === "thinking";
  const isDone = seat.status === "done";

  // 确定是否可以操作
  const canNominate = isDiscussing && !isSpeaking && !isThinking && onNominate && !seat.is_moderator;
  const canRemove = onRemove && !isSpeaking;

  return (
    <div
      className={`bg-secondary/50 border rounded-lg p-3 transition-all duration-300 ${
        isSpeaking
          ? `${color.border} ${color.bg}`
          : isThinking
          ? "border-warning/30 bg-warning/5"
          : isDone
          ? "border-success/20 bg-success/5"
          : "border-border/50"
      }`}
      role="article"
      aria-label={`${seat.role_name} - ${getStatusText(seat.status)}${seat.is_moderator ? " (主持人)" : ""}`}
    >
      <div className="flex items-center gap-2">
        {/* 状态指示器 - 使用更大的触摸区域 */}
        <div className="relative w-6 h-6 flex items-center justify-center" aria-hidden="true">
          <span className={`w-3 h-3 rounded-full block ${isThinking ? "bg-warning" : isDone ? "bg-success" : color.dot}`} />
          {(isSpeaking || isThinking) && (
            <span
              className={`absolute inset-0 w-6 h-6 rounded-full ${isThinking ? "bg-warning" : color.dot} animate-ping opacity-75`}
            />
          )}
        </div>

        {/* 角色名 */}
        <span className="text-sm font-medium text-foreground flex-1 truncate">
          {seat.role_name}
        </span>

        {/* 状态标签 */}
        <StatusBadge status={seat.status} />
      </div>

      {/* 角色信息 */}
      <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-mono">T={seat.temperature}</span>
        {seat.is_moderator && (
          <span className="bg-warning/20 text-warning px-1.5 py-0.5 rounded text-xs font-medium">
            主持人
          </span>
        )}
        <div className="flex-1" />
        {/* Phase 3: 点名按钮 - 增加触摸目标大小 */}
        {canNominate && (
          <button
            type="button"
            onClick={() => onNominate(seat.seat_id)}
            disabled={actionsDisabled}
            className="text-muted-foreground hover:text-info transition-colors cursor-pointer p-2 min-w-[44px] min-h-[44px] flex items-center justify-center disabled:cursor-not-allowed disabled:opacity-40"
            aria-label={`点名 ${seat.role_name} 发言`}
          >
            <MessageCircle size={14} aria-hidden="true" />
          </button>
        )}
        {/* Phase 3: 移除按钮 - 增加触摸目标大小 */}
        {canRemove && (
          <button
            type="button"
            onClick={() => onRemove(seat.seat_id)}
            disabled={actionsDisabled}
            className="text-muted-foreground hover:text-destructive transition-colors cursor-pointer p-2 min-w-[44px] min-h-[44px] flex items-center justify-center disabled:cursor-not-allowed disabled:opacity-40"
            aria-label={`移除 ${seat.role_name}`}
          >
            <X size={14} aria-hidden="true" />
          </button>
        )}
      </div>
    </div>
  );
}

function getStatusText(status: string): string {
  const map: Record<string, string> = {
    idle: "等待中",
    speaking: "发言中",
    thinking: "思考中",
    done: "已发言",
  };
  return map[status] || "等待中";
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { bg: string; text: string; label: string }> = {
    idle: { bg: "bg-muted-foreground/20", text: "text-muted-foreground", label: "等待" },
    speaking: { bg: "bg-success/20", text: "text-success", label: "发言中" },
    thinking: { bg: "bg-warning/20", text: "text-warning", label: "思考中" },
    done: { bg: "bg-info/20", text: "text-info", label: "已发言" },
  };

  const c = config[status] || config.idle;

  return (
    <span
      className={`text-xs px-1.5 py-0.5 rounded ${c.bg} ${c.text}`}
      role="status"
      aria-label={`状态: ${c.label}`}
      aria-live="polite"
    >
      {c.label}
    </span>
  );
}
