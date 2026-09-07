/**
 * WorkflowNode - 节点画布渲染（支持 Agent / 审批等多节点类型）
 *
 * 吸取 bk-sops TaskNode 设计：
 * - 左侧色块（对应 node_type 颜色）
 * - 右上角类型角标
 * - 运行时状态：pending(grey) → running(blue+pulse) → waiting_approval(yellow) → completed(green) → failed(red)
 * - 底部显示执行摘要
 */
import { Handle, Position, type NodeProps } from "reactflow";
import { AGENT_TYPE_COLORS, NODE_TYPE_COLORS } from "../../types";
import { BRAND_COLORS, NODE_STATUS_COLORS } from "../../lib/brand-colors";

const STATUS_CLASSES: Record<string, string> = {
  pending: "border-border/30",
  running: "border-info shadow-info/20",
  retry_waiting: "border-warning shadow-warning/20",
  completed: "border-success shadow-success/20",
  failed: "border-destructive shadow-destructive/20",
  waiting_approval: "border-warning shadow-warning/20",
  skipped: "border-border/40",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待执行",
  running: "执行中",
  retry_waiting: "等待重试",
  completed: "已完成",
  failed: "失败",
  waiting_approval: "待审批",
  skipped: "已跳过",
};

export default function WorkflowNode({ id, data }: NodeProps) {
  const { label, agent_type, node_type, status, summary, selectionMode, checked, onToggleCheck, is_skipped: legacySkipped, error: nodeError, attempt_count: attemptCount } = data;
  const nt = node_type || "agent";
  const isSelectionMode = selectionMode === true;
  const isChecked = checked !== false; // 默认勾选

  // 颜色：优先 node_type 颜色，其次 agent_type 颜色
  const color =
    NODE_TYPE_COLORS[nt] || AGENT_TYPE_COLORS[agent_type] || BRAND_COLORS.primary;
  const isSkipped = legacySkipped || status === "skipped";
  const effectiveStatus = isSkipped ? "skipped" : status || "pending";
  const borderClass = STATUS_CLASSES[effectiveStatus] || STATUS_CLASSES.pending;
  const dotColor = NODE_STATUS_COLORS[effectiveStatus] || BRAND_COLORS.muted;
  const isRunning = status === "running";
  const isWaitingApproval = status === "waiting_approval";

  // 角标文本
  const badgeText = nt === "approval" ? "审批" : nt === "script" ? "脚本" : nt === "subprocess" ? "子流程" : agent_type || "agent";

  return (
    <div
      className={`relative flex items-stretch rounded-xl bg-card border-2 ${borderClass} min-w-[180px] shadow-lg transition-all duration-300 overflow-hidden ${
        isRunning ? "animate-pulse motion-reduce:animate-none" : ""
      }`}
      style={{ borderColor: effectiveStatus === "pending" ? `color-mix(in srgb, ${color} 25%, transparent)` : undefined }}
      role="article"
      aria-label={`工作流节点: ${label || "未命名"}，状态: ${effectiveStatus}`}
    >
      {/* Left color block */}
      <div
        className="w-1 shrink-0 rounded-l-[10px]"
        style={{ backgroundColor: color }}
      />

      {/* Node body */}
      <div className="flex-1 px-3 py-2.5 min-w-0">
        <Handle
          type="target"
          position={Position.Top}
          className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-border"
        />

        {/* Header: type badge + (status dot / checkbox) */}
        <div className="flex items-center justify-between mb-1">
          <span
            className="text-xs uppercase tracking-wider px-1.5 py-0.5 rounded-md font-medium"
            style={{ backgroundColor: `color-mix(in srgb, ${color} 8%, transparent)`, color }}
          >
            {isWaitingApproval ? "待审批" : badgeText}
          </span>
          {isSelectionMode ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onToggleCheck?.(id, !isChecked);
              }}
              disabled={!onToggleCheck}
              aria-label={`${isChecked ? "取消勾选" : "勾选"}节点 ${label || "未命名"}`}
              className="w-6 h-6 min-w-[24px] min-h-[24px] rounded-full flex items-center justify-center border-2 transition-all duration-200 flex-shrink-0 ml-2 hover:scale-110 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer focus-visible:ring-2 focus-visible:ring-primary/30"
              style={{
                borderColor: isChecked ? BRAND_COLORS.success : BRAND_COLORS.muted,
                backgroundColor: isChecked ? `color-mix(in srgb, ${BRAND_COLORS.success} 12.5%, transparent)` : "transparent",
              }}
            >
              {isChecked ? (
                <svg className="w-3.5 h-3.5 text-success" fill="currentColor" viewBox="0 0 20 20" aria-hidden="true">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              )}
            </button>
          ) : (
            effectiveStatus !== "pending" && (
              <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: dotColor }}
                  aria-hidden="true"
                />
                <span>{STATUS_LABELS[effectiveStatus] || effectiveStatus}</span>
              </div>
            )
          )}
        </div>

        {/* Label */}
        <div className="text-sm font-medium text-foreground truncate">
          {label || "未命名"}
        </div>

        {/* Skipped error tooltip */}
        {isSkipped && nodeError && (
          <div className="mt-1 text-xs text-warning truncate max-w-[200px] leading-tight" title={nodeError}>
            ⚠ {nodeError}
          </div>
        )}

        {/* Summary (truncated) */}
        {!isSkipped && summary && (
          <div className="mt-1 text-xs text-muted-foreground truncate max-w-[200px] leading-tight" title={summary}>
            {summary}
          </div>
        )}

        {(status === "failed" || status === "retry_waiting") && typeof attemptCount === "number" && attemptCount > 0 && (
          <div className="mt-1 text-xs text-muted-foreground">已尝试 {attemptCount} 次</div>
        )}

        <Handle
          type="source"
          position={Position.Bottom}
          className="!bg-muted-foreground !w-2.5 !h-2.5 !border-2 !border-border"
        />
      </div>
    </div>
  );
}
