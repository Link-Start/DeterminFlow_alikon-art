import assert from "node:assert/strict";
import { after, afterEach, test } from "node:test";
import { Window } from "happy-dom";

const dom = new Window({ url: "http://localhost/" });
for (const name of [
  "window", "document", "Node", "Text", "HTMLElement", "Element", "Range",
  "Event", "MouseEvent", "KeyboardEvent", "PointerEvent", "ResizeObserver", "navigator",
]) {
  const value = name === "window" ? dom : dom[name as keyof Window];
  Object.defineProperty(globalThis, name, { configurable: true, value });
}
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const React = await import("react");
const { act, createElement } = React;
Object.assign(globalThis, { React });
const { createRoot } = await import("react-dom/client");
const { default: ConversationComposer } = await import("./ConversationComposer");
const { findMentionAtCaret } = await import("./mentionQuery");
const { useMentionResources } = await import("./useMentionResources");
const { insertText, readComposerMessage } = await import("./composerEditorDom");
const { useComposerFileInsert } = await import("./useComposerFileInsert");
import type { MentionResourcesState } from "./useMentionResources";
import type { MentionResourceType } from "../../types";

let root: ReturnType<typeof createRoot> | null = null;
const originalFetch = globalThis.fetch;
const wait = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  document.body.replaceChildren();
  globalThis.fetch = originalFetch;
});
after(async () => dom.happyDOM.abort());

function host() {
  const element = document.createElement("div");
  document.body.append(element);
  root = createRoot(element);
  return element;
}

function caret(node: Node, offset: number) {
  const range = document.createRange();
  range.setStart(node, offset);
  range.collapse(true);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function resource(id: string, resource_type: MentionResourceType = "skill") {
  return {
    resource_type, resource_id: id, name: id, description: "", source: "",
    reference_text: `Skill「${id}」（get_skills(skill_id="${id}")）`, available: true,
  };
}

function page(ids: string[], more = false) {
  return new Response(JSON.stringify({
    items: ids.map((id) => resource(id)), total: ids.length + (more ? 1 : 0), has_more: more,
  }));
}

async function press(editor: HTMLElement, key: string, extra = {}) {
  const event = new dom.KeyboardEvent("keydown", {
    key, bubbles: true, cancelable: true, ...extra,
  }) as unknown as KeyboardEvent;
  await act(async () => {
    editor.dispatchEvent(event);
  });
  return event;
}

async function setInput(editor: HTMLElement, text: string) {
  await act(async () => {
    editor.focus();
    editor.textContent = text;
    caret(editor.firstChild!, text.length);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function mountComposer() {
  const container = host();
  await act(async () => root?.render(createElement(ConversationComposer, {
    sessionId: "current", onSendMessage: () => undefined,
  })));
  return container.querySelector<HTMLElement>('[role="textbox"]')!;
}

function interceptFileDialog() {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  let opened = 0;
  input.addEventListener("click", (event) => { event.preventDefault(); opened += 1; });
  return { input, opened: () => opened };
}

async function chooseFile(input: HTMLInputElement, name = "notes.md") {
  Object.defineProperty(input, "files", { configurable: true, value: [new File(["notes"], name)] });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
}

for (const method of ["keyboard", "mouse"]) {
  test(`the top file action opens the existing picker by ${method} and replaces only @`, async () => {
    const uploads: string[] = [];
    globalThis.fetch = async (url, options) => {
      if (options?.method !== "POST") return page([]);
      uploads.push(String(url));
      assert.equal(options?.method, "POST");
      assert.ok(options?.body instanceof File);
      return new Response(JSON.stringify({ name: "notes.md", absolute_path: "/tmp/notes.md" }));
    };
    const editor = await mountComposer();
    const dialog = interceptFileDialog();
    await setInput(editor, "前 @ 后");
    await act(async () => {
      caret(editor.firstChild!, 3);
      editor.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const first = document.querySelector<HTMLElement>('[role="option"]')!;
    assert.equal(first.textContent, "文件附件");
    assert.equal(first.getAttribute("aria-haspopup"), null);
    assert.equal(first.querySelector(".lucide-chevron-right"), null);
    assert.equal(document.querySelectorAll('[role="listbox"]').length, 1);
    await press(editor, "ArrowRight");
    assert.equal(dialog.opened(), 0);
    if (method === "keyboard") await press(editor, "Enter");
    else await act(async () => first.click());
    assert.equal(dialog.opened(), 1);
    assert.equal(document.querySelector('[data-mention-picker]'), null);
    assert.equal(editor.textContent, "前 @ 后");
    await chooseFile(dialog.input);
    assert.equal(uploads.length, 1);
    assert.match(uploads[0], /\/workspace\/current\/attachments\?filename=notes.md$/);
    const message = readComposerMessage(editor);
    assert.match(message.content, /^前\s*\/tmp\/notes.md\s*后$/);
    assert.deepEqual(message.attachments, [{ name: "notes.md", absolute_path: "/tmp/notes.md" }]);
    assert.ok(editor.querySelector('[data-file-token] [data-resource-icon="file"]'));
    assert.equal(editor.querySelector('[data-resource-token]'), null);
  });
}

test("cancel keeps the draft and plus opens mentions before choosing a file at the saved caret", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ name: "notes.md", absolute_path: "/tmp/notes.md" }));
  const editor = await mountComposer();
  const dialog = interceptFileDialog();
  await setInput(editor, "@");
  await press(editor, "Enter");
  await act(async () => dialog.input.dispatchEvent(new Event("cancel")));
  assert.equal(editor.textContent, "@");
  assert.equal(document.activeElement, editor);
  assert.equal(document.querySelector('[data-mention-picker]'), null);
  await setInput(editor, "前 后");
  caret(editor.firstChild!, 2);
  const button = document.querySelector<HTMLButtonElement>('button[aria-label="添加资源"]')!;
  assert.ok(button.querySelector(".lucide-plus"));
  await act(async () => button.click());
  assert.equal(dialog.opened(), 1);
  assert.equal(editor.textContent, "前 @后");
  assert.equal(document.querySelector('[role="option"]')?.textContent, "文件附件");
  await press(editor, "Enter");
  assert.equal(dialog.opened(), 2);
  // A native dialog can move focus/selection away from the editor.
  window.getSelection()?.removeAllRanges();
  await chooseFile(dialog.input);
  assert.match(readComposerMessage(editor).content, /^前\s*\/tmp\/notes.md\s*后$/);
});

for (const draft of ["", "请检查", "review", "第一行\n"]) {
  test(`plus inserts a searchable @ into ${JSON.stringify(draft)} without opening the file dialog`, async () => {
    const editor = await mountComposer();
    const dialog = interceptFileDialog();
    if (draft) await setInput(editor, draft);
    const button = document.querySelector<HTMLButtonElement>('button[aria-label="添加资源"]')!;
    await act(async () => button.click());
    assert.equal(editor.textContent, draft + (draft === "review" ? " @" : "@"));
    assert.equal(document.activeElement, editor);
    assert.equal(dialog.opened(), 0);
    assert.equal(findMentionAtCaret(editor)?.query, "");
    assert.equal(document.querySelectorAll('[role="option"]').length, 7);
    await press(editor, "Escape");
    await act(async () => button.click());
    assert.equal(document.querySelectorAll('[role="option"]').length, 7);
    assert.equal(findMentionAtCaret(editor)?.query, "");
    assert.equal(dialog.opened(), 0);
  });
}

test("a pending file selection cannot insert into a different session", async () => {
  let uploads = 0;
  globalThis.fetch = async () => { uploads += 1; return page([]); };
  const editor = await mountComposer();
  const dialog = interceptFileDialog();
  await setInput(editor, "@");
  await press(editor, "Enter");
  await act(async () => root?.render(createElement(ConversationComposer, {
    sessionId: "next", onSendMessage: () => undefined,
  })));
  await chooseFile(dialog.input);
  assert.equal(uploads, 0);
  assert.equal(editor.textContent, "");
});

test("typing file searches the direct action without creating a resource submenu", async () => {
  globalThis.fetch = async () => page([]);
  const editor = await mountComposer();
  const dialog = interceptFileDialog();
  await setInput(editor, "@文件");
  await act(async () => wait());
  assert.equal(document.querySelectorAll('[role="listbox"]').length, 1);
  assert.equal(document.querySelector('[role="option"]')?.textContent, "文件附件");
  await press(editor, "Enter");
  assert.equal(dialog.opened(), 1);
});

test("a mention after a literal newline replaces only its own range", () => {
  const editor = document.createElement("div");
  editor.contentEditable = "true";
  document.body.append(editor);
  const text = document.createTextNode("第一段\n用@审查 后面的文字");
  editor.append(text);
  caret(text, "第一段\n用@审查".length);
  const match = findMentionAtCaret(editor);
  assert.equal(match?.range.toString(), "@审查");
  assert.equal(match?.startOffset, "第一段\n用".length);
});

test("real composer key events insert a reference, preserve newlines and send subsequent text", async () => {
  globalThis.fetch = async () => page(["review"]);
  const container = host();
  const sent: unknown[][] = [];
  await act(async () => {
    root?.render(createElement(ConversationComposer, {
      sessionId: "current", onSendMessage: (...args) => { sent.push(args); },
    }));
  });
  const editor = container.querySelector<HTMLElement>('[role="textbox"]')!;
  await act(async () => {
    editor.focus();
    editor.textContent = "第一段\n用@";
    caret(editor.firstChild!, editor.textContent.length);
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
  assert.equal(document.querySelectorAll('[role="option"]').length, 7);
  await press(editor, "ArrowDown");
  await press(editor, "ArrowDown");
  await press(editor, "ArrowDown");
  await press(editor, "Enter");
  assert.equal(sent.length, 0);
  await act(async () => wait());
  await press(editor, "Enter", { isComposing: true, keyCode: 229 });
  assert.equal(editor.querySelector("[data-resource-token]"), null);
  await press(editor, "Enter");
  assert.ok(editor.querySelector("[data-resource-token]"));
  assert.match(readComposerMessage(editor).content, /^第一段\n用 /);
  assert.equal(document.querySelector('[role="listbox"]'), null);
  await act(async () => {
    insertText(editor, " 帮我检查");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await press(editor, "Enter");
  assert.equal(sent.length, 1);
  assert.match(String(sent[0][0]), /帮我检查$/);
  assert.deepEqual((sent[0][1] as unknown[]).length, 1);
});

test("horizontal keys preserve both panes, retry and return keyboard focus", async () => {
  let calls = 0;
  globalThis.fetch = async (url) => {
    const params = new URL(String(url), "http://localhost").searchParams;
    if (params.get("resource_type") !== "skill") return page([]);
    calls += 1;
    if (calls === 1) throw new Error("offline");
    return page(["review", "write"]);
  };
  const editor = await mountComposer();
  await setInput(editor, "@");
  await press(editor, "ArrowDown");
  await press(editor, "ArrowDown");
  await press(editor, "ArrowDown");
  await press(editor, "ArrowRight");
  await act(async () => wait());
  const panes = () => document.querySelectorAll('[role="listbox"]');
  assert.equal(panes().length, 2);
  assert.equal(panes()[0].querySelectorAll('[role="option"]').length, 7);
  assert.equal(panes()[1].querySelector('[role="option"]')?.textContent, "重试");
  await press(editor, "Enter");
  await act(async () => wait());
  await press(editor, "ArrowDown");
  assert.equal(document.getElementById(editor.getAttribute("aria-activedescendant")!)?.textContent, "write");
  await press(editor, "ArrowLeft");
  assert.equal(panes().length, 2);
  assert.equal(document.getElementById(editor.getAttribute("aria-activedescendant")!)?.textContent, "Skill 技能");
  await press(editor, "ArrowRight");
  assert.equal(document.getElementById(editor.getAttribute("aria-activedescendant")!)?.textContent, "review");
  await press(editor, "Escape");
  await press(editor, "Escape");
  assert.equal(panes().length, 0);
  await setInput(editor, "用 @skill");
  const tab = await press(editor, "Tab", { shiftKey: true });
  assert.equal(tab.defaultPrevented, false);
  assert.equal(panes().length, 0);
  assert.equal(editor.querySelector("[data-resource-token]"), null);
});

test("typing a resource name directly searches all categories and Enter inserts its match", async () => {
  const searched = new Set<string>();
  globalThis.fetch = async (url) => {
    const params = new URL(String(url), "http://localhost").searchParams;
    assert.equal(params.get("q"), "review");
    const type = params.get("resource_type")!;
    searched.add(type);
    return type === "skill" ? page(["review"]) : page([]);
  };
  const editor = await mountComposer();
  await setInput(editor, "用 @review");
  await act(async () => wait());
  assert.equal(searched.size, 6);
  const panes = document.querySelectorAll('[role="listbox"]');
  assert.equal(panes.length, 2);
  assert.equal(panes[0].textContent, "Skill 技能");
  assert.equal(panes[1].textContent, "review");
  await press(editor, "Enter");
  assert.equal(readComposerMessage(editor).attachments.length, 1);
  assert.equal(editor.querySelector<HTMLElement>("[data-resource-token]")?.dataset.resourceId, "review");
  await press(editor, "Backspace");
  assert.equal(readComposerMessage(editor).attachments.length, 0);
});

test("hover opens the submenu on the right and a nonfirst row remains selected", async () => {
  globalThis.fetch = async () => page(["review", "write"]);
  const editor = await mountComposer();
  await setInput(editor, "@");
  const parent = document.querySelector('[role="listbox"]')!;
  await act(async () => {
    parent.querySelectorAll('[role="option"]')[3].dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  });
  await act(async () => wait());
  const panes = document.querySelectorAll('[role="listbox"]');
  assert.equal(panes[0], parent);
  assert.equal(panes.length, 2);
  const second = panes[1].querySelectorAll<HTMLElement>('[role="option"]')[1];
  await act(async () => second.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })));
  assert.equal(document.getElementById(editor.getAttribute("aria-activedescendant")!), second);
  await act(async () => second.click());
  assert.equal(editor.querySelector<HTMLElement>("[data-resource-token]")?.dataset.resourceId, "write");
});

test("a late category response does not replace a resource the user is navigating", async () => {
  let resolvePrompt: ((response: Response) => void) | undefined;
  globalThis.fetch = async (url) => {
    const type = new URL(String(url), "http://localhost").searchParams.get("resource_type");
    if (type === "prompt") return new Promise<Response>((resolve) => { resolvePrompt = resolve; });
    return type === "skill" ? page(["review", "review-write"]) : page([]);
  };
  const editor = await mountComposer();
  await setInput(editor, "@review");
  await act(async () => wait());
  await press(editor, "ArrowDown");
  await act(async () => resolvePrompt?.(new Response(JSON.stringify({
    items: [resource("review-prompt", "prompt")], total: 1, has_more: false,
  }))));
  assert.equal(document.getElementById(editor.getAttribute("aria-activedescendant")!)?.textContent, "review-write");
  await press(editor, "Enter");
  assert.equal(editor.querySelector<HTMLElement>("[data-resource-token]")?.dataset.resourceId, "review-write");
});

test("an unmatched direct query stays recoverable without selectable stale results", async () => {
  globalThis.fetch = async () => page([]);
  const editor = await mountComposer();
  await setInput(editor, "@不存在的资源");
  await act(async () => wait());
  assert.match(document.querySelector('[data-mention-picker]')?.textContent ?? "", /没有匹配的资源/);
  assert.equal(document.querySelectorAll('[role="option"]').length, 0);
  assert.equal(editor.getAttribute("aria-activedescendant"), null);
  await press(editor, "Enter");
  assert.equal(editor.querySelector("[data-resource-token]"), null);
  await setInput(editor, "@");
  assert.equal(document.querySelectorAll('[role="option"]').length, 7);
});

test("outside interaction dismisses the picker and a different @ starts at the type layer", async () => {
  globalThis.fetch = async () => page(["review"]);
  const editor = await mountComposer();
  await setInput(editor, "@skill");
  await act(async () => wait());
  assert.equal(document.querySelectorAll('[role="listbox"]').length, 2);
  await act(async () => {
    insertText(editor, " 还有 @");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
  assert.equal(document.querySelectorAll('[role="option"]').length, 7);
  assert.equal(document.querySelectorAll('[role="listbox"]').length, 1);
  await act(async () => {
    document.body.dispatchEvent(new dom.PointerEvent("pointerdown", { bubbles: true }) as unknown as Event);
    document.dispatchEvent(new Event("selectionchange"));
  });
  assert.equal(document.querySelector('[role="listbox"]'), null);
});

test("query results shrink upward from the composer boundary and leave a gap", async () => {
  globalThis.fetch = async (url) => {
    const params = new URL(String(url), "http://localhost").searchParams;
    if (params.get("resource_type") !== "skill") return page([]);
    return page(params.get("q") === "review" ? ["review"] : ["review", "read", "rewrite"]);
  };
  const editor = await mountComposer();
  const frame = editor.closest<HTMLElement>("[data-composer-frame]")!;
  frame.getBoundingClientRect = () => ({ top: 400, bottom: 600, left: 24, right: 800, width: 776, height: 200, x: 24, y: 400, toJSON: () => ({}) });
  await setInput(editor, "@re");
  await act(async () => wait());
  const panel = document.querySelector<HTMLElement>("[data-mention-picker]")!;
  const bottom = panel.style.bottom;
  assert.equal(window.innerHeight - parseFloat(bottom), 392);
  assert.equal(panel.style.top, "");
  assert.equal(panel.style.height, "");
  assert.equal(document.querySelectorAll('[role="listbox"]')[1].querySelectorAll('[role="option"]').length, 3);
  await act(async () => {
    insertText(editor, "view");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => wait(220));
  assert.equal(document.querySelector<HTMLElement>("[data-mention-picker]")?.style.bottom, bottom);
  assert.equal(document.querySelectorAll('[role="listbox"]')[1].querySelectorAll('[role="option"]').length, 1);
});

test("switching sessions clears the draft and both panes", async () => {
  globalThis.fetch = async () => page(["review"]);
  const editor = await mountComposer();
  await setInput(editor, "用 @review");
  await act(async () => wait());
  await act(async () => root?.render(createElement(ConversationComposer, {
    sessionId: "other", onSendMessage: () => undefined,
  })));
  assert.equal(editor.textContent, "");
  assert.equal(document.querySelector('[role="listbox"]'), null);
});

test("changing a query immediately makes the previous results unselectable", async () => {
  globalThis.fetch = async () => page(["old"]);
  host();
  let latest: MentionResourcesState | undefined;
  function Probe({ query }: { query: string }) {
    latest = useMentionResources("current", "skill", query, true);
    return null;
  }
  await act(async () => root?.render(createElement(Probe, { query: "old" })));
  await act(async () => wait());
  assert.equal(latest?.items[0]?.resource_id, "old");
  await act(async () => root?.render(createElement(Probe, { query: "new" })));
  assert.deepEqual(latest?.items, []);
  assert.equal(latest?.status, "loading");
});

test("a pending next page cannot contaminate a reopened resource picker", async () => {
  let resolveNext: ((response: Response) => void) | undefined;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    if (calls === 2) return new Promise<Response>((resolve) => { resolveNext = resolve; });
    return calls === 1 ? page(["old"], true) : page(["new"]);
  };
  host();
  let latest: MentionResourcesState | undefined;
  function Probe({ enabled }: { enabled: boolean }) {
    latest = useMentionResources("current", "skill", "", enabled);
    return null;
  }
  await act(async () => root?.render(createElement(Probe, { enabled: true })));
  await act(async () => wait());
  await act(async () => latest?.loadMore());
  await act(async () => root?.render(createElement(Probe, { enabled: false })));
  await act(async () => root?.render(createElement(Probe, { enabled: true })));
  await act(async () => wait());
  assert.equal(latest?.items[0]?.resource_id, "new");
  await act(async () => resolveNext?.(page(["stale-page"])));
  assert.deepEqual(latest?.items.map((item) => item.resource_id), ["new"]);
});

test("an old file upload cannot change the next session's composer state", async () => {
  let rejectUpload: ((error: Error) => void) | undefined;
  globalThis.fetch = async () => new Promise<Response>((_resolve, reject) => { rejectUpload = reject; });
  const editor = document.createElement("div");
  document.body.append(editor);
  let latest: ReturnType<typeof useComposerFileInsert> | undefined;
  const options = {
    sessionId: "old", editable: true, editorRef: { current: editor as HTMLDivElement },
    editableRef: { current: true }, refreshContentState: () => undefined,
    tokenBehavior: {
      onRemove: () => undefined, onMove: () => undefined,
      onRefresh: () => undefined, isEditable: () => true,
    },
  };
  function Probe() { latest = useComposerFileInsert(options); return null; }
  host();
  await act(async () => root?.render(createElement(Probe)));
  const range = document.createRange();
  range.selectNodeContents(editor);
  await act(async () => latest?.insertBrowserFiles([new File(["text"], "old.txt")], range));
  assert.equal(latest?.pendingUploads, 1);
  await act(async () => { editor.replaceChildren(); latest?.resetFileInsert(); });
  await act(async () => rejectUpload?.(new Error("late failure")));
  assert.equal(latest?.pendingUploads, 0);
  assert.equal(latest?.attachmentError, null);
});

test("Shift+Enter after text inserts a newline in one keypress", async () => {
  const editor = await mountComposer();
  await setInput(editor, "123");
  await press(editor, "Enter", { shiftKey: true });
  assert.equal(readComposerMessage(editor).content, "123\n");
  await press(editor, "Enter", { shiftKey: true });
  assert.equal(readComposerMessage(editor).content, "123\n\n");
});
