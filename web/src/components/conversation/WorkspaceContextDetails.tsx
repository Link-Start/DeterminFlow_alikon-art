interface WorkspaceContextDetailsProps { workspace: Record<string, unknown> }

/** Only display injected file references, never the hidden binding marker. */
export function WorkspaceContextDetails({ workspace }: WorkspaceContextDetailsProps) {
  const documents = Array.isArray(workspace.documents) ? workspace.documents : [];
  const files = Array.isArray(workspace.files) ? workspace.files : [];
  const references = documents.map((document) => {
    const item = document && typeof document === "object" ? document as Record<string, unknown> : {};
    return { path: item.path, version: item.version, text: item.text, status: item.status };
  });
  const manifest = files.map((file) => {
    const item = file && typeof file === "object" ? file as Record<string, unknown> : {};
    return { path: item.path, version: item.version };
  });
  return <div className="min-w-0 py-0.5 text-xs text-muted-foreground/50" role="listitem">
    <span className="font-medium">工作区：</span>
    {workspace.status === "unavailable" ? <span>暂不可用</span> : <>
      {!references.length && !manifest.length ? <code>[]</code> : <pre className="mt-1 max-w-full whitespace-pre-wrap break-words font-mono text-[11px] leading-5">
        {JSON.stringify({ documents: references, files: manifest }, null, 2)}
      </pre>}
      {workspace.truncated === true ? <span>（已按预算截取）</span> : null}
    </>}
  </div>;
}
