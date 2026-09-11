import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Loader2, Maximize2, Minimize2, Plus, Send, Square } from "lucide-react";

import type { MentionResource } from "../../lib/mention-resources";
import type { MessageAttachment } from "../../types";
import {
  findAdjacentToken,
  hasEditorContent,
  insertNewline,
  insertText,
  insertTokenAtRange,
  pointInside,
  placeCaretAfter,
  rangeAtPoint,
  readComposerMessage,
  replaceRangeWithToken,
  selectionRange,
} from "./composerEditorDom";
import { createResourceToken } from "./composerTokens";
import { shouldOfferComposerExpansion } from "./conversationComposerModel";
import { mentionOptionId, type MentionChoiceType } from "./mentionCatalog";
import { resolveComposerKey } from "./mentionKeyboard";
import { findMentionAtCaret, isSameMentionStart, type MentionMatch } from "./mentionQuery";
import MentionPicker from "./MentionPicker";
import { useComposerFileInsert } from "./useComposerFileInsert";
import { useMentionChoices } from "./useMentionChoices";

export interface ConversationComposerProps {
  sessionId: string | null;
  onSendMessage: (
    content: string,
    attachments?: MessageAttachment[],
  ) => boolean | void;
  onAbort?: () => void;
  isStreaming?: boolean;
  editable?: boolean;
  sendEnabled?: boolean;
  placeholder?: string;
  trailingControls?: ReactNode;
  variant?: "primary" | "compact";
  className?: string;
}

interface MentionUiState {
  layer: "types" | "resources";
  selectedType: MentionChoiceType | null;
  query: string;
  anchor: MentionMatch["anchor"];
  searchAll: boolean;
}

function clampIndex(index: number, length: number): number {
  if (length <= 0) return 0;
  return Math.min(Math.max(index, 0), length - 1);
}

export default function ConversationComposer({
  sessionId,
  onSendMessage,
  onAbort,
  isStreaming = false,
  editable = true,
  sendEnabled = true,
  placeholder = "输入消息...",
  trailingControls,
  variant = "primary",
  className = "",
}: ConversationComposerProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const fileSelectionRef = useRef<{ range: Range; mentionText?: string; sessionId: string } | null>(null);
  const editableRef = useRef(editable);
  const expandedRef = useRef(false);
  const composingRef = useRef(false);
  const mentionMatchRef = useRef<MentionMatch | null>(null);
  const dismissedMentionRef = useRef<Pick<MentionMatch, "startNode" | "startOffset"> | null>(null);
  const [hasContent, setHasContent] = useState(false);
  const [canExpand, setCanExpand] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [mention, setMention] = useState<MentionUiState | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const errorId = useId();
  const listboxId = useId();

  editableRef.current = editable;
  expandedRef.current = expanded;

  const { resources, typeOptions, selectedType, resourceType } = useMentionChoices(
    sessionId, mention?.query ?? "", mention?.searchAll ?? true,
    mention?.selectedType ?? null, Boolean(mention),
  );
  const mentionLayer = resourceType ? mention?.layer ?? "types" : "types";

  const refreshContentState = useCallback(() => {
    const editor = editorRef.current;
    const scroller = scrollRef.current;
    if (!editor) return;
    setHasContent(hasEditorContent(editor));
    if (!expandedRef.current && scroller) {
      setCanExpand(shouldOfferComposerExpansion(editor.scrollHeight, scroller.clientHeight));
    }
  }, []);

  const collapseComposer = useCallback(() => {
    expandedRef.current = false;
    setExpanded(false);
    window.requestAnimationFrame(refreshContentState);
  }, [refreshContentState]);

  const removeToken = useCallback((token: HTMLElement) => {
    if (!editableRef.current) return;
    token.remove();
    refreshContentState();
    editorRef.current?.focus();
  }, [refreshContentState]);

  const moveTokenAtPoint = useCallback((token: HTMLElement, x: number, y: number) => {
    const editor = editorRef.current;
    if (!editor || !editableRef.current || !pointInside(editor, x, y)) return;
    token.style.pointerEvents = "none";
    const range = rangeAtPoint(editor, x, y);
    token.style.pointerEvents = "";
    if (!range) return;
    insertTokenAtRange(range, token);
    placeCaretAfter(token);
    refreshContentState();
  }, [refreshContentState]);

  const tokenBehaviorRef = useRef({
    onRemove: removeToken,
    onMove: moveTokenAtPoint,
    onRefresh: refreshContentState,
    isEditable: () => editableRef.current,
  });
  tokenBehaviorRef.current = {
    onRemove: removeToken,
    onMove: moveTokenAtPoint,
    onRefresh: refreshContentState,
    isEditable: () => editableRef.current,
  };
  const tokenBehavior = useRef({
    onRemove: (token: HTMLElement) => tokenBehaviorRef.current.onRemove(token),
    onMove: (token: HTMLElement, x: number, y: number) => {
      tokenBehaviorRef.current.onMove(token, x, y);
    },
    onRefresh: () => tokenBehaviorRef.current.onRefresh(),
    isEditable: () => tokenBehaviorRef.current.isEditable(),
  }).current;

  const {
    pendingUploads,
    dragActive,
    attachmentError,
    insertBrowserFiles,
    handleBrowserDrop,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    resetFileInsert,
  } = useComposerFileInsert({
    sessionId,
    editable,
    editorRef,
    editableRef,
    tokenBehavior,
    refreshContentState,
  });

  const closeMention = useCallback((dismiss = false) => {
    if (dismiss) dismissedMentionRef.current = mentionMatchRef.current;
    mentionMatchRef.current = null;
    setMention(null);
    setActiveIndex(0);
  }, []);

  const syncMentionFromCaret = useCallback(() => {
    const editor = editorRef.current;
    if (!editor || composingRef.current || !editableRef.current) return;
    const match = findMentionAtCaret(editor);
    const previous = mentionMatchRef.current;
    mentionMatchRef.current = match;
    if (!match) {
      dismissedMentionRef.current = null;
      setMention(null);
      return;
    }
    if (isSameMentionStart(dismissedMentionRef.current, match)) return;
    dismissedMentionRef.current = null;
    const bounds = frameRef.current?.getBoundingClientRect();
    const anchor = bounds ? { ...match.anchor, top: bounds.top, bottom: bounds.bottom } : match.anchor;
    setMention((current) => {
      if (current && isSameMentionStart(previous, match)) {
        if (current.query === match.query
          && current.anchor.top === anchor.top
          && current.anchor.left === anchor.left
          && current.anchor.bottom === anchor.bottom) return current;
        const queryChanged = current.query !== match.query;
        return {
          ...current, query: match.query, anchor,
          ...(current.searchAll && queryChanged ? {
            layer: match.query.trim() ? "resources" as const : "types" as const,
            selectedType: null,
          } : {}),
        };
      }
      return {
        layer: match.query.trim() ? "resources" : "types",
        selectedType: null, query: match.query, anchor, searchAll: true,
      };
    });
  }, []);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor) return;
    editor.replaceChildren();
    expandedRef.current = false;
    dismissedMentionRef.current = null;
    mentionMatchRef.current = null;
    setHasContent(false);
    setCanExpand(false);
    setExpanded(false);
    setMention(null);
    setActiveIndex(0);
    resetFileInsert();
  }, [resetFileInsert, sessionId]);

  useEffect(() => {
    if (!editable) closeMention(true);
  }, [closeMention, editable]);

  const mentionOpen = Boolean(mention);
  useEffect(() => {
    if (!mentionOpen) return;
    const closeOnOutside = (event: PointerEvent | FocusEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (editorRef.current?.contains(target)
        || target.closest("[data-mention-picker]")?.getAttribute("data-mention-picker") === listboxId) return;
      closeMention(true);
    };
    document.addEventListener("pointerdown", closeOnOutside, true);
    document.addEventListener("focusin", closeOnOutside, true);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside, true);
      document.removeEventListener("focusin", closeOnOutside, true);
    };
  }, [closeMention, listboxId, mentionOpen]);

  useEffect(() => {
    const editor = editorRef.current;
    const scroller = scrollRef.current;
    if (!editor) return undefined;
    const observer = new ResizeObserver(() => {
      if (!expandedRef.current) refreshContentState();
    });
    observer.observe(editor);
    if (scroller) observer.observe(scroller);
    return () => observer.disconnect();
  }, [refreshContentState]);

  useEffect(() => {
    if (!expanded) return undefined;
    const closeOnOutside = (event: PointerEvent) => {
      const target = event.target as Element;
      if (!rootRef.current?.contains(target)
        && target.closest?.("[data-mention-picker]")?.getAttribute("data-mention-picker") !== listboxId) collapseComposer();
    };
    document.addEventListener("pointerdown", closeOnOutside, true);
    return () => document.removeEventListener("pointerdown", closeOnOutside, true);
  }, [collapseComposer, expanded, listboxId]);

  useEffect(() => {
    const handleSelectionChange = () => {
      const editor = editorRef.current;
      if (!editor || composingRef.current) return;
      const selection = window.getSelection();
      if (!selection?.anchorNode || !editor.contains(selection.anchorNode)) return;
      syncMentionFromCaret();
    };
    document.addEventListener("selectionchange", handleSelectionChange);
    return () => document.removeEventListener("selectionchange", handleSelectionChange);
  }, [syncMentionFromCaret]);

  useEffect(() => {
    const reposition = () => {
      if (!mention) return;
      syncMentionFromCaret();
    };
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [mention, syncMentionFromCaret]);

  const optionCount = mentionLayer === "types"
    ? typeOptions.length
    : resources.items.length + (resources.hasMore ? 1 : 0) + (resources.status === "error" ? 1 : 0);

  useEffect(() => {
    setActiveIndex(0);
  }, [mention?.query, resourceType]);

  const handleSend = useCallback(() => {
    const editor = editorRef.current;
    if (!editor || !editableRef.current || !sendEnabled || pendingUploads > 0) return;
    const message = readComposerMessage(editor);
    const content = message.content.trim();
    if (!content) return;
    const sent = onSendMessage(
      content,
      message.attachments.length > 0 ? message.attachments : undefined,
    );
    if (sent === false) return;
    editor.replaceChildren();
    expandedRef.current = false;
    mentionMatchRef.current = null;
    dismissedMentionRef.current = null;
    setHasContent(false);
    setCanExpand(false);
    setExpanded(false);
    resetFileInsert();
    setMention(null);
  }, [onSendMessage, pendingUploads, resetFileInsert, sendEnabled]);

  const insertResource = useCallback((resource: MentionResource) => {
    const editor = editorRef.current;
    if (!editor || !editableRef.current || !resource.available) return;
    const match = findMentionAtCaret(editor) ?? mentionMatchRef.current;
    if (!match) return;
    replaceRangeWithToken(
      match.range,
      createResourceToken(resource, tokenBehavior),
    );
    dismissedMentionRef.current = null;
    mentionMatchRef.current = null;
    setMention(null);
    setActiveIndex(0);
    refreshContentState();
    editor.focus();
  }, [refreshContentState, tokenBehavior]);

  const openMentionPicker = useCallback(() => {
    const editor = editorRef.current;
    if (!editor || !editableRef.current || !sessionId) return;
    const range = selectionRange(editor);
    const before = range.cloneRange();
    before.selectNodeContents(editor);
    before.setEnd(range.startContainer, range.startOffset);
    // Keep an explicit mention separate from an email-like English word prefix.
    const trigger = /[A-Za-z0-9._]$/.test(before.toString()) ? " @" : "@";
    editor.focus();
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    insertText(editor, trigger);
    dismissedMentionRef.current = null;
    mentionMatchRef.current = null;
    refreshContentState();
    syncMentionFromCaret();
  }, [refreshContentState, sessionId, syncMentionFromCaret]);

  const openFilePicker = useCallback(() => {
    const editor = editorRef.current;
    if (!editor || !editableRef.current || !sessionId) return;
    const match = findMentionAtCaret(editor) ?? mentionMatchRef.current;
    if (!match) return;
    fileSelectionRef.current = {
      range: match.range.cloneRange(),
      mentionText: match.range.toString(), sessionId,
    };
    closeMention(true);
    fileInputRef.current?.click();
  }, [closeMention, sessionId]);

  useEffect(() => {
    const input = fileInputRef.current;
    const cancel = () => {
      fileSelectionRef.current = null;
      editorRef.current?.focus();
    };
    input?.addEventListener("cancel", cancel);
    return () => input?.removeEventListener("cancel", cancel);
  }, []);

  const selectType = useCallback((nextType: MentionChoiceType, focus = true) => {
    if (!editableRef.current) return;
    if (nextType === "file" && focus) {
      openFilePicker();
      return;
    }
    setMention((current) => current ? {
      ...current, selectedType: nextType, layer: focus ? "resources" : "types",
      searchAll: focus ? current.searchAll && Boolean(current.query.trim()) : current.searchAll,
    } : current);
    setActiveIndex(0);
  }, [openFilePicker]);

  const confirmMention = useCallback(() => {
    if (!mention) return;
    if (mentionLayer === "types") {
      const option = typeOptions.find((option) => option.type === selectedType) ?? typeOptions[0];
      if (option) selectType(option.type);
      return;
    }
    if (resources.hasMore && activeIndex === resources.items.length) {
      resources.loadMore();
      return;
    }
    if (resources.status === "error"
      && activeIndex === resources.items.length + (resources.hasMore ? 1 : 0)) {
      resources.retry();
      return;
    }
    const resource = resources.items[activeIndex];
    if (resource?.available) insertResource(resource);
  }, [activeIndex, insertResource, mention, mentionLayer, resources, selectedType, selectType, typeOptions]);

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    if (!editableRef.current) return;
    const action = resolveComposerKey({
      key: event.key,
      shiftKey: event.shiftKey,
      altKey: event.altKey,
      metaKey: event.metaKey,
      ctrlKey: event.ctrlKey,
      isComposing: event.nativeEvent.isComposing || composingRef.current,
      keyCode: event.nativeEvent.keyCode,
      mentionOpen: Boolean(mention),
      mentionLayer: mention ? mentionLayer : null,
    });
    const editor = editorRef.current;

    switch (action.type) {
      case "pass":
        return;
      case "send":
        event.preventDefault();
        handleSend();
        return;
      case "newline":
        event.preventDefault();
        if (editor) {
          insertNewline(editor);
          refreshContentState();
          syncMentionFromCaret();
        }
        return;
      case "mention-move":
        event.preventDefault();
        if (mentionLayer === "types") {
          const index = Math.max(0, typeOptions.findIndex((option) => option.type === selectedType));
          const option = typeOptions[clampIndex(index + action.delta, typeOptions.length)];
          if (option) selectType(option.type, false);
        } else {
          setMention((current) => current ? { ...current, selectedType: resourceType } : current);
          setActiveIndex((index) => clampIndex(index + action.delta, optionCount));
        }
        return;
      case "mention-confirm":
        event.preventDefault();
        if (event.key === "ArrowRight" && !resourceType) return;
        confirmMention();
        return;
      case "mention-back":
        event.preventDefault();
        setMention((current) => current ? { ...current, layer: "types", selectedType: resourceType } : current);
        return;
      case "mention-close":
        event.preventDefault();
        closeMention(true);
        return;
      case "mention-tab": {
        closeMention(true);
        return;
      }
      case "delete-adjacent":
        if (!editor) return;
        {
          const token = findAdjacentToken(editor, action.direction);
          if (token) {
            event.preventDefault();
            removeToken(token);
            syncMentionFromCaret();
          }
        }
        return;
      default:
        return;
    }
  }, [
    closeMention,
    confirmMention,
    handleSend,
    mention,
    mentionLayer,
    optionCount,
    resourceType,
    selectedType,
    typeOptions,
    refreshContentState,
    removeToken,
    selectType,
    syncMentionFromCaret,
  ]);

  const handlePaste = useCallback((event: ClipboardEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!editorRef.current || !editableRef.current) return;
    insertText(editorRef.current, event.clipboardData.getData("text/plain"));
    refreshContentState();
    syncMentionFromCaret();
  }, [refreshContentState, syncMentionFromCaret]);

  const isCompact = variant === "compact";
  const canSubmit = editable && sendEnabled && hasContent && pendingUploads === 0;
  const activeTypeIndex = Math.max(0, typeOptions.findIndex((option) => option.type === selectedType));
  const activeListId = mentionLayer === "types" ? listboxId : `${listboxId}-resources`;
  const activeOptionIndex = mentionLayer === "types" ? activeTypeIndex : activeIndex;

  return (
    <div ref={rootRef} className={className}>
      <div
        ref={frameRef}
        data-composer-frame=""
        className={`${isCompact ? "rounded-lg bg-background" : "rounded-2xl bg-secondary/80"} border p-2.5 transition-[border-color,box-shadow] duration-200 focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/35 ${
          dragActive
            ? "border-primary ring-2 ring-primary/25"
            : "border-border/60"
        } ${editable ? "" : "opacity-50"}`}
      >
        <div className="relative">
          <div
            ref={scrollRef}
            className={`conversation-composer-scroll w-full overflow-y-auto ${
              expanded
                ? "h-[calc(50vh-4.25rem)] min-h-48"
                : isCompact
                  ? "max-h-[200px]"
                  : "max-h-32"
            }`}
          >
            <div
              ref={editorRef}
              role="textbox"
              aria-label="聊天消息输入"
              aria-multiline="true"
              aria-disabled={!editable}
              aria-describedby={attachmentError ? errorId : undefined}
              aria-autocomplete="list"
              aria-expanded={mentionOpen}
              aria-controls={mentionOpen ? activeListId : undefined}
              aria-activedescendant={mentionOpen && activeOptionIndex < optionCount
                ? mentionOptionId(activeListId, activeOptionIndex) : undefined}
              contentEditable={editable}
              suppressContentEditableWarning
              data-placeholder={placeholder}
              onInput={() => {
                refreshContentState();
                syncMentionFromCaret();
              }}
              onCompositionStart={() => {
                composingRef.current = true;
              }}
              onCompositionEnd={() => {
                composingRef.current = false;
                syncMentionFromCaret();
              }}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              onDragEnter={handleDragEnter}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleBrowserDrop}
              className={`conversation-composer-editor w-full overflow-hidden whitespace-pre-wrap break-words rounded-lg border-none bg-transparent px-2 py-1 text-sm text-foreground outline-none ${
                expanded
                  ? "min-h-full"
                  : isCompact
                    ? "min-h-11"
                    : "min-h-12"
              } ${canExpand || expanded ? "pr-11" : ""} ${editable ? "" : "cursor-not-allowed"}`}
            />
          </div>
          {canExpand || expanded ? (
            <button
              type="button"
              onPointerDown={(event) => event.preventDefault()}
              onClick={() => {
                if (expanded) collapseComposer();
                else setExpanded(true);
                window.requestAnimationFrame(() => editorRef.current?.focus());
              }}
              aria-label={expanded ? "收起输入框" : "展开输入框"}
              aria-pressed={expanded}
              title={expanded ? "收起输入框" : "展开输入框"}
              className="absolute right-1 top-1 flex h-8 w-8 items-center justify-center rounded-lg bg-muted/70 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
            >
              {expanded ? <Minimize2 size={15} aria-hidden="true" /> : <Maximize2 size={15} aria-hidden="true" />}
            </button>
          ) : null}
        </div>
        <div className="mt-2 flex min-h-10 items-center justify-between gap-2">
          <div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              tabIndex={-1}
              aria-hidden="true"
              className="hidden"
              onChange={(event) => {
                const selected = Array.from(event.target.files ?? []);
                const editor = editorRef.current;
                const pending = fileSelectionRef.current;
                fileSelectionRef.current = null;
                event.target.value = "";
                if (editor && editableRef.current && sessionId && selected.length > 0) {
                  if (pending && (pending.sessionId !== sessionId
                    || !editor.contains(pending.range.startContainer)
                    || !editor.contains(pending.range.endContainer))) return;
                  const range = pending?.range ?? selectionRange(editor);
                  if (pending?.mentionText !== undefined) {
                    if (range.toString() !== pending.mentionText) return;
                    range.deleteContents();
                  }
                  insertBrowserFiles(selected, range);
                }
              }}
            />
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={openMentionPicker}
              disabled={!editable || !sessionId}
              title="添加资源"
              aria-label="添加资源"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-muted text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Plus size={17} aria-hidden="true" />
            </button>
          </div>
          <div className="flex items-center justify-end gap-2">
            {trailingControls}
            {isStreaming && onAbort ? (
            <button
              type="button"
              onClick={onAbort}
              title="中止输出"
              aria-label="中止输出"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-destructive/20 text-destructive transition-colors duration-200 hover:bg-destructive/40"
            >
              <Square size={17} className="fill-current" aria-hidden="true" />
            </button>
            ) : (
            <button
              type="button"
              onClick={handleSend}
              disabled={!canSubmit}
              aria-label={pendingUploads > 0 ? "正在添加文件" : "发送消息"}
              className={`flex h-9 w-9 items-center justify-center rounded-full transition-colors duration-200 ${
                canSubmit
                  ? "bg-primary text-primary-foreground hover:bg-primary"
                  : "cursor-not-allowed bg-muted text-muted-foreground"
              }`}
            >
              {pendingUploads > 0 ? (
                <Loader2 size={17} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              ) : (
                <Send size={17} aria-hidden="true" />
              )}
            </button>
            )}
          </div>
        </div>
      </div>
      {attachmentError ? (
        <p id={errorId} className="mt-1 text-xs text-destructive" role="alert">
          {attachmentError}
        </p>
      ) : null}
      <MentionPicker
        open={mentionOpen}
        layer={mentionLayer}
        typeOptions={typeOptions}
        selectedType={selectedType}
        resourceType={resourceType}
        sessionId={sessionId}
        anchor={mention?.anchor ?? null}
        items={resources.items}
        status={resources.status}
        error={resources.error}
        hasMore={resources.hasMore}
        activeIndex={activeIndex}
        listboxId={listboxId}
        onActiveIndexChange={(index) => {
          setMention((current) => current ? { ...current, layer: "resources", selectedType: resourceType } : current);
          setActiveIndex(index);
        }}
        onSelectType={(type) => selectType(type)}
        onPreviewType={(type) => selectType(type, false)}
        onSelectResource={insertResource}
        onRetry={resources.retry}
        onLoadMore={resources.loadMore}
      />
    </div>
  );
}
