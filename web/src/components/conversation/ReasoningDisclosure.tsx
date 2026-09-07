import { useId, useState } from "react";
import { Brain, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import CopyButton from "./CopyButton";
import MarkdownContent from "./MarkdownContent";

export interface ReasoningDisclosureProps {
  content: string;
  streaming?: boolean;
  defaultExpanded?: boolean;
  className?: string;
}

export default function ReasoningDisclosure({
  content,
  streaming = false,
  defaultExpanded = false,
  className = "",
}: ReasoningDisclosureProps) {
  const contentId = useId();
  const [expanded, setExpanded] = useState(defaultExpanded);
  const label = streaming ? "思考中" : "思考过程";

  if (!content && !streaming) return null;

  return (
    <section className={`rounded-lg border border-primary/15 bg-primary/5 ${className}`} aria-label={label}>
      <div className="flex min-h-10 items-center gap-1 px-2">
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-controls={contentId}
          className="inline-flex min-h-9 flex-1 items-center gap-2 rounded text-left text-xs text-primary transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        >
          {streaming ? (
            <Loader2 size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          ) : (
            <Brain size={14} aria-hidden="true" />
          )}
          <span>{label}</span>
          {expanded ? <ChevronDown size={13} className="ml-auto" aria-hidden="true" /> : <ChevronRight size={13} className="ml-auto" aria-hidden="true" />}
        </button>
        {content && <CopyButton value={content} label="思考过程" />}
      </div>
      {expanded && content && (
        <div id={contentId} className="border-t border-primary/10 px-3 py-2 text-sm text-muted-foreground">
          <MarkdownContent content={content} className="text-sm" />
        </div>
      )}
    </section>
  );
}
