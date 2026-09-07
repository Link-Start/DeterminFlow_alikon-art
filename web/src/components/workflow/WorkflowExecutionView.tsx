/**
 * WorkflowExecutionView - 执行状态浮层
 *
 * 显示运行进度、当前节点、完成/失败统计、节点状态列表。
 */
import { Node } from "reactflow";
import type { WorkflowState } from "../../types";
import { CheckCircle2, XCircle, Clock, Play } from "lucide-react";

interface WorkflowExecutionViewProps {
  state: WorkflowState;
  nodes: Node[];
}

export default function WorkflowExecutionView({ state, nodes }: WorkflowExecutionViewProps) {
  const nodeStateEntries = Object.entries(state.node_states || {});
  const completedNodes = nodeStateEntries.filter(
    ([, ns]) => ns.status === "completed"
  ).length;
  const failedNodes = nodeStateEntries.filter(
    ([, ns]) => ns.status === "failed"
  ).length;
  const runningNodes = nodeStateEntries.filter(
    ([, ns]) => ns.status === "running"
  ).length;
  const totalNodes = nodeStateEntries.length || nodes.length || 1;
  const progress =
    totalNodes > 0
      ? Math.round(((completedNodes + failedNodes) / totalNodes) * 100)
      : 0;
  const currentNode = state.current_node_id
    ? nodes.find((n) => n.id === state.current_node_id)
    : null;

  const statusConfig: Record<
    string,
    { icon: React.ReactNode; cls: string }
  > = {
    pending: {
      icon: <Clock size={12} aria-hidden="true" />,
      cls: "text-muted-foreground bg-muted-foreground/5 border-border/10",
    },
    running: {
      icon: <Play size={12} aria-hidden="true" />,
      cls: "text-info bg-info/10 border-info/20",
    },
    completed: {
      icon: <CheckCircle2 size={12} aria-hidden="true" />,
      cls: "text-success bg-success/10 border-success/20",
    },
    failed: {
      icon: <XCircle size={12} aria-hidden="true" />,
      cls: "text-destructive bg-destructive/10 border-destructive/20",
    },
  };

  return (
    <div className="absolute bottom-0 left-0 right-0 z-20">
      <div
        className="mx-4 mb-4 p-4 rounded-xl bg-card/95 border border-primary/30 shadow-2xl"
        role="status"
        aria-label="工作流执行状态"
      >
        {/* Top row: status + stats */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-info animate-pulse motion-reduce:animate-none" aria-hidden="true" />
              <span className="text-sm font-medium text-foreground">运行中</span>
            </div>
            {currentNode && (
              <span className="text-xs text-muted-foreground">
                当前节点:{" "}
                <span className="text-foreground">
                  {currentNode.data?.label || currentNode.id}
                </span>
              </span>
            )}
          </div>
          <div className="flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1 text-success">
              <CheckCircle2 size={12} aria-hidden="true" />
              完成 {completedNodes}
            </span>
            {runningNodes > 0 && (
              <span className="flex items-center gap-1 text-info">
                <Play size={12} aria-hidden="true" />
                运行中 {runningNodes}
              </span>
            )}
            {failedNodes > 0 && (
              <span className="flex items-center gap-1 text-destructive">
                <XCircle size={12} aria-hidden="true" />
                失败 {failedNodes}
              </span>
            )}
            <span className="text-muted-foreground">{progress}%</span>
          </div>
        </div>

        {/* Progress bar */}
        <div
          className="w-full h-2 rounded-full bg-background overflow-hidden mb-3"
          role="progressbar"
          aria-valuenow={progress}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`执行进度 ${progress}%`}
        >
          <div className="h-full rounded-full flex">
            <div
              className="h-full bg-gradient-to-r from-primary to-info transition-all duration-500 rounded-l-full"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Node status list */}
        <div className="flex flex-wrap gap-2" role="list" aria-label="节点执行状态">
          {nodeStateEntries.map(([nodeId, ns]) => {
            const nodeObj = nodes.find((n) => n.id === nodeId);
            const label = nodeObj?.data?.label || nodeId;
            const isActive = state.current_node_id === nodeId;
            const config = statusConfig[ns.status] || statusConfig.pending;

            return (
              <div
                key={nodeId}
                role="listitem"
                aria-label={`${label}: ${ns.status}`}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md border text-xs ${
                  config.cls
                } ${isActive ? "ring-1 ring-info" : ""}`}
              >
                {config.icon}
                <span className="truncate max-w-[80px]">{label}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
