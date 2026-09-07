import { useState } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { RefreshCw } from "lucide-react";
import { fetchSessionSystemPrompt } from "../lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import MessageItem from "./MessageItem";

type LlmContextData = Awaited<ReturnType<typeof fetchSessionSystemPrompt>>;

interface PromptPanelProps {
  llmContext: LlmContextData | null;
  loading: boolean;
  onRefresh: () => void;
  sessionId: string;
}

export default function PromptPanel({ llmContext, loading, onRefresh, sessionId }: PromptPanelProps) {
  const [activeTab, setActiveTab] = useState<"system_prompt" | "messages" | "tools">("system_prompt");

  if (loading && !llmContext) {
    return (
      <div className="p-4 flex items-center justify-center text-muted-foreground text-sm gap-2" role="status" aria-label="加载中">
        <RefreshCw size={14} className="animate-spin" aria-hidden="true" />
        加载中...
      </div>
    );
  }

  if (!llmContext) {
    return <div className="p-4 text-center text-muted-foreground text-sm" role="status" aria-label="暂无 LLM 上下文数据">暂无数据</div>;
  }

  const { system_prompt, agent_type, tools, tools_count, message_counts, token_estimate, model_config, messages } = llmContext;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-hidden">
      {/* Header */}
      <div className="min-w-0 flex-shrink-0 border-b border-border/50 px-4 py-3">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="text-xs font-medium text-primary">当前有效入模上下文</span>
            <Badge variant="outline" className="min-w-0 truncate text-xs text-muted-foreground border-muted-foreground/30">
              {agent_type}
            </Badge>
          </div>
          <button
            onClick={onRefresh}
            disabled={loading}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors cursor-pointer disabled:opacity-40 min-h-[44px] min-w-[44px] flex items-center justify-center"
            aria-label="刷新 LLM 上下文"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} aria-hidden="true" />
          </button>
        </div>
        {/* 摘要统计条 */}
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="min-w-0 break-all font-mono text-info">{sessionId}</span>
          <span aria-hidden="true">·</span>
          <span>{model_config.model}</span>
          <span aria-hidden="true">·</span>
          <span>T={model_config.temperature}</span>
          <span aria-hidden="true">·</span>
          <span>~{token_estimate.total}t</span>
        </div>
      </div>

      {/* Sub Tabs */}
      <div className="flex border-b border-border/50 flex-shrink-0" role="tablist" aria-label="LLM 上下文视图">
        {([
          { key: "system_prompt" as const, label: "系统提示词", count: `${token_estimate.system_prompt}t` },
          { key: "messages" as const, label: "入模消息", count: `${message_counts.system + message_counts.user + message_counts.assistant + message_counts.tool}条` },
          { key: "tools" as const, label: "工具定义", count: String(tools_count) },
        ]).map(({ key, label, count }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            role="tab"
            aria-selected={activeTab === key}
            aria-controls={`tabpanel-${key}`}
            className={`flex-1 py-1.5 text-xs font-medium transition-colors cursor-pointer min-h-[44px] ${
              activeTab === key
                ? "text-primary border-b border-primary"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {label} <span className="opacity-60">({count})</span>
          </button>
        ))}
      </div>

      {/* Content */}
      <ScrollArea className="min-h-0 min-w-0 flex-1">
        <div className="min-w-0 space-y-3 px-4 py-4">
          {/* === System Prompt Tab === */}
          {activeTab === "system_prompt" && (
            <div id="tabpanel-system_prompt" role="tabpanel" aria-label="System Prompt 内容" className="min-w-0">
              {system_prompt ? (
                <div className="max-w-none [overflow-wrap:anywhere] rounded-lg bg-secondary/80 border border-border/50 p-4 prose prose-invert prose-sm
                  prose-headings:text-primary prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1.5
                  prose-p:text-xs prose-p:text-foreground prose-p:leading-relaxed prose-p:my-1
                  prose-li:text-xs prose-li:text-foreground prose-li:my-0.5
                  prose-strong:text-warning prose-strong:font-semibold
                  prose-code:text-info prose-code:text-xs prose-code:bg-secondary/60 prose-code:px-1 prose-code:py-0.5 prose-code:rounded
                  prose-hr:border-border/50 prose-hr:my-2
                  prose-ul:my-1 prose-ol:my-1">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {system_prompt}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="text-center text-muted-foreground text-sm py-8" role="status">该会话无 system prompt</div>
              )}
            </div>
          )}

          {/* === Messages Tab === */}
          {activeTab === "messages" && (
            <div id="tabpanel-messages" role="tabpanel" aria-label="当前有效入模消息" className="min-w-0 space-y-2">
              {/* Token 使用概览 */}
              <div className="mb-2 rounded-lg bg-secondary/80 border border-border/50 p-3">
                <h4 className="text-xs text-muted-foreground font-medium mb-2">Token 估算</h4>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">System Prompt</span>
                    <span className="text-primary font-mono">{token_estimate.system_prompt}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">对话消息</span>
                    <span className="text-info font-mono">{token_estimate.messages}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">工具定义</span>
                    <span className="text-warning font-mono">{token_estimate.tools}</span>
                  </div>
                  <div className="border-t border-border/30 pt-1 flex justify-between text-xs">
                    <span className="text-foreground font-medium">估算总计</span>
                    <span className="text-foreground font-mono font-bold">{token_estimate.total}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-secondary" role="progressbar" aria-valuenow={Math.min((token_estimate.total / model_config.max_context_tokens) * 100, 100)} aria-valuemin={0} aria-valuemax={100} aria-label={`Token 使用率 ${Math.round((token_estimate.total / model_config.max_context_tokens) * 100)}%`}>
                    <div
                      className={`h-full rounded-full transition-all ${
                        token_estimate.total > model_config.max_context_tokens * 0.8 ? "bg-destructive" :
                        token_estimate.total > model_config.max_context_tokens * 0.5 ? "bg-warning" : "bg-success"
                      }`}
                      style={{ width: `${Math.min((token_estimate.total / model_config.max_context_tokens) * 100, 100)}%` }}
                    />
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    {token_estimate.total} / {model_config.max_context_tokens}
                  </div>
                </div>
              </div>

              {/* 消息统计 */}
              <div className="mb-2 rounded-lg bg-secondary/80 border border-border/50 p-3">
                <h4 className="text-xs text-muted-foreground font-medium mb-2">消息组成</h4>
                <div className="grid grid-cols-2 gap-2" role="list" aria-label="消息类型统计">
                  {([
                    { label: "用户消息", count: message_counts.user, color: "text-success" },
                    { label: "助手回复", count: message_counts.assistant, color: "text-primary" },
                    { label: "工具结果", count: message_counts.tool, color: "text-warning" },
                    { label: "系统消息", count: message_counts.system, color: "text-primary" },
                  ]).map(({ label, count, color }) => (
                    <div key={label} className="flex justify-between text-xs" role="listitem">
                      <span className="text-muted-foreground">{label}</span>
                      <span className={`font-mono ${color}`}>{count}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* 完整消息列表 */}
              <div className="space-y-1.5">
                <h4 className="text-xs text-muted-foreground font-medium mb-1">当前入模消息 ({messages?.length || 0} 条)</h4>
                {messages && messages.length > 0 ? (
                  messages.map((msg, idx) => (
                    <MessageItem key={idx} message={msg} index={idx} />
                  ))
                ) : (
                  <div className="text-center text-muted-foreground text-sm py-8" role="status">暂无消息</div>
                )}
              </div>
            </div>
          )}

          {/* === Tools Tab === */}
          {activeTab === "tools" && (
            <div id="tabpanel-tools" role="tabpanel" aria-label="工具定义内容" className="min-w-0 space-y-1.5">
              {tools.map((tool) => (
                <div key={tool.name} className="min-w-0 rounded-lg bg-secondary/80 border border-border/50 px-3 py-2.5" role="article" aria-label={`工具: ${tool.name}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="min-w-0 break-all text-xs font-mono text-info font-semibold">{tool.name}</span>
                  </div>
                  <p className="mb-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">{tool.description}</p>
                  {tool.parameters && Object.keys(tool.parameters).length > 0 && (
                    <div className="flex flex-wrap gap-1" role="list" aria-label={`${tool.name} 参数列表`}>
                      {Object.entries(tool.parameters).map(([name, info]) => (
                        <span
                          key={name}
                            className={`max-w-full break-all text-xs px-1.5 py-0.5 rounded ${
                            info.required
                              ? "bg-warning/10 text-warning border border-warning/20"
                              : "bg-secondary/60 text-muted-foreground"
                          }`}
                          title={`${info.type}${info.required ? " (必填)" : " (可选)"}: ${info.description}`}
                          role="listitem"
                        >
                          {name}: {info.type}
                        </span>
                      ))}
                    </div>
                  )}
                  <details className="mt-2 min-w-0 border-t border-border/40 pt-2">
                    <summary className="cursor-pointer text-xs text-muted-foreground">完整 JSON Schema</summary>
                    <pre className="mt-2 max-h-72 min-w-0 overflow-auto whitespace-pre-wrap rounded bg-background/70 p-2 text-xs text-muted-foreground [overflow-wrap:anywhere]">
                      {JSON.stringify(tool.schema, null, 2)}
                    </pre>
                  </details>
                </div>
              ))}
              {tools.length === 0 && (
                <div className="text-center text-muted-foreground text-sm py-8" role="status">该会话无绑定工具</div>
              )}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
