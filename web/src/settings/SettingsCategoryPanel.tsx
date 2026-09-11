import {
  Folder, Brain, ChevronDown, Code, Cpu, Loader2, MessageCircle, Monitor, Moon,
  Puzzle, Server, SlidersHorizontal, Users, type LucideIcon,
} from "lucide-react";
import { useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { SettingsSectionTargetContext } from "./section-target-context";
import { useSettingsWorkspace } from "./SettingsWorkspace";

const CATEGORY_PRESENTATION: Record<string, { icon: LucideIcon; color: string }> = {
  appearance: { icon: Moon, color: "text-primary" },
  desktop: { icon: Monitor, color: "text-info" },
  models: { icon: Cpu, color: "text-primary" },
  agent: { icon: Users, color: "text-info" },
  roundtable: { icon: MessageCircle, color: "text-success" },
  coding: { icon: Code, color: "text-destructive" },
  compression: { icon: SlidersHorizontal, color: "text-warning" },
  memory: { icon: Brain, color: "text-primary" },
  workspace: { icon: Folder, color: "text-info" },
  system: { icon: Server, color: "text-warning" },
};

interface SettingsCategoryPanelProps {
  sectionId: string;
  title: string;
  description?: string;
  loading?: boolean;
  loadError?: string | null;
  onRetry?: () => void;
  headerActions?: ReactNode;
  headerMeta?: ReactNode;
  children?: ReactNode;
}

export function SettingsCategoryPanel({
  sectionId,
  title,
  description,
  loading,
  loadError,
  onRetry,
  headerActions,
  headerMeta,
  children,
}: SettingsCategoryPanelProps) {
  const { categoryErrors, stores } = useSettingsWorkspace();
  const targetId = useContext(SettingsSectionTargetContext);
  const saveError = categoryErrors[sectionId];
  const dirty = stores.some((store) => store.id === sectionId && store.dirty);
  const [expanded, setExpanded] = useState(sectionId === "appearance" || sectionId === "models");
  const panelRef = useRef<HTMLElement>(null);
  const { icon: Icon, color: iconColor } = CATEGORY_PRESENTATION[sectionId] || { icon: Puzzle, color: "text-info" };
  const contentId = `${sectionId}-content`;

  useEffect(() => {
    if (targetId !== sectionId) return;
    setExpanded(true);
    const frame = requestAnimationFrame(() => panelRef.current?.scrollIntoView({ block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [sectionId, targetId]);

  useEffect(() => {
    if (saveError || loadError) setExpanded(true);
  }, [saveError, loadError]);

  return (
    <section
      ref={panelRef}
      aria-labelledby={`${sectionId}-title`}
      className="min-w-0 scroll-mt-40 rounded-xl border border-border/50 bg-secondary/80"
    >
      <div className="flex items-center gap-3 px-5">
        <h2 className="min-w-0 flex-1">
          <button
            id={`${sectionId}-title`}
            type="button"
            aria-expanded={expanded}
            aria-controls={contentId}
            onClick={() => setExpanded((current) => !current)}
            className="flex min-h-14 w-full items-center gap-3 rounded-lg py-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Icon size={18} className={`shrink-0 ${iconColor}`} aria-hidden="true" />
            <span className="text-base font-semibold text-foreground">{title}</span>
            {headerMeta ? <span className="text-xs text-muted-foreground">{headerMeta}</span> : null}
            {dirty ? <span className="text-xs text-warning">已修改</span> : null}
            <ChevronDown size={18} className={`ml-auto shrink-0 text-muted-foreground ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
          </button>
        </h2>
        {expanded && headerActions ? <div className="shrink-0">{headerActions}</div> : null}
      </div>
      <div id={contentId} hidden={!expanded} className="px-5 pb-5">
        {description ? <p className="mb-4 text-sm text-muted-foreground">{description}</p> : null}
        {saveError ? (
          <p className="mb-4 text-sm text-destructive" role="alert">{saveError}</p>
        ) : null}
        {loadError ? (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-md border border-destructive/40 bg-destructive/5 p-3" role="alert">
            <p className="text-sm text-destructive">{loadError}</p>
            {onRetry ? (
              <Button type="button" variant="outline" size="sm" onClick={onRetry}>重试</Button>
            ) : null}
          </div>
        ) : null}
        {loading ? (
          <div className="flex min-h-32 items-center gap-2 text-sm text-muted-foreground" role="status">
            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
            正在加载
          </div>
        ) : children}
      </div>
    </section>
  );
}
