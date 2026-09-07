/**
 * Theme-aware color strings for third-party canvas, SVG, and chart APIs that
 * cannot consume Tailwind classes. Product components should prefer semantic
 * Tailwind utilities; visualizations import values from this module.
 */
export const BRAND_COLORS = {
  primary: "hsl(var(--primary))",
  muted: "hsl(var(--muted-foreground))",
  border: "hsl(var(--border))",
  borderStrong: "hsl(var(--theme-surface-strong))",
  background: "hsl(var(--background))",
  backgroundOverlay: "hsl(var(--background) / 0.7)",
  success: "hsl(var(--success))",
  warning: "hsl(var(--warning))",
  destructive: "hsl(var(--destructive))",
  info: "hsl(var(--info))",
  node: {
    agent: "hsl(var(--node-agent))",
    tool: "hsl(var(--node-tool))",
    script: "hsl(var(--node-script))",
    api: "hsl(var(--node-api))",
    approval: "hsl(var(--node-approval))",
  },
} as const;

export const AGENT_TYPE_COLORS: Record<string, string> = {
  coder: BRAND_COLORS.success,
  reviewer: BRAND_COLORS.info,
  researcher: BRAND_COLORS.warning,
  reader: BRAND_COLORS.node.agent,
  default: BRAND_COLORS.primary,
};

export const NODE_TYPE_COLORS: Record<string, string> = {
  agent: BRAND_COLORS.node.agent,
  tool: BRAND_COLORS.node.tool,
  script: BRAND_COLORS.node.script,
  api: BRAND_COLORS.node.api,
  approval: BRAND_COLORS.node.approval,
  subprocess: BRAND_COLORS.node.api,
};

export const NODE_STATUS_COLORS: Record<string, string> = {
  pending: BRAND_COLORS.muted,
  running: BRAND_COLORS.info,
  retry_waiting: BRAND_COLORS.warning,
  completed: BRAND_COLORS.success,
  failed: BRAND_COLORS.destructive,
  waiting_approval: BRAND_COLORS.warning,
  skipped: BRAND_COLORS.muted,
};
