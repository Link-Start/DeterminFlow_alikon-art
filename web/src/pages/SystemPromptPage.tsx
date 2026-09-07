import { useState, useEffect, useCallback } from "react";
import { FileText, RefreshCw, Eye, Code, ChevronDown, AlertCircle, CheckCircle, Copy, Download } from "lucide-react";
import { fetchSessionSystemPrompt, fetchSessions } from "../lib/api";
import { Session } from "../types";
import MarkdownRenderer from "../components/MarkdownRenderer";
import ToolDefinitionList from "../components/ToolDefinitionList";

interface ToolParameter {
  type: string;
  description: string;
  required: boolean;
}

interface ToolData {
  name: string;
  description: string;
  parameters?: Record<string, ToolParameter>;
  schema: {
    type: "function";
    function: {
      name: string;
      description?: string;
      parameters: Record<string, unknown>;
    };
  };
}

interface SystemPromptData {
  session_id: string;
  agent_type: string;
  system_prompt: string;
  tools: ToolData[];
  tools_count: number;
  message_counts: {
    system: number;
    user: number;
    assistant: number;
    tool: number;
  };
  token_estimate: {
    system_prompt: number;
    messages: number;
    tools: number;
    total: number;
  };
  model_config: {
    model: string;
    temperature: number;
    model_params: Record<string, unknown>;
    max_context_tokens: number;
    max_tool_rounds: number;
  };
}

export default function SystemPromptPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [promptData, setPromptData] = useState<SystemPromptData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"preview" | "raw">("preview");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadSessions();
  }, []);

  useEffect(() => {
    if (selectedSessionId) {
      loadSystemPrompt(selectedSessionId);
    }
  }, [selectedSessionId]);

  const loadSessions = async () => {
    try {
      const data = await fetchSessions();
      setSessions(data.sessions);
      if (data.main_session_id) {
        setSelectedSessionId(data.main_session_id);
      } else if (data.sessions.length > 0) {
        setSelectedSessionId(data.sessions[0].session_id);
      }
    } catch (err) {
      console.error("加载会话列表失败:", err);
      setError("加载会话列表失败");
    }
  };

  const loadSystemPrompt = async (sessionId: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSessionSystemPrompt(sessionId);
      setPromptData(data);
    } catch (err) {
      console.error("加载 system prompt 失败:", err);
      setError("加载 system prompt 失败");
      setPromptData(null);
    } finally {
      setLoading(false);
    }
  };

  const systemPrompt = promptData?.system_prompt ?? "";

  const handleRefresh = useCallback(() => {
    if (selectedSessionId) {
      loadSystemPrompt(selectedSessionId);
    }
  }, [selectedSessionId]);

  const handleCopy = useCallback(async () => {
    if (!systemPrompt) return;
    if (!navigator.clipboard) {
      setError("当前浏览器不支持剪贴板 API，请手动复制");
      return;
    }
    try {
      await navigator.clipboard.writeText(systemPrompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch (err) {
      console.error("复制失败:", err);
      setError("复制到剪贴板失败，请手动复制");
    }
  }, [systemPrompt]);

  const handleDownload = useCallback(() => {
    if (!systemPrompt || !selectedSessionId) return;
    try {
      const blob = new Blob([systemPrompt], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `system-prompt-${selectedSessionId.slice(0, 8)}.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("下载失败:", err);
      setError("下载文件失败，请重试");
    }
  }, [systemPrompt, selectedSessionId]);

  return (
    <div className="min-w-0" role="main" aria-label="System Prompt 预览页面">
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* 标题栏 */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-info/10 border border-info/20">
              <FileText size={22} className="text-info" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-foreground">LLM 提示词与工具</h2>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* 视图模式切换 */}
            <div className="flex items-center gap-1 bg-secondary/80 rounded-lg p-1 border border-border/50">
              <button
                type="button"
                onClick={() => setViewMode("preview")}
                className={`flex items-center gap-2 px-3 py-1.5 rounded text-sm transition-all duration-200 min-h-[44px] focus-visible:ring-2 focus-visible:ring-info/30 ${
                  viewMode === "preview"
                    ? "bg-info/20 text-info"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                aria-label="预览模式"
                aria-pressed={viewMode === "preview"}
              >
                <Eye size={14} aria-hidden="true" />
                <span>预览</span>
              </button>
              <button
                type="button"
                onClick={() => setViewMode("raw")}
                className={`flex items-center gap-2 px-3 py-1.5 rounded text-sm transition-all duration-200 min-h-[44px] focus-visible:ring-2 focus-visible:ring-primary/30 ${
                  viewMode === "raw"
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                aria-label="原格式模式"
                aria-pressed={viewMode === "raw"}
              >
                <Code size={14} aria-hidden="true" />
                <span>原格式</span>
              </button>
            </div>

            {/* 操作按钮组 */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handleCopy}
                disabled={loading || !promptData}
                className="p-2 rounded-lg border border-border text-muted-foreground
                  hover:bg-muted hover:text-foreground transition-all duration-200 cursor-pointer
                  focus-visible:ring-2 focus-visible:ring-info/30
                  disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="复制到剪贴板"
                aria-label="复制到剪贴板"
              >
                {copied ? (
                  <CheckCircle size={16} className="text-success" />
                ) : (
                  <Copy size={16} />
                )}
              </button>
              <button
                type="button"
                onClick={handleDownload}
                disabled={loading || !promptData}
                className="p-2 rounded-lg border border-border text-muted-foreground
                  hover:bg-muted hover:text-foreground transition-all duration-200 cursor-pointer
                  focus-visible:ring-2 focus-visible:ring-info/30
                  disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="下载 Markdown 文件"
                aria-label="下载 Markdown 文件"
              >
                <Download size={16} />
              </button>
              <button
                type="button"
                onClick={handleRefresh}
                disabled={loading}
                className="p-2 rounded-lg border border-border text-muted-foreground
                  hover:bg-muted hover:text-foreground transition-all duration-200 cursor-pointer
                  focus-visible:ring-2 focus-visible:ring-info/30
                  disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="刷新"
                aria-label="刷新数据"
              >
                <RefreshCw size={16} className={loading ? "animate-spin motion-reduce:animate-none" : ""} aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>

        {/* 会话选择器 */}
        <section className="bg-secondary/80 rounded-xl border border-border/50 p-4" aria-label="会话选择">
          <label htmlFor="session-select" className="text-sm text-foreground font-medium mb-2 block">
            选择会话
          </label>
          <div className="relative">
            <select
              id="session-select"
              value={selectedSessionId || ""}
              onChange={(e) => setSelectedSessionId(e.target.value)}
              className="w-full bg-secondary border border-border rounded-lg pl-3 pr-10 py-2 text-sm text-foreground
                focus:border-info/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-info/30
                cursor-pointer transition-all duration-200 min-h-[44px] appearance-none"
              aria-label="选择会话"
            >
              {sessions.length === 0 ? (
                <option value="" disabled>暂无可用会话</option>
              ) : (
                sessions.map((session) => (
                  <option key={session.session_id} value={session.session_id}>
                    {session.type === "main" ? "[主] " : "[子] "}
                    {session.session_id.slice(0, 8)} - {session.task || "无任务描述"} ({session.agent_type || "default"})
                  </option>
                ))
              )}
            </select>
            <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" aria-hidden="true" />
          </div>
        </section>

        {/* 错误提示 */}
        {error && (
          <div
            className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 flex items-start gap-3"
            role="alert"
            aria-live="polite"
          >
            <AlertCircle size={18} className="text-destructive mt-0.5 flex-shrink-0" aria-hidden="true" />
            <div className="flex-1">
              <p className="text-sm text-destructive">{error}</p>
              <button
                type="button"
                onClick={handleRefresh}
                disabled={!selectedSessionId}
                className="mt-2 text-xs text-destructive hover:text-destructive underline underline-offset-2
                  cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px] flex items-center
                  focus-visible:ring-2 focus-visible:ring-destructive/30 rounded"
                aria-label="重试加载"
              >
                重试
              </button>
            </div>
          </div>
        )}

        {/* 加载中 */}
        {loading && (
          <div
            className="flex items-center justify-center py-12"
            role="status"
            aria-label="正在加载 System Prompt 数据"
          >
            <div className="flex items-center gap-3 text-muted-foreground">
              <RefreshCw size={20} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
              <span>加载中...</span>
            </div>
          </div>
        )}

        {/* 复制成功提示 */}
        {copied && (
          <div
            className="fixed bottom-4 right-4 z-50"
            role="status"
            aria-live="polite"
          >
            <div className="bg-secondary/90 rounded-lg border border-success/30 p-3 flex items-center gap-2 shadow-lg">
              <CheckCircle size={16} className="text-success" aria-hidden="true" />
              <span className="text-sm text-success">已复制到剪贴板</span>
              <button
                type="button"
                onClick={() => setCopied(false)}
                className="ml-1 p-0.5 rounded text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-success/30"
                aria-label="关闭提示"
              >
                <span aria-hidden="true">&times;</span>
              </button>
            </div>
          </div>
        )}

        {/* System Prompt 内容 */}
        {!loading && promptData && (
          <section
            className="bg-secondary/80 rounded-xl border border-border/50 overflow-hidden"
            aria-label="System Prompt 内容"
          >
            <div className="bg-secondary/50 px-5 py-3 border-b border-border/50">
              <h3 className="text-base font-semibold text-foreground">
                系统提示词
              </h3>
              <p className="text-xs text-muted-foreground mt-1">
                {viewMode === "preview"
                  ? "以下是渲染后的 Markdown 预览"
                  : "以下是原始 Markdown 文本"}
              </p>
            </div>
            <div className="p-6">
              {viewMode === "preview" ? (
                <MarkdownRenderer content={systemPrompt} />
              ) : (
                <pre
                  className="text-xs text-foreground whitespace-pre-wrap font-mono bg-card/60 rounded-lg p-4 overflow-x-auto max-h-[60vh]"
                  role="textbox"
                  aria-readonly="true"
                  aria-label="原始 Markdown 内容"
                  tabIndex={0}
                >
                  {systemPrompt}
                </pre>
              )}
            </div>
          </section>
        )}

        {!loading && promptData && promptData.tools.length > 0 && (
          <ToolDefinitionList
            tools={promptData.tools}
            toolsCount={promptData.tools_count}
          />
        )}
      </div>
    </div>
  );
}
