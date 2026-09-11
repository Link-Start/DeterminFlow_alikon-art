import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Pin, Trash2, X, Plus, ChevronDown, ChevronRight, Zap } from "lucide-react";
import { Session } from "../types";
import { getStatusConfig, formatRelativeTime, truncate } from "../lib/utils-helpers";
import { useAgentTypes } from "../hooks/useAgentTypes";
import {
  collectPinnedItems,
  prunePinnedSessionIds,
  readPinnedSessionIds,
  shouldShowRegularSessionHeading,
  togglePinnedSessionId,
  writePinnedSessionIds,
} from "../lib/session-pins";
import { canDeleteMainSession } from "./sessionPolicy";
import { partitionSessions, type SessionCategory } from "../lib/session-catalog";

type SessionGroup = {
  main: Session;
  category: SessionCategory;
  subs: Session[];
};

type PinnableEntry =
  | { id: string; kind: "group"; group: SessionGroup }
  | { id: string; kind: "assistant"; session: Session };

interface SessionsPanelProps {
  sessions: Session[];
  viewingSessionId: string | null;
  mainSessionId: string | null;
  onViewSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string, e: React.MouseEvent) => void;
  onKillSession: (sessionId: string, e: React.MouseEvent) => void;
  onCreateSession: (agentType?: string) => void;
  visibleCategories: Set<SessionCategory>;
}

function isWorkflowMain(session: Session): boolean {
  return session.type === "main" && (
    session.runtime_scope === "workflow" ||
    (session.task || "").startsWith("Workflow:")
  );
}

function SessionGroupHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="px-1 text-[13px] font-medium text-muted-foreground">
      {children}
    </h2>
  );
}

const AGENT_TYPE_LABELS: Record<string, string> = {
  main: "通用助手",
  coder: "编码助手",
  reviewer: "审查助手",
  researcher: "研究助手",
  reader: "阅读助手",
  default: "默认助手",
};

function SessionMetaAction({
  label,
  pressed,
  tone = "neutral",
  onClick,
  children,
}: {
  label: string;
  pressed?: boolean;
  tone?: "neutral" | "danger" | "warning";
  onClick: (event: React.MouseEvent) => void;
  children: React.ReactNode;
}) {
  const toneClass = tone === "danger"
    ? "hover:text-destructive"
    : tone === "warning"
      ? "hover:text-warning"
      : "hover:text-foreground";
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onClick(event);
      }}
      aria-label={label}
      aria-pressed={pressed}
      className={`flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-muted ${toneClass}`}
    >
      {children}
    </button>
  );
}

function SessionCard({
  session, isViewing, isSub, isAssistant = false, canDelete, canKill, canPin = false, pinned = false,
  onViewSession, onDeleteSession, onKillSession, onTogglePin,
}: {
  session: Session; isViewing: boolean;
  isSub: boolean; isAssistant?: boolean; canDelete: boolean; canKill: boolean;
  canPin?: boolean; pinned?: boolean;
  onViewSession: (id: string) => void;
  onDeleteSession: (id: string, e: React.MouseEvent) => void;
  onKillSession: (id: string, e: React.MouseEvent) => void;
  onTogglePin?: (id: string, e: React.MouseEvent) => void;
}) {
  const cfg = getStatusConfig(session.status);
  const wfMain = isWorkflowMain(session);
  const label = session.type === "main"
    ? (wfMain ? "WF-MAIN" : "MAIN")
    : (isAssistant ? "ASST" : "SUB");

  return (
    <div
      key={session.session_id}
      role="button"
      tabIndex={0}
      onClick={() => onViewSession(session.session_id)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onViewSession(session.session_id); } }}
      aria-label={`${isAssistant ? "助手会话" : session.type === "main" ? "主会话" : "子会话"} ${session.session_id}，${session.task || ""}`}
      className={`bg-secondary/50 border border-border/50 rounded-lg transition-all cursor-pointer group relative ${
        isSub ? "px-1.5 py-1 ml-4" : "px-3 py-2.5"
      } ${
        isViewing
          ? "border-primary/60 bg-primary/10 shadow-lg shadow-primary/10"
          : "hover:border-primary/30"
      }`}
    >
      {isViewing && (
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-6 bg-primary rounded-r" />
      )}

      <div className={`flex items-center justify-between gap-2 ${isSub ? "mb-0.5" : "mb-1"}`}>
        <div className="flex min-w-0 items-center gap-1.5">
          <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${cfg.dotColor}`} aria-hidden="true" />
          <span className="truncate font-mono text-xs text-info">
            {session.session_id}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {isViewing ? (
            <Badge variant="outline" className="h-5 px-1.5 py-0 text-xs font-medium text-primary border-primary/30">查看中</Badge>
          ) : null}
          <Badge
            variant="outline"
            className={`h-5 px-1.5 py-0 text-xs font-medium ${wfMain ? "text-primary border-primary/30" : cfg.color} border-current/30`}
          >
            {label}
          </Badge>
        </div>
      </div>

      <div className="flex min-h-5 min-w-0 items-center gap-1.5">
        <p className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {truncate(session.task || (session.type === "main" ? "主会话" : ""), isSub ? 30 : 60)}
        </p>
        {session.agent_type && session.agent_type !== "main" ? (
          <Badge
            variant="outline"
            title={session.agent_type}
            className="h-5 max-w-20 shrink-0 overflow-hidden px-1.5 py-0 text-xs font-medium text-info border-info/30"
          >
            <span className="truncate">{session.agent_type}</span>
          </Badge>
        ) : null}
      </div>

      <div className={`flex items-center justify-between gap-2 text-xs text-muted-foreground ${isSub ? "mt-0.5" : "mt-1.5"}`}>
        <span className="min-w-0 truncate">{session.message_count} 条消息</span>
        <div className="relative shrink-0">
          <span>{formatRelativeTime(session.updated_at)}</span>
          <div className="pointer-events-none absolute inset-y-0 right-full z-10 mr-1 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
            {canPin && onTogglePin ? (
              <SessionMetaAction
                label={pinned ? `取消置顶 ${session.session_id}` : `置顶 ${session.session_id}`}
                pressed={pinned}
                onClick={(event) => onTogglePin(session.session_id, event)}
              >
                <Pin size={12} className={pinned ? "fill-current" : undefined} />
              </SessionMetaAction>
            ) : null}
            {canKill ? (
              <SessionMetaAction
                label={`终止会话 ${session.session_id}`}
                tone="warning"
                onClick={(event) => onKillSession(session.session_id, event)}
              >
                <X size={12} />
              </SessionMetaAction>
            ) : null}
            {canDelete ? (
              <SessionMetaAction
                label={`删除会话 ${session.session_id}`}
                tone="danger"
                onClick={(event) => onDeleteSession(session.session_id, event)}
              >
                <Trash2 size={12} />
              </SessionMetaAction>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SessionsPanel({
  sessions, viewingSessionId, mainSessionId,
  onViewSession, onDeleteSession, onKillSession, onCreateSession, visibleCategories,
}: SessionsPanelProps) {
  const [collapsedMains, setCollapsedMains] = useState<Set<string>>(new Set());
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const { agentTypes } = useAgentTypes({ endpoint: "/api/agent-types", filterSubSessionOnly: true });
  const dropdownRef = useRef<HTMLDivElement>(null);
  const collapseInitializedRef = useRef(false);

  // 首次加载 sessions 后，默认折叠所有有子会话的 main
  useEffect(() => {
    if (collapseInitializedRef.current) return;
    const mains = sessions.filter(s => s.type === "main");
    const subs = sessions.filter(s => s.type === "sub");
    const mainIdsWithSubs = new Set(
      mains.filter(m => subs.some(sub => sub.parent_id === m.session_id)).map(m => m.session_id)
    );
    if (mainIdsWithSubs.size > 0) {
      setCollapsedMains(mainIdsWithSubs);
      collapseInitializedRef.current = true;
    }
  }, [sessions]);

  // 外部点击关闭下拉菜单 + Escape 关闭
  useEffect(() => {
    if (!dropdownOpen) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDropdownOpen(false);
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKey);
    };
  }, [dropdownOpen]);

  const catalog = useMemo(() => partitionSessions(sessions), [sessions]);
  const groups = useMemo(
    () => catalog.groups.filter(({ category }) => visibleCategories.has(category)),
    [catalog.groups, visibleCategories],
  );
  const assistants = visibleCategories.has("assistant") ? catalog.assistants : [];
  const knownSessionIds = useMemo(
    () => sessions.map((session) => session.session_id),
    [sessions],
  );
  const [pinnedIds, setPinnedIds] = useState(readPinnedSessionIds);

  useEffect(() => {
    writePinnedSessionIds(pinnedIds);
  }, [pinnedIds]);

  useEffect(() => {
    if (knownSessionIds.length === 0) return;
    setPinnedIds((current) => {
      const next = prunePinnedSessionIds(current, knownSessionIds);
      return next.length === current.length && next.every((id, index) => id === current[index])
        ? current
        : next;
    });
  }, [knownSessionIds]);

  const pinnableEntries = useMemo<PinnableEntry[]>(() => [
    ...groups.map((group) => ({ id: group.main.session_id, kind: "group" as const, group })),
    ...assistants.map((session) => ({ id: session.session_id, kind: "assistant" as const, session })),
  ], [assistants, groups]);
  const pinnedEntries = useMemo(
    () => collectPinnedItems(pinnableEntries, (entry) => entry.id, pinnedIds),
    [pinnableEntries, pinnedIds],
  );
  const pinnedIdSet = useMemo(
    () => new Set(pinnedEntries.map((entry) => entry.id)),
    [pinnedEntries],
  );
  const restGroups = groups.filter((group) => !pinnedIdSet.has(group.main.session_id));
  const restAssistants = assistants.filter((session) => !pinnedIdSet.has(session.session_id));
  const showRegularHeading = shouldShowRegularSessionHeading(pinnedEntries.length, restGroups.length);
  const displayedCount = groups.length + assistants.length;

  const handleTogglePin = useCallback((sessionId: string, event: React.MouseEvent) => {
    event.stopPropagation();
    setPinnedIds((current) => togglePinnedSessionId(current, sessionId));
  }, []);

  const renderAssistant = (assistant: Session) => (
    <SessionCard
      key={assistant.session_id}
      session={assistant}
      isViewing={viewingSessionId === assistant.session_id}
      isSub={false}
      isAssistant
      canDelete={assistant.status !== "running" && assistant.status !== "streaming"}
      canKill={assistant.status === "running" || assistant.status === "waiting" || assistant.status === "streaming"}
      canPin
      pinned={pinnedIdSet.has(assistant.session_id)}
      onViewSession={onViewSession}
      onDeleteSession={onDeleteSession}
      onKillSession={onKillSession}
      onTogglePin={handleTogglePin}
    />
  );

  const renderGroup = ({ main, subs }: SessionGroup) => {
    const isViewing = viewingSessionId === main.session_id;
    const canDelete = canDeleteMainSession(main, mainSessionId);
    const isCollapsed = collapsedMains.has(main.session_id);

    return (
      <div key={main.session_id} className="space-y-1">
        <div className="flex items-start gap-1">
          <div className="flex w-4 shrink-0 justify-center pt-2.5">
            {subs.length > 0 ? (
              <button
                type="button"
                onClick={(e) => toggleCollapse(main.session_id, e)}
                aria-expanded={!isCollapsed}
                aria-label={isCollapsed ? `展开 ${subs.length} 个子会话` : "折叠子会话"}
                className="relative flex h-4 w-4 items-center justify-center rounded hover:bg-secondary transition-colors cursor-pointer"
              >
                <span className="absolute -inset-3" aria-hidden="true" />
                {isCollapsed
                  ? <ChevronRight size={12} className="text-muted-foreground" />
                  : <ChevronDown size={12} className="text-muted-foreground" />}
              </button>
            ) : null}
          </div>
          <div className="min-w-0 flex-1">
            <SessionCard
              session={main}
              isViewing={isViewing}
              isSub={false}
              canDelete={canDelete}
              canKill={false}
              canPin
              pinned={pinnedIdSet.has(main.session_id)}
              onViewSession={onViewSession}
              onDeleteSession={onDeleteSession}
              onKillSession={onKillSession}
              onTogglePin={handleTogglePin}
            />
          </div>
        </div>

        {isCollapsed && subs.length > 0 && (
          <div
            className="relative ml-4 cursor-pointer group"
            role="button"
            tabIndex={0}
            onClick={(e) => toggleCollapse(main.session_id, e)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCollapse(main.session_id, e); } }}
            aria-label={`展开 ${subs.length} 个子会话`}
          >
            <div className="relative h-6">
              <div className="absolute inset-x-0 top-0 z-30 h-[20px] rounded-lg border border-primary/15 bg-secondary/60" />
              <div className="absolute left-[3px] right-[3px] top-[2px] z-20 h-[18px] rounded-lg border border-primary/10 bg-secondary/40" />
              <div className="absolute left-[6px] right-[6px] top-[4px] z-10 h-[16px] rounded-lg border border-primary/5 bg-secondary/20" />
            </div>
            <Badge variant="outline" className="absolute -right-1 top-1/2 -translate-y-1/2 text-xs text-primary border-primary/30 bg-card/80">
              +{subs.length}
            </Badge>
          </div>
        )}

        {!isCollapsed && subs.map((sub) => {
          const subViewing = viewingSessionId === sub.session_id;
          const canKillSub = sub.status === "running" || sub.status === "waiting" || sub.status === "streaming";
          const subCanDelete = sub.status !== "running";
          return (
            <SessionCard
              key={sub.session_id}
              session={sub}
              isViewing={subViewing}
              isSub={true}
              canDelete={subCanDelete}
              canKill={canKillSub}
              onViewSession={onViewSession}
              onDeleteSession={onDeleteSession}
              onKillSession={onKillSession}
            />
          );
        })}
      </div>
    );
  };

  const toggleCollapse = (mainId: string, e: React.SyntheticEvent) => {
    e.stopPropagation();
    setCollapsedMains(prev => {
      const next = new Set(prev);
      if (next.has(mainId)) next.delete(mainId);
      else next.add(mainId);
      return next;
    });
  };

  const handleCreateWithType = useCallback((agentType: string) => {
    onCreateSession(agentType);
    setDropdownOpen(false);
  }, [onCreateSession]);

  return (
    <ScrollArea className="h-full">
      <div className="px-3 py-2 space-y-2">
        {/* Split Button */}
        <div className="relative" ref={dropdownRef}>
          <div className="flex rounded-lg overflow-hidden">
            {/* 左侧主按钮 */}
            <button
              type="button"
              onClick={() => { onCreateSession("main"); setDropdownOpen(false); }}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 bg-primary/15 text-primary hover:bg-primary/25 transition-colors text-xs font-medium cursor-pointer"
            >
              <Plus size={14} />
              新建会话
            </button>
            {/* 右侧下拉触发按钮 */}
            <button
              type="button"
              onClick={() => setDropdownOpen((prev) => !prev)}
              aria-haspopup="menu"
              aria-expanded={dropdownOpen}
              aria-label="选择会话类型"
              className="px-2 py-2 bg-primary/15 text-primary hover:bg-primary/25 transition-colors border-l border-primary/30 cursor-pointer"
            >
              <ChevronDown size={14} className={`transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
            </button>
          </div>

          {/* 下拉菜单 */}
          {dropdownOpen && (
            <div className="absolute left-0 right-0 mt-1 z-50 max-h-64 overflow-y-auto rounded-lg bg-secondary border border-border/60 shadow-xl py-1" role="menu" aria-label="选择会话类型">
              {agentTypes.map((t) => (
                <button
                  key={t.agent_type}
                  onClick={() => handleCreateWithType(t.agent_type)}
                  role="menuitem"
                  className="w-full flex items-start gap-3 px-3 py-2 text-left hover:bg-primary/10 transition-colors cursor-pointer"
                >
                  <Zap size={14} className="mt-0.5 text-primary flex-shrink-0" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground">
                      {AGENT_TYPE_LABELS[t.agent_type] || t.agent_type}
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {t.description || t.agent_type}
                    </div>
                  </div>
                </button>
              ))}
              {agentTypes.length === 0 && (
                <div className="px-3 py-2 text-xs text-muted-foreground text-center">
                  暂无可用类型
                </div>
              )}
            </div>
          )}
        </div>

        {pinnedEntries.length > 0 ? (
          <section className="space-y-2" aria-labelledby="pinned-sessions-heading">
            <SessionGroupHeading id="pinned-sessions-heading">置顶</SessionGroupHeading>
            {pinnedEntries.map((entry) => (
              entry.kind === "group"
                ? renderGroup(entry.group)
                : renderAssistant(entry.session)
            ))}
          </section>
        ) : null}

        {showRegularHeading ? (
          <section className="space-y-2" aria-labelledby="regular-sessions-heading">
            <SessionGroupHeading id="regular-sessions-heading">常规会话</SessionGroupHeading>
            {restGroups.map((group) => renderGroup(group))}
          </section>
        ) : restGroups.map((group) => renderGroup(group))}

        {restAssistants.length > 0 && (
          <section className="space-y-1.5 pt-2" aria-labelledby="extension-sessions-heading">
            <div className="flex items-center justify-between border-t border-border/60 px-1 pt-3">
              <div>
                <h2 id="extension-sessions-heading" className="text-xs font-medium text-foreground">
                  外部助手
                </h2>
                <p className="text-[11px] text-muted-foreground">Extension Sessions</p>
              </div>
              <Badge variant="outline" className="text-xs text-info border-info/30">
                {restAssistants.length}
              </Badge>
            </div>
            {restAssistants.map((assistant) => renderAssistant(assistant))}
          </section>
        )}

        {displayedCount === 0 && (
          <div className="text-center text-muted-foreground text-sm py-4">
            {sessions.length === 0 ? "暂无会话" : "当前筛选下暂无会话"}
          </div>
        )}
      </div>
    </ScrollArea>
  );
}
