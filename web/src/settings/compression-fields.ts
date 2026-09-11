import type { SettingsFieldGroup } from "./types";

export const COMPRESSION_FIELD_GROUPS: SettingsFieldGroup[] = [
  {
    id: "general",
    title: "通用",
    fields: [
      { id: "general.enabled", label: "启用压缩", kind: "boolean" },
      {
        id: "general.compactionThreshold",
        label: "压缩触发阈值",
        kind: "number",
        description: "上下文占用率达到该值时触发 FullCompact",
        min: 50,
        max: 95,
        step: 5,
        scale: 100,
        suffix: "%",
      },
    ],
  },
  {
    id: "micro_compact",
    title: "MicroCompact",
    description: "工具结果微压缩",
    fields: [
      {
        id: "micro_compact.maxToolResults",
        label: "工具结果数量阈值",
        kind: "integer",
        min: 5,
        max: 50,
        step: 1,
      },
      {
        id: "micro_compact.keepRecentToolResults",
        label: "保留最近工具结果数",
        kind: "integer",
        min: 1,
        max: 20,
        step: 1,
      },
      {
        id: "micro_compact.toolResultTokenRatio",
        label: "工具结果 Token 占比",
        kind: "number",
        min: 10,
        max: 80,
        step: 5,
        scale: 100,
        suffix: "%",
      },
      {
        id: "micro_compact.placeholder",
        label: "占位符文本",
        kind: "string",
      },
    ],
  },
  {
    id: "full_compact",
    title: "FullCompact",
    description: "全量摘要压缩",
    fields: [
      {
        id: "full_compact.keepRecentTokens",
        label: "保留最近 Token 数",
        kind: "integer",
        min: 10000,
        max: 200000,
        step: 1000,
      },
      {
        id: "full_compact.summaryTokenBudget",
        label: "摘要生成最大 Token 数",
        kind: "integer",
        min: 1000,
        max: 100000,
        step: 500,
      },
      {
        id: "full_compact.maxRetryCount",
        label: "最大重试次数",
        kind: "integer",
        min: 0,
        max: 5,
        step: 1,
      },
    ],
  },
  {
    id: "reactive_compact",
    title: "ReactiveCompact",
    description: "渐进式丢弃压缩",
    fields: [
      {
        id: "reactive_compact.maxRetryCount",
        label: "最大重试次数",
        kind: "integer",
        min: 1,
        max: 10,
        step: 1,
      },
    ],
  },
  {
    id: "post_compact",
    title: "后处理",
    fields: [
      {
        id: "post_compact.maxFilesToRead",
        label: "最多重读文件数",
        kind: "integer",
        min: 0,
        max: 10,
        step: 1,
      },
      {
        id: "post_compact.maxTokensPerFile",
        label: "每文件重读 Token 上限",
        kind: "integer",
        min: 1000,
        max: 20000,
        step: 1000,
      },
    ],
  },
  {
    id: "transcript",
    title: "日志",
    fields: [
      {
        id: "transcript.logsDir",
        label: "日志目录",
        kind: "string",
      },
    ],
  },
];

export function compressionValueAt(config: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((current, segment) => {
    if (!current || typeof current !== "object") return undefined;
    return (current as Record<string, unknown>)[segment];
  }, config);
}

export function setCompressionValue(
  config: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const segments = path.split(".");
  const next = { ...config };
  let cursor: Record<string, unknown> = next;
  for (let index = 0; index < segments.length - 1; index += 1) {
    const segment = segments[index];
    const child = cursor[segment];
    const copy = child && typeof child === "object"
      ? { ...(child as Record<string, unknown>) }
      : {};
    cursor[segment] = copy;
    cursor = copy;
  }
  cursor[segments[segments.length - 1]] = value;
  return next;
}
