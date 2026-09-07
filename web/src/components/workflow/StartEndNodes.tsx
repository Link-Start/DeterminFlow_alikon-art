/**
 * StartEndNodes - START/END 终端节点 + 并行/汇聚/条件网关节点渲染
 */
import { Handle, Position, type NodeProps } from "reactflow";
import { BRAND_COLORS } from "../../lib/brand-colors";

export function StartNode() {
  return (
    <div className="relative px-6 py-2.5 rounded-full bg-card border-2 border-success/50 shadow-lg shadow-success/5" role="article" aria-label="工作流开始节点">
      <div className="text-xs font-semibold text-success tracking-wider">START</div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-success !w-2.5 !h-2.5 !border-2 !border-border"
      />
    </div>
  );
}

export function EndNode() {
  return (
    <div className="relative px-6 py-2.5 rounded-full bg-card border-2 border-destructive/50 shadow-lg shadow-destructive/5" role="article" aria-label="工作流结束节点">
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-destructive !w-2.5 !h-2.5 !border-2 !border-border"
      />
      <div className="text-xs font-semibold text-destructive tracking-wider">END</div>
    </div>
  );
}

const GATEWAY_COLORS: Record<string, string> = {
  parallel: BRAND_COLORS.node.agent,
  converge: BRAND_COLORS.warning,
  condition: BRAND_COLORS.info,
  loop: BRAND_COLORS.success,
};

const GATEWAY_LABELS: Record<string, string> = {
  parallel: "并行",
  converge: "汇聚",
  condition: "条件",
  loop: "循环",
};

function GatewayNode({ data, type }: NodeProps & { type: string }) {
  const gatewayType =
    type === "parallelGateway" ? "parallel" :
    type === "convergeGateway" ? "converge" :
    type === "conditionGateway" ? "condition" :
    type === "loopGateway" ? "loop" : "parallel";
  const color = GATEWAY_COLORS[gatewayType] || BRAND_COLORS.node.agent;
  const nodeLabel = GATEWAY_LABELS[gatewayType] || gatewayType;
  const status = (data as Record<string, string>)?.status || "";
  const isActive = status === "running";

  return (
    <div
      className={`relative flex items-center justify-center w-14 h-14 rotate-45 bg-card border-2 shadow-lg transition-all duration-300 ${
        isActive ? "animate-pulse motion-reduce:animate-none" : ""
      }`}
      style={{
        borderColor: isActive ? color : `color-mix(in srgb, ${color} 50%, transparent)`,
        boxShadow: `0 0 10px color-mix(in srgb, ${color} 12%, transparent)`,
      }}
      role="article"
      aria-label={`${nodeLabel}网关节点${isActive ? "，运行中" : ""}`}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-muted-foreground !w-2 !h-2 !border-2 !border-border"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-muted-foreground !w-2 !h-2 !border-2 !border-border"
      />
      <div className="-rotate-45 text-xs font-bold" style={{ color }}>{nodeLabel}</div>
    </div>
  );
}

export function ParallelGatewayNode(props: NodeProps) {
  return <GatewayNode {...props} type="parallelGateway" />;
}

export function ConvergeGatewayNode(props: NodeProps) {
  return <GatewayNode {...props} type="convergeGateway" />;
}

export function ConditionGatewayNode(props: NodeProps) {
  return <GatewayNode {...props} type="conditionGateway" />;
}

export function LoopGatewayNode(props: NodeProps) {
  return <GatewayNode {...props} type="loopGateway" />;
}
