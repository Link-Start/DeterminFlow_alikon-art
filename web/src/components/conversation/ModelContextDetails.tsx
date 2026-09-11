import { WorkspaceContextDetails } from "./WorkspaceContextDetails";

interface ModelContextDetailsProps {
  context: Record<string, unknown>;
}

/** Display only recorded context; absence must not be presented as an empty recall. */
export default function ModelContextDetails({ context }: ModelContextDetailsProps) {
  const memory = context.long_term_memory;
  const hasMemory = memory !== null && typeof memory === "object"
    && !Array.isArray(memory) && "items" in memory && Array.isArray(memory.items);
  const workspace = context.workspace;
  const hasWorkspace = workspace !== null && typeof workspace === "object" && !Array.isArray(workspace);
  const productContext = { ...context };
  if (hasWorkspace) delete productContext.workspace;
  if (hasMemory) delete productContext.long_term_memory;
  const items = hasMemory ? memory.items as unknown[] : null;

  return <>
    {hasWorkspace ? <WorkspaceContextDetails workspace={workspace as Record<string, unknown>} /> : null}
    {(Object.keys(productContext).length > 0 || (!hasMemory && !hasWorkspace)) && (
      <div className="min-w-0 py-0.5 text-xs text-muted-foreground/50" role="listitem">
        <div className="font-medium">产品上下文</div>
        <pre className="mt-1 max-w-full whitespace-pre-wrap break-words font-mono text-[11px] leading-5">
          {JSON.stringify(productContext, null, 2)}
        </pre>
      </div>
    )}
    {items !== null && (
      <div className="min-w-0 py-0.5 text-xs text-muted-foreground/50" role="listitem">
        <span className="font-medium">长期记忆：</span>
        {items.length === 0 ? <code>[]</code> : (
          <pre className="mt-1 max-w-full whitespace-pre-wrap break-words font-mono text-[11px] leading-5">
            {JSON.stringify(items, null, 2)}
          </pre>
        )}
      </div>
    )}
  </>;
}
