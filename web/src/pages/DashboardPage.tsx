import { useEffect, useState, useCallback } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { useSystemStatus } from "../hooks/useSystemStatus";
import { useSessions } from "../hooks/useSessions";
import StatsCards from "../components/StatsCards";
import PromptTimeline from "../components/PromptTimeline";
import ToolStatsPanel from "../components/ToolStatsPanel";
import CompressionMonitorPanel from "../components/compression/CompressionMonitorPanel";
import CompressionLogsPanel from "../components/compression/CompressionLogsPanel";
import { formatTime, truncate } from "../lib/utils-helpers";
import { fetchPromptHistory } from "../lib/api";
import { PromptHistoryEntry, Session } from "../types";
import { BRAND_COLORS } from "../lib/brand-colors";

/* Status color map (single source of truth) */
const STATUS_STYLES: Record<string, { bg: string; label: string }> = {
  running:   { bg: BRAND_COLORS.success, label: "运行中" },
  streaming: { bg: BRAND_COLORS.info, label: "流式传输" },
  completed: { bg: BRAND_COLORS.success, label: "已完成" },
  error:     { bg: BRAND_COLORS.destructive, label: "错误" },
  idle:      { bg: BRAND_COLORS.muted, label: "空闲" },
};
const DEFAULT_STATUS = { bg: BRAND_COLORS.warning, label: "未知" };

function getStatusStyle(status: string) {
  return STATUS_STYLES[status] ?? DEFAULT_STATUS;
}

export default function DashboardPage() {
  const { status, tools } = useSystemStatus();
  const { sessions } = useSessions();
  const [promptHistory, setPromptHistory] = useState<PromptHistoryEntry[]>([]);
  const [historyError, setHistoryError] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const data = await fetchPromptHistory();
      setPromptHistory(data.history);
      setHistoryError(false);
    } catch {
      setHistoryError(true);
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  if (!status) {
    return (
      <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3" role="status" aria-label="加载中" aria-live="polite">
        <div className="flex gap-1.5">
          <span className="w-2 h-2 rounded-full bg-info/60 animate-pulse motion-reduce:animate-none [animation-delay:0ms]" aria-hidden="true" />
          <span className="w-2 h-2 rounded-full bg-info/60 animate-pulse motion-reduce:animate-none [animation-delay:150ms]" aria-hidden="true" />
          <span className="w-2 h-2 rounded-full bg-info/60 animate-pulse motion-reduce:animate-none [animation-delay:300ms]" aria-hidden="true" />
        </div>
        <span className="text-sm text-muted-foreground">加载系统状态...</span>
      </div>
    );
  }

  return (
    <ScrollArea className="h-full min-h-0 min-w-0">
      <div className="p-6 space-y-8 max-w-[1400px] mx-auto" role="main" aria-label="仪表盘">
        {/* Stats Cards Row */}
        <section aria-label="系统指标概览">
          <StatsCards status={status} />
        </section>

        {/* Sessions Table */}
        <section aria-label="活跃会话">
          <SessionsTable sessions={sessions} />
        </section>

        {/* Tool Stats & Prompt Timeline */}
        <div className="grid grid-cols-1 items-stretch gap-6 lg:grid-cols-3 lg:grid-rows-1">
          <div className="lg:col-span-2 max-h-[350px] overflow-y-auto rounded-lg" role="region" aria-label="工具调用统计">
            <ToolStatsPanel tools={tools} stats={status.event_bus_stats} />
          </div>
          <div className="flex min-h-0 max-h-[350px] flex-col overflow-hidden rounded-lg" role="region" aria-label="提示词历史时间线">
            {historyError ? (
              <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 rounded-lg border border-border/50 bg-secondary/80 p-4" role="alert">
                <span className="text-sm text-destructive">加载提示词历史失败</span>
                <button
                  onClick={loadHistory}
                  className="text-xs text-info hover:underline cursor-pointer min-h-[44px] min-w-[44px] flex items-center justify-center focus-visible:ring-2 focus-visible:ring-info/30 rounded"
                  aria-label="重新加载提示词历史"
                >
                  重试
                </button>
              </div>
            ) : (
              <PromptTimeline history={promptHistory} />
            )}
          </div>
        </div>

        {/* Compression Monitor */}
        <section className="rounded-lg border border-border/50 bg-secondary/80 p-3" aria-label="压缩状态监控">
          <h3 className="mb-2 text-xs font-semibold text-muted-foreground/70">压缩状态监控</h3>
          <CompressionMonitorPanel compact={true} />
        </section>

        {/* Compression Logs */}
        <section className="bg-secondary/80 border border-border/50 rounded-lg p-5" aria-label="压缩日志">
          <h3 className="text-xs font-semibold text-muted-foreground/70 mb-3">压缩日志</h3>
          <div className="max-h-[300px] overflow-y-auto rounded">
            <CompressionLogsPanel compact={true} />
          </div>
        </section>
      </div>
    </ScrollArea>
  );
}

// ============ Sessions Table ============

function StatusDot({ status }: { status: string }) {
  const isAnimated = status === "running" || status === "streaming";
  const style = getStatusStyle(status);
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={`w-2 h-2 rounded-full flex-shrink-0 ${isAnimated ? "status-running" : ""}`}
        style={{ backgroundColor: style.bg }}
        aria-hidden="true"
      />
      <span className="text-xs text-foreground">{status}</span>
      <span className="sr-only">{style.label}</span>
    </span>
  );
}

function SessionsTable({ sessions }: { sessions: Session[] }) {
  return (
    <div className="bg-secondary/80 border border-border/50 rounded-lg p-5">
      <h3 className="text-xs font-semibold text-muted-foreground/70 mb-3">会话实时状态</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm" aria-label="会话列表">
          <thead>
            <tr className="text-xs text-muted-foreground/60 border-b border-border/40">
              <th scope="col" className="text-left py-2.5 px-3 font-medium">ID</th>
              <th scope="col" className="text-left py-2.5 px-3 font-medium">类型</th>
              <th scope="col" className="text-left py-2.5 px-3 font-medium">状态</th>
              <th scope="col" className="text-left py-2.5 px-3 font-medium">任务</th>
              <th scope="col" className="text-right py-2.5 px-3 font-medium">消息数</th>
              <th scope="col" className="text-right py-2.5 px-3 font-medium">更新时间</th>
            </tr>
          </thead>
          <tbody>
            {sessions.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center text-muted-foreground/50 text-sm py-10" role="status" aria-label="暂无活跃会话">
                  暂无活跃会话
                </td>
              </tr>
            ) : (
              sessions.map((session) => {
                return (
                  <tr
                    key={session.session_id}
                    className="border-b border-border/30 hover:bg-white/[0.02] transition-colors duration-200"
                    role="row"
                  >
                    <td className="py-2.5 px-3">
                      <span className="font-mono text-xs text-info">{session.session_id}</span>
                    </td>
                    <td className="py-2.5 px-3">
                      <Badge
                        variant="outline"
                        className={`text-xs font-medium ${
                          session.type === "main"
                            ? "text-primary border-primary/20"
                            : "text-muted-foreground/50 border-muted-foreground/15"
                        }`}
                      >
                        {session.type === "main" ? "MAIN" : "SUB"}
                      </Badge>
                    </td>
                    <td className="py-2.5 px-3">
                      <StatusDot status={session.status} />
                    </td>
                    <td className="py-2.5 px-3 max-w-[200px]">
                      <span className="text-xs text-muted-foreground truncate block" title={session.task || undefined}>
                        {truncate(session.task || (session.type === "main" ? "主会话" : "-"), 40)}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right tabular-nums">
                      <span className="text-xs text-muted-foreground/60">{session.message_count}</span>
                    </td>
                    <td className="py-2.5 px-3 text-right tabular-nums">
                      <span className="text-xs text-muted-foreground/60">{formatTime(session.updated_at)}</span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
