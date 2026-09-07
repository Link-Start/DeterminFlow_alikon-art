/**
 * 压缩模块共享工具函数
 * 从 CompressionLogsPage / CompressionMonitorPage / CompressionLogsPanel / CompressionMonitorPanel 中提取
 */

/** 压缩类型 → Tailwind 样式类 */
export function getCompressionTypeColor(type: string): string {
  switch (type) {
    case "micro":
      return "bg-success/20 text-success";
    case "full":
      return "bg-primary/20 text-primary";
    case "reactive":
      return "bg-destructive/20 text-destructive";
    default:
      return "bg-muted text-muted-foreground";
  }
}

/** 压缩类型 → 中文标签 */
export function getCompressionTypeLabel(type: string): string {
  switch (type) {
    case "micro":
      return "MicroCompact";
    case "full":
      return "FullCompact";
    case "reactive":
      return "ReactiveCompact";
    default:
      return type;
  }
}

/** 格式化时间戳为中文本地格式 */
export function formatTimestamp(timestamp: string, options?: { includeYear?: boolean }): string {
  const date = new Date(timestamp);
  const opts: Intl.DateTimeFormatOptions = {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  };
  if (options?.includeYear) {
    opts.year = "numeric";
    opts.second = "2-digit";
  }
  return date.toLocaleString("zh-CN", opts);
}

/** 大数字格式化（1K, 1.2M） */
export function formatNumber(num: number): string {
  if (num >= 1_000_000) {
    return (num / 1_000_000).toFixed(1) + "M";
  }
  if (num >= 1_000) {
    return (num / 1_000).toFixed(1) + "K";
  }
  return num.toString();
}
