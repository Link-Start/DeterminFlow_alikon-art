import { memo, useState, useRef, useEffect } from "react";
import { Check, FileText, Filter, FolderCode, GripVertical, MessageSquare, X } from "lucide-react";
import WorkspaceExplorer from "./WorkspaceExplorer";
import SessionsPanel from "./SessionsPanel";
import PromptPanel from "./PromptPanel";
import { Session, SessionDetail } from "../types";
import { fetchSessionSystemPrompt } from "../lib/api";
import type { SessionCategory } from "../lib/session-catalog";

const SESSION_FILTERS: { key: SessionCategory; label: string }[] = [
  { key: "main", label: "Main 会话" },
  { key: "workflow", label: "Workflow 会话" },
  { key: "assistant", label: "助手会话" },
];

interface ResizableSidePanelProps {
  sidePanel: "sessions" | "prompt" | "workspace";
  setSidePanel: (panel: "sessions" | "prompt" | "workspace") => void;
  sortedSessions: Session[];
  viewingSessionId: string | null;
  mainSessionId: string | null;
  onViewSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string, e: React.MouseEvent) => void;
  onKillSession: (sessionId: string, e: React.MouseEvent) => void;
  onCreateSession: (agentType?: string) => void;
  llmContext: Awaited<ReturnType<typeof fetchSessionSystemPrompt>> | null;
  promptLoading: boolean;
  onRefreshPrompt: () => void;
  viewingSession: SessionDetail | null;
  sessions: Session[];
  mobileOpen: boolean;
  onMobileClose: () => void;
}

function ResizableSidePanel({
  sidePanel,
  setSidePanel,
  sortedSessions,
  viewingSessionId,
  mainSessionId,
  onViewSession,
  onDeleteSession,
  onKillSession,
  onCreateSession,
  llmContext,
  promptLoading,
  onRefreshPrompt,
  viewingSession,
  sessions,
  mobileOpen,
  onMobileClose,
}: ResizableSidePanelProps) {
  const [width, setWidth] = useState(320); // 默认 320px (w-80)
  const [isResizing, setIsResizing] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [visibleCategories, setVisibleCategories] = useState<Set<SessionCategory>>(
    () => new Set(["main"]),
  );
  const panelRef = useRef<HTMLDivElement>(null);
  const filterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!filterOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFilterOpen(false);
    };
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (filterRef.current && !filterRef.current.contains(event.target as Node)) {
        setFilterOpen(false);
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.removeEventListener("mousedown", closeOnOutsideClick);
    };
  }, [filterOpen]);

  const toggleCategory = (category: SessionCategory) => {
    setVisibleCategories((current) => {
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing) return;

      const newWidth = window.innerWidth - e.clientX;
      // 限制宽度在 280px 到 800px 之间
      const clampedWidth = Math.max(280, Math.min(800, newWidth));
      setWidth(clampedWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    if (isResizing) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizing]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const delta = e.key === 'ArrowLeft' ? -10 : 10;
      const newWidth = Math.max(280, Math.min(800, width + delta));
      setWidth(newWidth);
    }
  };

  return (
    <div
      ref={panelRef}
      id="chat-side-panel"
      className={`${mobileOpen ? "flex" : "hidden md:flex"} fixed inset-x-0 bottom-0 top-14 z-40 h-auto min-h-0 w-full min-w-0 max-w-none flex-col overflow-hidden border-l border-border bg-card md:relative md:inset-auto md:z-auto md:h-full md:min-w-[280px] md:max-w-[800px] md:w-[var(--panel-width)]`}
      style={{ "--panel-width": `${width}px` } as React.CSSProperties}
    >
      {/* Resize Handle */}
      <div
        onMouseDown={handleMouseDown}
        onKeyDown={handleKeyDown}
        role="separator"
        aria-orientation="vertical"
        aria-label="调整侧边面板宽度，使用左右箭头键调整"
        tabIndex={0}
        className={`absolute left-0 top-0 bottom-0 hidden w-1 cursor-col-resize hover:bg-primary/30 transition-colors z-10 group md:block ${
          isResizing ? "bg-primary/50" : ""
        }`}
      >
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
          <GripVertical size={16} className="text-primary" aria-hidden="true" />
        </div>
      </div>

      {/* Panel Tabs */}
      <div className="relative flex border-b border-border">
        <div className="flex min-w-0 flex-1" role="tablist" aria-label="侧边面板导航">
          {[
            { key: "sessions" as const, icon: MessageSquare, label: "会话" },
            { key: "prompt" as const, icon: FileText, label: "提示词" },
            { key: "workspace" as const, icon: FolderCode, label: "工作空间" },
          ].map(({ key, icon: Icon, label }) => (
            <button
              key={key}
              onClick={() => setSidePanel(key)}
              role="tab"
              aria-selected={sidePanel === key}
              aria-controls={`panel-${key}`}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition-colors cursor-pointer min-h-[44px] ${
                sidePanel === key
                  ? "text-primary border-b-2 border-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon size={14} aria-hidden="true" />
              {label}
            </button>
          ))}
        </div>
        {sidePanel === "sessions" && (
          <div ref={filterRef} className="relative flex items-center">
            <button
              type="button"
              onClick={() => setFilterOpen((open) => !open)}
              aria-haspopup="menu"
              aria-expanded={filterOpen}
              aria-label={`筛选会话类型，已选择 ${visibleCategories.size} 项`}
              className={`flex min-h-[44px] min-w-[44px] items-center justify-center gap-1 px-2 transition-colors ${
                filterOpen ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              }`}
            >
              <Filter size={15} aria-hidden="true" />
              <span className="text-[10px] tabular-nums" aria-hidden="true">{visibleCategories.size}</span>
            </button>
            {filterOpen && (
              <div
                role="menu"
                aria-label="会话类型"
                className="absolute right-0 top-[calc(100%+4px)] z-50 w-48 rounded-lg border border-border/70 bg-secondary p-1.5 shadow-xl"
              >
                {SESSION_FILTERS.map(({ key, label }) => {
                  const selected = visibleCategories.has(key);
                  return (
                    <button
                      key={key}
                      type="button"
                      role="menuitemcheckbox"
                      aria-checked={selected}
                      onClick={() => toggleCategory(key)}
                      className="flex min-h-[40px] w-full items-center gap-2 rounded-md px-2.5 text-left text-xs text-foreground transition-colors hover:bg-primary/10"
                    >
                      <span className={`flex h-4 w-4 items-center justify-center rounded border ${
                        selected ? "border-primary bg-primary text-white" : "border-border"
                      }`}>
                        {selected && <Check size={12} aria-hidden="true" />}
                      </span>
                      {label}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        )}
        <button
          type="button"
          onClick={onMobileClose}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center text-muted-foreground hover:bg-secondary hover:text-foreground md:hidden"
          aria-label="关闭侧边面板"
        >
          <X size={16} aria-hidden="true" />
        </button>
      </div>

      {/* Panel Content */}
      <div className="min-h-0 min-w-0 flex-1 overflow-hidden">
        {sidePanel === "sessions" && (
          <div id="panel-sessions" className="h-full" role="tabpanel" aria-label="会话面板">
            <SessionsPanel
              sessions={sortedSessions}
              viewingSessionId={viewingSessionId}
              mainSessionId={mainSessionId}
              onViewSession={(sessionId) => {
                onViewSession(sessionId);
                onMobileClose();
              }}
              onDeleteSession={onDeleteSession}
              onKillSession={onKillSession}
              onCreateSession={onCreateSession}
              visibleCategories={visibleCategories}
            />
          </div>
        )}
        {sidePanel === "prompt" && (
          <div id="panel-prompt" className="h-full min-h-0 min-w-0" role="tabpanel" aria-label="提示词面板">
            <PromptPanel
              llmContext={llmContext}
              loading={promptLoading}
              onRefresh={onRefreshPrompt}
              sessionId={viewingSessionId || mainSessionId || ""}
            />
          </div>
        )}
        {sidePanel === "workspace" && (
          <div id="panel-workspace" className="h-full" role="tabpanel" aria-label="工作空间面板">
            <WorkspaceExplorer
              sessionId={viewingSessionId || mainSessionId || null}
              workspacePath={
                viewingSession?.workspace_path ||
                sessions.find((s) => s.session_id === mainSessionId)?.workspace_path
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(ResizableSidePanel);
