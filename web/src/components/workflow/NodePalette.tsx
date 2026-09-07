/**
 * NodePalette - 节点类型面板
 *
 * 从后端 API 动态加载已注册的节点类型（Agent / 审批 / ...），
 * 参照 bk-sops 插件设计哲学，节点类型与编排引擎解耦合。
 */
import { useEffect, useState } from "react";
import type { DragEvent, KeyboardEvent } from "react";
import { Bot, CheckSquare, User, HelpCircle } from "lucide-react";
import { fetchNodeTypes } from "../../lib/api";
import { NodeTypeOption, NODE_TYPE_COLORS } from "../../types";
import { BRAND_COLORS } from "../../lib/brand-colors";

const NODE_DRAG_PREFIX = "application/workflow-node:";

const onDragStart = (event: DragEvent, nodeType: string) => {
  event.dataTransfer.setData(`${NODE_DRAG_PREFIX}${nodeType}`, nodeType);
  event.dataTransfer.effectAllowed = "move";
};

/** 通用拖拽键盘触发：Enter/Space 模拟 dragstart */
const handleDragKeyDown = (e: KeyboardEvent) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    const dragEvent = new globalThis.DragEvent("dragstart", {
      bubbles: true,
      cancelable: true,
      dataTransfer: new DataTransfer(),
    });
    e.currentTarget.dispatchEvent(dragEvent);
  }
};

const ICON_MAP: Record<string, React.ReactNode> = {
  bot: <Bot size={14} />,
  "check-square": <CheckSquare size={14} />,
  user: <User size={14} />,
};

export default function NodePalette() {
  const [nodeTypes, setNodeTypes] = useState<NodeTypeOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchNodeTypes()
      .then((types) => setNodeTypes(types))
      .catch(() => {
        // fallback: 至少显示 Agent 节点
        setNodeTypes([
          {
            node_type: "agent",
            label: "Agent 节点",
            icon: "bot",
            params_schema: [],
          },
        ]);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="w-52 h-full bg-card border-r border-primary/10 flex items-center justify-center" role="status" aria-label="加载节点类型">
        <div className="w-4 h-4 border-2 border-primary/30 border-t-indigo-500 rounded-full animate-spin motion-reduce:animate-none" aria-hidden="true" />
        <span className="sr-only">加载中...</span>
      </div>
    );
  }

  return (
    <div className="w-52 h-full bg-card border-r border-primary/10 flex flex-col shrink-0 select-none" role="complementary" aria-label="节点类型面板">
      {/* Header */}
      <div className="p-4 border-b border-primary/10">
        <h3 className="text-xs font-semibold text-muted-foreground">
          节点库
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5">拖拽到画布添加节点</p>
      </div>

      {/* Node cards */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2" role="list" aria-label="节点类型列表">
        {nodeTypes.map((nt) => {
          const color =
            NODE_TYPE_COLORS[nt.node_type] || BRAND_COLORS.primary;
          const iconNode = ICON_MAP[nt.icon] || <HelpCircle size={14} />;

          return (
            <div key={nt.node_type} className="space-y-0.5" role="listitem">
              <div
                draggable
                onDragStart={(e) => onDragStart(e, nt.node_type)}
                className="group flex items-start gap-2.5 p-2.5 rounded-lg bg-background border border-primary/10 hover:border-primary/40 cursor-grab active:cursor-grabbing transition-all duration-200 hover:shadow-md hover:shadow-primary/5 hover:translate-x-0.5"
                role="button"
                aria-label={`拖拽添加 ${nt.label}`}
                tabIndex={0}
                onKeyDown={handleDragKeyDown}
              >
                <div
                  className="w-6 h-6 rounded shrink-0 flex items-center justify-center text-white"
                  style={{ backgroundColor: color }}
                  aria-hidden="true"
                >
                  {iconNode}
                </div>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-foreground truncate">
                    {nt.label}
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {nt.node_type === "agent"
                      ? "AI Agent 处理节点"
                      : nt.node_type === "approval"
                        ? "人工审批决策节点"
                        : nt.node_type}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Gateway section */}
      <div className="px-3 py-2 border-t border-primary/10">
        <h3 className="text-xs font-semibold text-muted-foreground mb-2">
          流程控制
        </h3>
        <div className="space-y-2" role="list" aria-label="流程控制节点">
          <div
            draggable
            onDragStart={(e) => onDragStart(e, "parallel_gateway")}
            className="group flex items-center gap-2 p-2 rounded-lg bg-background border border-primary/10 hover:border-primary/40 cursor-grab active:cursor-grabbing transition-all duration-200 hover:shadow-md"
            role="listitem"
            aria-label="拖拽添加并行网关"
            tabIndex={0}
            onKeyDown={handleDragKeyDown}
          >
            <div className="w-5 h-5 rotate-45 rounded border-2 border-primary flex items-center justify-center text-xs font-bold text-primary" aria-hidden="true">
              <span className="-rotate-45">∥</span>
            </div>
            <div>
              <div className="text-xs font-medium text-foreground">并行网关</div>
              <div className="text-xs text-muted-foreground">多分支并行执行</div>
            </div>
          </div>
          <div
            draggable
            onDragStart={(e) => onDragStart(e, "converge_gateway")}
            className="group flex items-center gap-2 p-2 rounded-lg bg-background border border-warning/10 hover:border-warning/40 cursor-grab active:cursor-grabbing transition-all duration-200 hover:shadow-md"
            role="listitem"
            aria-label="拖拽添加汇聚网关"
            tabIndex={0}
            onKeyDown={handleDragKeyDown}
          >
            <div className="w-5 h-5 rotate-45 rounded border-2 border-warning flex items-center justify-center text-xs font-bold text-warning" aria-hidden="true">
              <span className="-rotate-45">⋈</span>
            </div>
            <div>
              <div className="text-xs font-medium text-foreground">汇聚网关</div>
              <div className="text-xs text-muted-foreground">等待全部完成后汇聚</div>
            </div>
          </div>
          <div
            draggable
            onDragStart={(e) => onDragStart(e, "condition_gateway")}
            className="group flex items-center gap-2 p-2 rounded-lg bg-background border border-info/10 hover:border-info/40 cursor-grab active:cursor-grabbing transition-all duration-200 hover:shadow-md"
            role="listitem"
            aria-label="拖拽添加条件网关"
            tabIndex={0}
            onKeyDown={handleDragKeyDown}
          >
            <div className="w-5 h-5 rotate-45 rounded border-2 border-info flex items-center justify-center text-xs font-bold text-info" aria-hidden="true">
              <span className="-rotate-45">?</span>
            </div>
            <div>
              <div className="text-xs font-medium text-foreground">条件网关</div>
              <div className="text-xs text-muted-foreground">分支/循环条件判断</div>
            </div>
          </div>
          <div
            draggable
            onDragStart={(e) => onDragStart(e, "loop_gateway")}
            className="group flex items-center gap-2 p-2 rounded-lg bg-background border border-success/10 hover:border-success/40 cursor-grab active:cursor-grabbing transition-all duration-200 hover:shadow-md"
            role="listitem"
            aria-label="拖拽添加循环网关"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                const dragEvent = new DragEvent("dragstart", {
                  bubbles: true,
                  cancelable: true,
                  dataTransfer: new DataTransfer(),
                });
                e.currentTarget.dispatchEvent(dragEvent);
              }
            }}
          >
            <div className="w-5 h-5 rotate-45 rounded border-2 border-success flex items-center justify-center text-xs font-bold text-success" aria-hidden="true">
              <span className="-rotate-45">↻</span>
            </div>
            <div>
              <div className="text-xs font-medium text-foreground">循环网关</div>
              <div className="text-xs text-muted-foreground">列表遍历/次数循环</div>
            </div>
          </div>
        </div>
      </div>

      {/* Footer: START/END info */}
      <div className="p-3 border-t border-primary/10">
        <p className="text-xs text-muted-foreground mb-2">
          START / END 自动管理
        </p>
        <div className="space-y-1.5" role="list" aria-label="自动管理节点">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-background/50" role="listitem">
            <div className="w-1.5 h-1.5 rounded-full bg-success" aria-hidden="true" />
            <span className="text-xs text-muted-foreground">START — 入口</span>
          </div>
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-background/50" role="listitem">
            <div className="w-1.5 h-1.5 rounded-full bg-destructive" aria-hidden="true" />
            <span className="text-xs text-muted-foreground">END — 出口</span>
          </div>
        </div>
      </div>
    </div>
  );
}
