import type { MentionResourceType } from "../../types";
import { moveTokenByKeyboard } from "./composerEditorDom";
import { mentionTypeLabel } from "./mentionCatalog";
import { createResourceIdentityIcon, resourceChipClass } from "./resourceIdentity";

const CHIP_CLASS = [
  "outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
].join(" ");

interface TokenBehavior {
  onRemove: (token: HTMLElement) => void;
  onMove: (token: HTMLElement, x: number, y: number) => void;
  onRefresh: () => void;
  isEditable: () => boolean;
}

function attachTokenBehaviors(token: HTMLElement, behavior: TokenBehavior) {
  token.addEventListener("keydown", (event) => {
    event.stopPropagation();
    if (!behavior.isEditable()) return;
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      behavior.onRemove(token);
    } else if (event.altKey && event.key === "ArrowLeft") {
      event.preventDefault();
      moveTokenByKeyboard(token, "left");
      behavior.onRefresh();
    } else if (event.altKey && event.key === "ArrowRight") {
      event.preventDefault();
      moveTokenByKeyboard(token, "right");
      behavior.onRefresh();
    }
  });
  token.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !behavior.isEditable()) return;
    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    let moved = false;

    const handleMove = (moveEvent: PointerEvent) => {
      if (Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 4) return;
      moved = true;
      token.classList.add("opacity-50", "cursor-grabbing");
    };
    const handleUp = (upEvent: PointerEvent) => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
      token.classList.remove("opacity-50", "cursor-grabbing");
      if (moved) behavior.onMove(token, upEvent.clientX, upEvent.clientY);
      else token.focus();
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp, { once: true });
  });
}

function createRemoveButton(label: string, onRemove: () => void): HTMLButtonElement {
  const remove = document.createElement("button");
  remove.type = "button";
  remove.tabIndex = -1;
  remove.className = "ml-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground";
  remove.setAttribute("aria-label", label);
  remove.textContent = "×";
  remove.addEventListener("pointerdown", (event) => event.stopPropagation());
  remove.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    onRemove();
  });
  return remove;
}

export function createFileToken(
  name: string,
  behavior: TokenBehavior,
  absolutePath?: string,
): HTMLElement {
  const token = document.createElement("span");
  token.contentEditable = "false";
  token.tabIndex = 0;
  token.dataset.fileToken = crypto.randomUUID();
  token.dataset.attachmentStatus = absolutePath ? "ready" : "uploading";
  if (absolutePath) token.dataset.absolutePath = absolutePath;
  token.className = `${resourceChipClass("file")} ${CHIP_CLASS}`;
  token.setAttribute("aria-label", `文件 ${name}。可拖动调整位置，按 Delete 删除`);
  if (absolutePath) token.title = absolutePath;

  const status = document.createElement("span");
  status.dataset.fileStatus = "";
  status.className = absolutePath
    ? "inline-flex shrink-0"
    : "h-3 w-3 shrink-0 animate-spin rounded-full border border-muted-foreground/30 border-t-muted-foreground motion-reduce:animate-none";
  if (absolutePath) status.append(createResourceIdentityIcon("file"));
  status.setAttribute("aria-hidden", "true");

  const label = document.createElement("span");
  label.dataset.fileName = "";
  label.className = "truncate";
  label.textContent = name;

  token.append(status, label, createRemoveButton(`移除文件 ${name}`, () => behavior.onRemove(token)));
  attachTokenBehaviors(token, behavior);
  return token;
}

export function markFileTokenReady(token: HTMLElement, name: string, absolutePath: string) {
  token.dataset.attachmentStatus = "ready";
  token.dataset.absolutePath = absolutePath;
  token.title = absolutePath;
  const status = token.querySelector<HTMLElement>("[data-file-status]");
  if (status) {
    status.className = "inline-flex shrink-0";
    status.replaceChildren(createResourceIdentityIcon("file"));
  }
  const label = token.querySelector<HTMLElement>("[data-file-name]");
  if (label) label.textContent = name;
  token.setAttribute("aria-label", `文件 ${name}。可拖动调整位置，按 Delete 删除`);
}

export function createResourceToken(
  resource: {
    name: string;
    resource_type: MentionResourceType;
    resource_id: string;
    reference_text: string;
  },
  behavior: TokenBehavior,
): HTMLElement {
  const token = document.createElement("span");
  token.contentEditable = "false";
  token.tabIndex = 0;
  token.dataset.resourceToken = crypto.randomUUID();
  token.dataset.resourceType = resource.resource_type;
  token.dataset.resourceId = resource.resource_id;
  token.dataset.referenceText = resource.reference_text;
  token.dataset.resourceName = resource.name;
  token.className = `${resourceChipClass(resource.resource_type)} ${CHIP_CLASS}`;
  token.title = resource.reference_text;
  token.setAttribute(
    "aria-label",
    `${mentionTypeLabel(resource.resource_type)} ${resource.name}。可拖动调整位置，按 Delete 删除`,
  );

  const label = document.createElement("span");
  label.dataset.resourceName = "";
  label.className = "truncate";
  label.textContent = `@${resource.name}`;

  token.append(
    createResourceIdentityIcon(resource.resource_type),
    label,
    createRemoveButton(`移除 ${resource.name}`, () => behavior.onRemove(token)),
  );
  attachTokenBehaviors(token, behavior);
  return token;
}
