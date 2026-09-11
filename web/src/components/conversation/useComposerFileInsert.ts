import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type RefObject,
} from "react";

import { uploadWorkspaceAttachment } from "../../lib/api";
import { isDesktopRuntime } from "../../lib/desktop-update";
import {
  insertTokenAtRange,
  pointInside,
  rangeAtPoint,
} from "./composerEditorDom";
import { createFileToken, markFileTokenReady } from "./composerTokens";
import { getDroppedFileName } from "./conversationComposerModel";

interface TokenBehavior {
  onRemove: (token: HTMLElement) => void;
  onMove: (token: HTMLElement, x: number, y: number) => void;
  onRefresh: () => void;
  isEditable: () => boolean;
}

export function useComposerFileInsert(options: {
  sessionId: string | null;
  editable: boolean;
  editorRef: RefObject<HTMLDivElement>;
  editableRef: { current: boolean };
  tokenBehavior: TokenBehavior;
  refreshContentState: () => void;
}) {
  const {
    sessionId,
    editable,
    editorRef,
    editableRef,
    tokenBehavior,
    refreshContentState,
  } = options;
  const dragDepthRef = useRef(0);
  const generationRef = useRef(0);
  const [pendingUploads, setPendingUploads] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);

  useEffect(() => () => { generationRef.current += 1; }, []);

  const insertNativePaths = useCallback((paths: string[], x: number, y: number) => {
    const editor = editorRef.current;
    if (!editor || !editableRef.current || !pointInside(editor, x, y)) return;
    let range = rangeAtPoint(editor, x, y);
    if (!range) return;
    for (const path of paths) {
      range = insertTokenAtRange(
        range,
        createFileToken(getDroppedFileName(path), tokenBehavior, path),
      );
    }
    editor.focus();
    refreshContentState();
    setAttachmentError(null);
  }, [editableRef, editorRef, refreshContentState, tokenBehavior]);

  useEffect(() => {
    if (!isDesktopRuntime()) return undefined;
    let disposed = false;
    let unlisten: (() => void) | undefined;

    void import("@tauri-apps/api/webview")
      .then(({ getCurrentWebview }) => getCurrentWebview().onDragDropEvent((event) => {
        const editor = editorRef.current;
        if (!editor || !editableRef.current) return;
        if (event.payload.type === "leave") {
          setDragActive(false);
          return;
        }
        const scale = window.devicePixelRatio || 1;
        const x = event.payload.position.x / scale;
        const y = event.payload.position.y / scale;
        const inside = pointInside(editor, x, y);
        setDragActive(inside);
        if (event.payload.type === "drop") {
          setDragActive(false);
          if (inside) insertNativePaths(event.payload.paths, x, y);
        }
      }))
      .then((cleanup) => {
        if (disposed) cleanup();
        else unlisten = cleanup;
      })
      .catch(() => {
        if (!disposed) setAttachmentError("桌面文件拖入暂不可用");
      });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [editableRef, editorRef, insertNativePaths]);

  const insertBrowserFiles = useCallback((files: File[], initialRange: Range) => {
    const editor = editorRef.current;
    if (!editor || !editable || !sessionId || files.length === 0) return;

    let range = initialRange;
    const generation = generationRef.current;
    setAttachmentError(null);
    setPendingUploads((count) => count + files.length);

    for (const file of files) {
      const token = createFileToken(file.name, tokenBehavior);
      range = insertTokenAtRange(range, token);
      void uploadWorkspaceAttachment(sessionId, file)
        .then((attachment) => {
          if (generationRef.current !== generation || !editor.contains(token)) return;
          markFileTokenReady(token, attachment.name, attachment.absolute_path);
        })
        .catch(() => {
          if (generationRef.current !== generation || !editor.contains(token)) return;
          token.remove();
          setAttachmentError(`文件 ${file.name} 添加失败，请重试`);
        })
        .finally(() => {
          if (generationRef.current !== generation) return;
          setPendingUploads((count) => Math.max(0, count - 1));
          refreshContentState();
        });
    }
    editor.focus();
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    refreshContentState();
  }, [editable, editorRef, refreshContentState, sessionId, tokenBehavior]);

  const handleBrowserDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = 0;
    setDragActive(false);
    const files = Array.from(event.dataTransfer.files);
    const editor = editorRef.current;
    if (!editor) return;
    const range = rangeAtPoint(editor, event.clientX, event.clientY);
    if (!range) return;
    insertBrowserFiles(files, range);
  }, [editorRef, insertBrowserFiles]);

  const handleDragEnter = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!editable || !event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    dragDepthRef.current += 1;
    setDragActive(true);
  }, [editable]);

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!editable || !event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, [editable]);

  const handleDragLeave = useCallback(() => {
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragActive(false);
  }, []);

  const resetFileInsert = useCallback(() => {
    generationRef.current += 1;
    dragDepthRef.current = 0;
    setPendingUploads(0);
    setDragActive(false);
    setAttachmentError(null);
  }, []);

  return {
    pendingUploads,
    dragActive,
    attachmentError,
    insertBrowserFiles,
    handleBrowserDrop,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    resetFileInsert,
  };
}
