import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

/**
 * 统一的 Markdown 渲染组件
 * 使用相同的样式配置，确保整个应用中 markdown 显示一致
 */
function MarkdownRenderer({ content, className = "" }: MarkdownRendererProps) {
  return (
    <div
      className={`markdown-body prose prose-invert max-w-none
        prose-headings:text-foreground prose-headings:font-semibold
        prose-p:text-foreground prose-p:leading-relaxed
        prose-a:text-info prose-a:no-underline hover:prose-a:underline
        prose-strong:text-foreground prose-strong:font-semibold
        prose-code:text-info prose-code:text-sm prose-code:bg-secondary/60 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded
        prose-pre:bg-card prose-pre:border prose-pre:border-border/50 prose-pre:rounded-lg
        prose-ul:text-foreground prose-ol:text-foreground
        prose-li:text-foreground prose-li:my-1
        prose-blockquote:border-l-0 prose-blockquote:bg-primary/5 prose-blockquote:border prose-blockquote:border-primary/20 prose-blockquote:rounded-lg prose-blockquote:text-muted-foreground
        prose-hr:border-border/50
        prose-table:text-foreground
        prose-th:text-foreground prose-th:bg-secondary/60
        prose-td:border-border/50
        ${className}
      `}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

export default memo(MarkdownRenderer);
