import { ChevronRight, Terminal, Wrench } from "lucide-react";
import { useState } from "react";

import {
  readToolSchemaView,
  type SchemaActionView,
  type SchemaFieldView,
  type ToolDefinitionSource,
  type ToolSchemaView,
} from "../lib/tool-schema-view";

interface ToolDefinitionListProps {
  tools: ToolDefinitionSource[];
  toolsCount?: number;
}

function CountBadge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "accent" | "danger" }) {
  const toneClass = {
    neutral: "border-border/40 bg-muted/70 text-foreground",
    accent: "border-info/20 bg-info/10 text-info",
    danger: "border-destructive/20 bg-destructive/10 text-destructive",
  }[tone];

  return (
    <span className={`rounded border px-1.5 py-0.5 text-[11px] font-medium tabular-nums ${toneClass}`}>
      {children}
    </span>
  );
}

function FieldList({
  fields,
  caption,
  showHeading = true,
}: {
  fields: SchemaFieldView[];
  caption: string;
  showHeading?: boolean;
}) {
  if (fields.length === 0) return null;

  return (
    <section className="min-w-0" aria-label={caption}>
      {showHeading ? (
        <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{caption}</h5>
      ) : null}
      <ul className="min-w-0 divide-y divide-border/40 border-y border-border/40">
        {fields.map((field) => (
          <li key={field.path} className="grid min-w-0 gap-1.5 py-2.5 sm:grid-cols-[minmax(9rem,0.7fr)_minmax(0,1.3fr)] sm:gap-4">
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="max-w-full break-all font-mono text-sm font-medium text-foreground">
                {field.name}
              </span>
              <span className="max-w-full break-all font-mono text-[11px] text-muted-foreground">
                {field.typeLabel}
              </span>
              <span className={`text-[11px] ${field.required ? "text-destructive" : "text-muted-foreground"}`}>
                {field.required ? "必填" : "可选"}
              </span>
            </div>
            <div className="min-w-0">
              {field.description ? (
                <p className="text-xs leading-relaxed text-foreground [overflow-wrap:anywhere]">
                  {field.description}
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">未提供说明</p>
              )}
              {field.allowedValues.length > 0 ? (
                <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="text-[11px] text-muted-foreground">允许值</span>
                  <ul className="flex min-w-0 flex-wrap gap-1.5" aria-label={`${field.name} 允许值`}>
                    {field.allowedValues.map((value) => (
                      <li
                        key={value}
                        className="max-w-full break-all rounded bg-card/70 px-1.5 py-0.5 font-mono text-[11px] text-info"
                      >
                        {value}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {field.constraints.length > 0 ? (
                <p className="mt-1 text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
                  {field.constraints.join(" · ")}
                </p>
              ) : null}
              {field.children.length > 0 ? (
                <div className="mt-2 min-w-0 border-l border-border/60 pl-3">
                  <FieldList fields={field.children} caption={`${field.name} 字段`} showHeading={false} />
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ActionList({
  actions,
  description,
}: {
  actions: SchemaActionView[];
  description: string;
}) {
  if (actions.length === 0) return null;
  const hasActionDescriptions = actions.some((action) => action.description);

  return (
    <section className="min-w-0" aria-label="操作">
      <div className="mb-2 flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <h5 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">操作</h5>
        {description ? (
          <p className="text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">{description}</p>
        ) : null}
      </div>
      {hasActionDescriptions ? (
        <dl className="min-w-0 divide-y divide-border/40 border-y border-border/40">
          {actions.map((action) => (
            <div key={action.value} className="grid min-w-0 gap-1 py-2.5 sm:grid-cols-[minmax(9rem,0.7fr)_minmax(0,1.3fr)] sm:gap-4">
              <dt className="max-w-full break-all font-mono text-sm font-medium text-info">
                {action.value}
              </dt>
              <dd className="text-xs leading-relaxed text-foreground [overflow-wrap:anywhere]">
                {action.description || "未单独说明"}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <ul className="flex min-w-0 flex-wrap gap-2 border-y border-border/40 py-2.5" aria-label="允许的操作值">
          {actions.map((action) => (
            <li key={action.value} className="max-w-full break-all rounded bg-card/70 px-2 py-1 font-mono text-xs text-info">
              {action.value}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ToolDefinitionRow({
  view,
  index,
  expanded,
  onToggle,
}: {
  view: ToolSchemaView;
  index: number;
  expanded: boolean;
  onToggle: () => void;
}) {
  const detailsId = `tool-definition-${index}`;
  const hasContract = view.actions.length > 0 || view.fields.length > 0;
  const parameterCount = view.actions.length > 0 ? view.fields.length : view.parameterCount;
  const requiredCount = view.actions.length > 0
    ? view.fields.filter((field) => field.required).length
    : view.requiredCount;

  const heading = (
    <>
      <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-info/10 text-info">
        <Wrench size={15} aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="max-w-full break-all font-mono text-sm font-semibold text-foreground">{view.name}</span>
          {view.actions.length > 0 ? <CountBadge tone="accent">{view.actions.length} 个操作</CountBadge> : null}
          {parameterCount > 0 ? <CountBadge>{parameterCount} 个参数</CountBadge> : null}
          {requiredCount > 0 ? <CountBadge tone="danger">{requiredCount} 必填</CountBadge> : null}
        </span>
        <span className="mt-1 block text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
          {view.description || "未提供工具说明"}
        </span>
      </span>
    </>
  );

  return (
    <li className={`min-w-0 transition-colors ${expanded ? "bg-secondary/55" : "hover:bg-secondary/35"}`}>
      {hasContract ? (
        <button
          type="button"
          onClick={onToggle}
          className="flex min-h-14 w-full min-w-0 cursor-pointer items-center gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-info/40 sm:px-5"
          aria-expanded={expanded}
          aria-controls={detailsId}
        >
          {heading}
          <ChevronRight
            size={17}
            aria-hidden="true"
            className={`flex-shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none ${expanded ? "rotate-90 text-info" : ""}`}
          />
        </button>
      ) : (
        <div className="flex min-h-14 min-w-0 items-center gap-3 px-4 py-3 sm:px-5">{heading}</div>
      )}

      {expanded && hasContract ? (
        <div
          id={detailsId}
          className="min-w-0 space-y-5 border-t border-border/40 bg-card/20 px-4 py-4 sm:px-16"
          role="region"
          aria-label={`${view.name} 工具契约`}
        >
          <ActionList actions={view.actions} description={view.actionDescription} />
          <FieldList fields={view.fields} caption="参数" />
        </div>
      ) : null}
    </li>
  );
}

export default function ToolDefinitionList({ tools, toolsCount }: ToolDefinitionListProps) {
  const [expandedToolIndex, setExpandedToolIndex] = useState<number | null>(null);
  const count = toolsCount ?? tools.length;

  return (
    <section className="min-w-0 overflow-hidden rounded-xl border border-border/50 bg-secondary/80">
      <div className="flex min-w-0 items-center justify-between gap-4 border-b border-border/50 bg-secondary/50 px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg border border-info/20 bg-info/10 text-info">
            <Terminal size={17} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-foreground">工具定义</h3>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              展开工具可查看模型获得的操作、参数与约束
            </p>
          </div>
        </div>
        <span className="flex-shrink-0 rounded-full border border-info/20 bg-info/10 px-2.5 py-1 text-xs font-medium tabular-nums text-info">
          {count} 个工具
        </span>
      </div>
      <ul className="min-w-0 divide-y divide-border/40" aria-label="工具定义列表">
        {tools.map((tool, index) => (
          <ToolDefinitionRow
            key={tool.name}
            view={readToolSchemaView(tool)}
            index={index}
            expanded={expandedToolIndex === index}
            onToggle={() => setExpandedToolIndex((current) => (current === index ? null : index))}
          />
        ))}
      </ul>
    </section>
  );
}
