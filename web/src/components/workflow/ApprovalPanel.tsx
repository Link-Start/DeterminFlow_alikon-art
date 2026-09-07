/**
 * ApprovalPanel — 审批节点决策面板
 *
 * 在任务执行时审批节点激活时从右侧弹出。
 * 包含：文件查看器（内联 MarkdownViewer）+ 驳回原因输入 + 通过/驳回按钮。
 */
import { useState } from "react";
import { Check, X, FileText, ChevronDown, ChevronRight, AlertCircle } from "lucide-react";
import { MarkdownViewer } from "../shared";
import { resolveApproval } from "../../lib/api";
import type { ApprovalFileInfo, NodeExecutionInfo } from "../../types";
import NodeFailureRuntimePanel from "./NodeFailureRuntimePanel";

interface ApprovalPanelProps {
  workflowId: string;
  taskId: string;
  nodeId: string;
  nodeLabel: string;
  files: ApprovalFileInfo[];
  placeholder: string;
  nodeState?: NodeExecutionInfo;
  onClose: () => void;
  onResolved: (approved: boolean, reason: string) => void;
}

export default function ApprovalPanel({
  workflowId,
  taskId,
  nodeId,
  nodeLabel,
  files,
  placeholder,
  nodeState,
  onClose,
  onResolved,
}: ApprovalPanelProps) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [expandedFiles, setExpandedFiles] = useState<Set<number>>(
    new Set(files.length > 0 ? [0] : []),
  );

  const toggleFile = (idx: number) => {
    setExpandedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const handleAction = async (approved: boolean) => {
    setSubmitting(true);
    try {
      await resolveApproval(workflowId, taskId, nodeId, approved, reason);
      onResolved(approved, reason);
    } catch {
      // keep panel open on error
    } finally {
      setSubmitting(false);
    }
  };

  const hasFiles = files.some((f) => f.exists && f.content);
  const canResolve = !nodeState || nodeState.status === "waiting_approval";

  return (
    <div className="flex flex-col h-full bg-card">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-primary/10 shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-foreground">审批节点</h3>
          <p className="text-xs text-muted-foreground mt-0.5">{nodeLabel}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="关闭审批面板"
          className="p-1.5 rounded-lg hover:bg-primary/10 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>

      {nodeState && (
        <NodeFailureRuntimePanel
          workflowId={workflowId}
          taskId={taskId}
          nodeId={nodeId}
          nodeState={nodeState}
        />
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Status banner */}
        {canResolve && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-warning/5 border border-warning/10">
            <AlertCircle size={16} className="text-warning shrink-0" aria-hidden="true" />
            <span className="text-xs text-warning">
              此节点需要人工审批才能继续执行
            </span>
          </div>
        )}

        {/* Files section */}
        {hasFiles ? (
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <FileText size={14} className="shrink-0" aria-hidden="true" />
              <span>查看文件 ({files.length})</span>
            </div>
            {files.map((file, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-primary/10 overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => toggleFile(idx)}
                  aria-expanded={expandedFiles.has(idx)}
                  aria-label={`展开/折叠文件 ${file.path}`}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-background hover:bg-primary/5 transition-colors text-left cursor-pointer"
                >
                  {expandedFiles.has(idx) ? (
                    <ChevronDown size={14} className="text-muted-foreground shrink-0" aria-hidden="true" />
                  ) : (
                    <ChevronRight size={14} className="text-muted-foreground shrink-0" aria-hidden="true" />
                  )}
                  <span className="text-xs text-foreground truncate font-mono">
                    {file.path}
                  </span>
                  {!file.exists && (
                    <span className="text-xs text-destructive ml-auto">不存在</span>
                  )}
                </button>
                {expandedFiles.has(idx) && (
                  <div className="border-t border-primary/10">
                    <MarkdownViewer
                      content={file.content}
                      fileName={file.path}
                      height="300px"
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground italic">
            此审批节点未配置要查看的文件
          </p>
        )}

        {/* Rejection reason */}
        {canResolve && <div>
          <label htmlFor="approval-reason" className="block text-xs font-medium text-muted-foreground mb-1.5">
            驳回原因（驳回时必填）
          </label>
          <textarea
            id="approval-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 rounded-lg bg-background border border-primary/20 text-foreground text-sm focus:outline-none focus:border-primary/50 transition-colors resize-none min-h-[44px]"
            placeholder={placeholder}
          />
        </div>}
      </div>

      {/* Footer: action buttons */}
      {canResolve && <div className="p-4 border-t border-primary/10 space-y-2 shrink-0">
        <button
          type="button"
          onClick={() => handleAction(true)}
          disabled={submitting}
          aria-label="通过审批"
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-success hover:bg-success disabled:opacity-50 text-white text-sm font-medium transition-colors cursor-pointer min-h-[44px]"
        >
          <Check size={16} aria-hidden="true" />
          {submitting ? "提交中..." : "通过"}
        </button>
        <button
          type="button"
          onClick={() => handleAction(false)}
          disabled={submitting}
          aria-label="驳回审批"
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg bg-destructive/10 hover:bg-destructive/20 disabled:opacity-50 text-destructive text-sm font-medium border border-destructive/20 transition-colors cursor-pointer min-h-[44px]"
        >
          <X size={16} aria-hidden="true" />
          {submitting ? "提交中..." : "驳回"}
        </button>
      </div>}
    </div>
  );
}
