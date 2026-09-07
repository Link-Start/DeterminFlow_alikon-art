import { TranscriptEntry } from "../types";
import MarkdownRenderer from "./MarkdownRenderer";
import { FileText, CircleCheck } from "lucide-react";
import { getSeatColor } from "../lib/seatColors";

interface TranscriptMessageProps {
  entry: TranscriptEntry;
  seatIndex: number;
  showRoundHeader?: boolean;
}

export default function TranscriptMessage({
  entry,
  seatIndex,
  showRoundHeader,
}: TranscriptMessageProps) {
  const color = getSeatColor(seatIndex);
  const isSummary = entry.entry_type === "summary";
  const isConclusion = entry.entry_type === "conclusion";

  return (
    <div className="mb-4">
      {showRoundHeader && (
        <div className="flex items-center gap-3 my-4" aria-hidden="true">
          <div className="flex-1 h-px bg-muted/60" />
          <span className="text-xs text-muted-foreground font-medium px-2">
            第 {entry.round_number} 轮
          </span>
          <div className="flex-1 h-px bg-muted/60" />
        </div>
      )}

      <div className={`bg-secondary/50 border border-border/50 rounded-lg p-4 ${
        isConclusion
          ? "border-success/30 bg-success/5"
          : isSummary
          ? "border-warning/30 bg-warning/5"
          : `${color.border} ${color.bg} hover:bg-muted/50`
      } transition-colors`} role="article" aria-label={`${entry.speaker_name} 第${entry.round_number}轮发言`}>
        <div className="flex items-center gap-2 mb-2">
          <span className={`w-2 h-2 rounded-full ${
            isConclusion ? "bg-success" : isSummary ? "bg-warning" : color.dot
          }`} aria-hidden="true" />
          <span className={`text-sm font-semibold ${
            isConclusion ? "text-success" : isSummary ? "text-warning" : color.text
          }`}>
            {entry.speaker_name}
          </span>
          <span className="text-xs text-muted-foreground">
            R{entry.round_number}
          </span>
          {entry.entry_type === "moderator_note" && (
            <span className="text-xs bg-warning/20 text-warning px-1.5 py-0.5 rounded">
              主持人
            </span>
          )}
          {isSummary && (
            <span className="text-xs bg-warning/20 text-warning px-1.5 py-0.5 rounded flex items-center gap-1">
              <FileText size={12} aria-hidden="true" />
              阶段摘要
            </span>
          )}
          {isConclusion && (
            <span className="text-xs bg-success/20 text-success px-1.5 py-0.5 rounded flex items-center gap-1">
              <CircleCheck size={12} aria-hidden="true" />
              会议结论
            </span>
          )}
        </div>

        <MarkdownRenderer content={entry.content} className="prose-sm" />
      </div>
    </div>
  );
}
