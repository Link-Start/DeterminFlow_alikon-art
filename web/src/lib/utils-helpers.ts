/**
 * 工具函数集合
 */

// ============ 时间格式化 ============

export function formatTime(isoString: string): string {
  if (!isoString) return "-";
  const date = new Date(isoString);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelativeTime(isoString: string): string {
  if (!isoString) return "-";
  const date = new Date(isoString);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
  return `${Math.floor(diff / 86400000)}天前`;
}

// ============ 状态颜色映射 ============

export const statusConfig: Record<string, { color: string; bg: string; dotColor: string; label: string }> = {
  running: { color: "text-success", bg: "bg-success/20", dotColor: "bg-success", label: "运行中" },
  streaming: { color: "text-info", bg: "bg-info/20", dotColor: "bg-info", label: "流式传输" },
  completed: { color: "text-info", bg: "bg-info/20", dotColor: "bg-info", label: "已完成" },
  error: { color: "text-destructive", bg: "bg-destructive/20", dotColor: "bg-destructive", label: "错误" },
  waiting: { color: "text-warning", bg: "bg-warning/20", dotColor: "bg-warning", label: "等待中" },
  idle: { color: "text-muted-foreground", bg: "bg-muted-foreground/20", dotColor: "bg-muted-foreground", label: "空闲" },
};

export function getStatusConfig(status: string) {
  return statusConfig[status] || statusConfig.error;
}

// ============ JSON 格式化 ============

export function safeJsonParse(str: string): unknown {
  try {
    return JSON.parse(str);
  } catch {
    return str;
  }
}

export function prettyJson(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

// ============ 截断文本 ============

export function truncate(text: string, maxLength: number): string {
  if (!text || text.length <= maxLength) return text || "";
  return text.slice(0, maxLength) + "...";
}

// ============ 工具分组映射（group_id → 显示名称/颜色）============

export const toolGroupLabel: Record<string, string> = {
  memory: "记忆管理",
  coding: "编码工具",
  session_main: "主会话管理",
  communication: "子代理通信",
  config: "配置工具",
  skills: "Skills",
};

export const toolGroupColor: Record<string, string> = {
  memory: "bg-primary/20 text-primary border-primary/30",
  coding: "bg-success/20 text-success border-success/30",
  session_main: "bg-primary/20 text-primary border-primary/30",
  communication: "bg-info/20 text-info border-info/30",
  config: "bg-warning/20 text-warning border-warning/30",
  skills: "bg-primary/20 text-primary border-primary/30",
};
