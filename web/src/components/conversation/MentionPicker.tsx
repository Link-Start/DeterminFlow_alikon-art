import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { ChevronRight, Loader2 } from "lucide-react";

import type { MentionResource } from "../../lib/mention-resources";
import type { MentionResourceType } from "../../types";
import { mentionOptionId, mentionTypeLabel, type MentionChoiceOption, type MentionChoiceType } from "./mentionCatalog";
import { ResourceIdentityIcon } from "./resourceIdentity";
import { layoutMentionPanel, type MentionAnchor } from "./mentionPanelPosition";
import type { MentionResourceStatus } from "./useMentionResources";

export interface MentionPickerProps {
  open: boolean;
  layer: "types" | "resources";
  typeOptions: readonly MentionChoiceOption[];
  selectedType: MentionChoiceType | null;
  resourceType: MentionResourceType | null;
  sessionId: string | null;
  anchor: MentionAnchor | null;
  items: MentionResource[];
  status: MentionResourceStatus;
  error: string | null;
  hasMore: boolean;
  activeIndex: number;
  listboxId: string;
  onActiveIndexChange: (index: number) => void;
  onSelectType: (type: MentionChoiceType) => void;
  onPreviewType: (type: MentionChoiceType) => void;
  onSelectResource: (resource: MentionResource) => void;
  onRetry: () => void;
  onLoadMore: () => void;
}

function optionClass(active: boolean, disabled = false): string {
  return [
    "flex w-full min-h-8 items-center justify-between gap-2 rounded px-2 py-1.5 text-left",
    disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer",
    active ? "bg-primary/10 text-foreground" : "text-foreground hover:bg-muted/70",
  ].join(" ");
}

const PANE_CLASS = "min-h-0 overflow-y-auto overscroll-contain rounded-md border border-border bg-popover p-1 shadow-sm";

export default function MentionPicker({
  open, layer, typeOptions, selectedType, resourceType, sessionId, anchor, items, status, error,
  hasMore, activeIndex, listboxId, onActiveIndexChange, onSelectType,
  onPreviewType, onSelectResource, onRetry, onLoadMore,
}: MentionPickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeTypeIndex = Math.max(0, typeOptions.findIndex((option) => option.type === selectedType));
  const resourcesId = `${listboxId}-resources`;
  const activeId = mentionOptionId(
    layer === "types" ? listboxId : resourcesId, layer === "types" ? activeTypeIndex : activeIndex,
  );
  useEffect(() => {
    if (!open) return;
    const option = document.getElementById(activeId);
    if (option && containerRef.current?.contains(option)) option.scrollIntoView({ block: "nearest" });
  }, [activeId, open, items, status]);

  if (!open || !anchor) return null;
  const viewport = typeof window === "undefined"
    ? { width: 1280, height: 800 }
    : { width: window.innerWidth, height: window.innerHeight };
  const layout = layoutMentionPanel(anchor, viewport, Boolean(resourceType));
  const retryIndex = items.length + (hasMore ? 1 : 0);
  const names = new Map<string, number>();
  for (const item of items) names.set(item.name, (names.get(item.name) ?? 0) + 1);
  const resourceActive = (index: number) => layer === "resources" && activeIndex === index;
  const panel = (
    <div
      ref={containerRef}
      data-mention-picker={listboxId}
      className="fixed z-50 flex items-end gap-1 text-xs leading-4 text-popover-foreground"
      style={{ bottom: layout.bottom, left: layout.left, maxHeight: layout.maxHeight }}
      onMouseDown={(event) => event.preventDefault()}
    >
      <div
        id={listboxId}
        role="listbox"
        aria-label="选择要引用的资源类型"
        className={PANE_CLASS}
        style={{ width: layout.typeWidth, maxHeight: layout.maxHeight }}
      >
        {typeOptions.length === 0 ? (
          <p className="px-2 py-2 text-muted-foreground" role="status">没有匹配的资源</p>
        ) : typeOptions.map((option, index) => {
          const selected = activeTypeIndex === index;
          const isFile = option.type === "file";
          const disabled = isFile && !sessionId;
          return (
            <div
              key={option.type}
              id={mentionOptionId(listboxId, index)}
              role="option"
              tabIndex={-1}
              aria-selected={selected}
              aria-disabled={disabled || undefined}
              aria-haspopup={isFile ? undefined : "listbox"}
              aria-expanded={isFile ? undefined : resourceType === option.type}
              aria-controls={resourceType === option.type ? resourcesId : undefined}
              className={optionClass(selected, disabled)}
              onMouseEnter={() => onPreviewType(option.type)}
              onClick={() => { if (!disabled) onSelectType(option.type); }}
            >
              <ResourceIdentityIcon type={option.type} />
              <span className="min-w-0 flex-1 truncate">{option.label}</span>
              {selected && !isFile ? <ChevronRight size={12} className="shrink-0" aria-hidden="true" /> : null}
            </div>
          );
        })}
      </div>
      {resourceType ? (
        <div
          id={resourcesId}
          role="listbox"
          aria-label={`选择要引用的${mentionTypeLabel(resourceType)}`}
          className={PANE_CLASS}
          style={{ width: layout.resourceWidth, maxHeight: layout.maxHeight }}
        >
          {!sessionId ? (
            <p className="px-2 py-2 text-muted-foreground" role="status">当前会话不可用</p>
          ) : (
            <>
              {items.map((item, index) => {
                const duplicate = (names.get(item.name) ?? 0) > 1;
                const detail = duplicate
                  ? [item.source, item.resource_id].filter(Boolean).join(" · ")
                  : item.description || item.source;
                return (
                  <div
                    key={`${item.resource_type}:${item.resource_id}`}
                    id={mentionOptionId(resourcesId, index)}
                    role="option"
                    tabIndex={-1}
                    aria-selected={resourceActive(index)}
                    aria-disabled={!item.available}
                    className={optionClass(resourceActive(index), !item.available)}
                    onMouseEnter={() => onActiveIndexChange(index)}
                    onClick={() => { if (item.available) onSelectResource(item); }}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{item.name}</span>
                      {detail ? (
                        <span className="block truncate text-muted-foreground" title={detail}>{detail}</span>
                      ) : null}
                      {!item.available && item.unavailable_reason ? (
                        <span className="block text-warning">{item.unavailable_reason}</span>
                      ) : null}
                    </span>
                  </div>
                );
              })}
              {status === "loading" ? (
                <div className="flex items-center gap-2 px-2 py-2 text-muted-foreground" role="status">
                  <Loader2 size={12} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  正在搜索
                </div>
              ) : null}
              {status === "empty" ? (
                <p className="px-2 py-2 text-muted-foreground" role="status">没有匹配的资源</p>
              ) : null}
              {hasMore ? (
                <div
                  id={mentionOptionId(resourcesId, items.length)}
                  role="option"
                  tabIndex={-1}
                  aria-selected={resourceActive(items.length)}
                  className={optionClass(resourceActive(items.length))}
                  onMouseEnter={() => onActiveIndexChange(items.length)}
                  onClick={onLoadMore}
                >加载更多</div>
              ) : null}
              {status === "error" ? (
                <>
                  <p className="px-2 py-1 text-destructive" role="alert">{error || "资源列表加载失败"}</p>
                  <div
                    id={mentionOptionId(resourcesId, retryIndex)}
                    role="option"
                    tabIndex={-1}
                    aria-selected={resourceActive(retryIndex)}
                    className={optionClass(resourceActive(retryIndex))}
                    onMouseEnter={() => onActiveIndexChange(retryIndex)}
                    onClick={onRetry}
                  >重试</div>
                </>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
  return typeof document === "undefined" ? panel : createPortal(panel, document.body);
}
