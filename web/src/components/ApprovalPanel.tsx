/**
 * ApprovalPanel - 审批通知面板
 *
 * 位于 ChatPage 顶部的悬浮审批通知条：
 * - 每条审批请求显示命令内容（等宽字体高亮）、来源 Session ID、工作目录、超时倒计时
 * - 操作按钮：✅ 批准 / ❌ 拒绝
 * - 多条排队显示（FIFO）
 * - 审批通过/拒绝后自动消失
 */
import { memo, useState, useEffect } from "react";
import { Shield, Check, X, Clock, Terminal } from "lucide-react";
import { ApprovalRequest } from "../types";

interface ApprovalPanelProps {
  pendingApprovals: ApprovalRequest[];
  resolvedApprovals: { request_id: string; result: string; resolved_at: string }[];
  onApprove: (requestId: string) => void;
  onReject: (requestId: string, reason?: string) => void;
  onClearResolved: (requestId: string) => void;
}

function CountdownBar({ expiresAt }: { expiresAt: string }) {
  const [remaining, setRemaining] = useState(100);

  useEffect(() => {
    const expiresMs = new Date(expiresAt).getTime();
    const totalMs = expiresMs - Date.now();
    if (totalMs <= 0) {
      setRemaining(0);
      return;
    }

    const timer = setInterval(() => {
      const now = Date.now();
      const left = expiresMs - now;
      if (left <= 0) {
        setRemaining(0);
        clearInterval(timer);
      } else {
        setRemaining(Math.round((left / totalMs) * 100));
      }
    }, 500);

    return () => clearInterval(timer);
  }, [expiresAt]);

  const seconds = Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 1000));

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 bg-secondary rounded-full overflow-hidden" role="progressbar" aria-valuenow={remaining} aria-valuemin={0} aria-valuemax={100} aria-label={`审批超时倒计时 ${seconds} 秒`}>
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            remaining > 50 ? "bg-success" : remaining > 20 ? "bg-warning" : "bg-destructive"
          }`}
          style={{ width: `${remaining}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground font-mono w-8 text-right">
        {seconds}s
      </span>
    </div>
  );
}

function ApprovalPanel({
  pendingApprovals,
  resolvedApprovals,
  onApprove,
  onReject,
  onClearResolved,
}: ApprovalPanelProps) {
  // 自动清除已解决的通知（3秒后消失）
  useEffect(() => {
    if (resolvedApprovals.length === 0) return;
    const latest = resolvedApprovals[resolvedApprovals.length - 1];
    const timer = setTimeout(() => {
      onClearResolved(latest.request_id);
    }, 3000);
    return () => clearTimeout(timer);
  }, [resolvedApprovals, onClearResolved]);

  if (pendingApprovals.length === 0 && resolvedApprovals.length === 0) {
    return null;
  }

  return (
    <div className="px-4 py-2 space-y-2" role="region" aria-label="审批通知面板">
      {/* 已解决通知（Toast） */}
      {resolvedApprovals.map((r) => (
        <div
          key={r.request_id}
          className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs animate-fade-in ${
            r.result === "approved"
              ? "bg-success/10 border border-success/20 text-success"
              : r.result === "rejected"
                ? "bg-destructive/10 border border-destructive/20 text-destructive"
                : "bg-warning/10 border border-warning/20 text-warning"
          }`}
          role="alert"
        >
          {r.result === "approved" ? <Check size={14} aria-hidden="true" /> : <X size={14} aria-hidden="true" />}
          <span>
            审批请求 {r.request_id.slice(0, 8)}...{" "}
            {r.result === "approved" ? "已批准" : r.result === "rejected" ? "已拒绝" : "已超时"}
          </span>
        </div>
      ))}

      {/* 待审批请求 */}
      {pendingApprovals.map((request) => (
        <div
          key={request.request_id}
          className="bg-secondary/40 border border-warning/20 rounded-xl px-4 py-3 space-y-2 animate-slide-in"
          role="alert"
          aria-label={`审批请求: ${request.command}`}
        >
          {/* 头部 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Shield size={14} className="text-warning" aria-hidden="true" />
              <span className="text-xs font-medium text-warning">命令审批请求</span>
              <span className="text-xs text-muted-foreground font-mono">
                {request.request_id.slice(0, 8)}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock size={12} aria-hidden="true" />
              <span>来自 {request.session_id}</span>
            </div>
          </div>

          {/* 命令内容 */}
          <div className="flex items-start gap-2 px-3 py-2 rounded bg-card border border-border">
            <Terminal size={12} className="text-warning mt-0.5 flex-shrink-0" aria-hidden="true" />
            <code className="text-xs font-mono text-warning break-all">
              {request.command}
            </code>
          </div>

          {/* 工作目录 */}
          {request.workspace && (
            <div className="text-xs text-muted-foreground font-mono">
              cwd: {request.workspace}
            </div>
          )}

          {/* 倒计时 */}
          <CountdownBar expiresAt={request.expires_at} />

          {/* 操作按钮 */}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => onApprove(request.request_id)}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium
                bg-success/20 text-success border border-success/30
                hover:bg-success/30 transition-all cursor-pointer min-h-[44px]"
              aria-label={`批准命令: ${request.command}`}
            >
              <Check size={14} aria-hidden="true" />
              批准
            </button>
            <button
              onClick={() => onReject(request.request_id)}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium
                bg-destructive/20 text-destructive border border-destructive/30
                hover:bg-destructive/30 transition-all cursor-pointer min-h-[44px]"
              aria-label={`拒绝命令: ${request.command}`}
            >
              <X size={14} aria-hidden="true" />
              拒绝
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default memo(ApprovalPanel);
