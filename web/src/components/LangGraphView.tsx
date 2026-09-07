import { useMemo } from "react";
import ReactFlow, {
  Node,
  Edge,
  Background,
  Handle,
  Position,
  NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { GraphStructure } from "../types";
import { BRAND_COLORS } from "../lib/brand-colors";

interface LangGraphViewProps {
  graph: GraphStructure;
}

// ============ Custom Nodes ============

function LLMNode({ data }: NodeProps) {
  return (
    <div
      className="px-4 py-2 rounded-lg bg-node-agent/15 border-2 border-node-agent/50 min-w-[100px] min-h-[44px] text-center flex flex-col justify-center"
      role="article"
      aria-label={`LLM 节点: ${data.label}${data.description ? `, ${data.description}` : ""}`}
    >
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="text-xs font-bold text-node-agent">{data.label}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{data.description}</div>
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

function ToolNodeComponent({ data }: NodeProps) {
  return (
    <div
      className="px-4 py-2 rounded-lg bg-node-tool/15 border-2 border-node-tool/50 min-w-[100px] min-h-[44px] text-center flex flex-col justify-center"
      role="article"
      aria-label={`工具节点: ${data.label}${data.description ? `, ${data.description}` : ""}`}
    >
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="text-xs font-bold text-node-tool">{data.label}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{data.description}</div>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  );
}

function CheckNode({ data }: NodeProps) {
  return (
    <div
      className="px-4 py-2 rounded-lg bg-node-api/15 border-2 border-node-api/50 min-w-[100px] min-h-[44px] text-center flex flex-col justify-center"
      role="article"
      aria-label={`检查节点: ${data.label}${data.description ? `, ${data.description}` : ""}`}
    >
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="text-xs font-bold text-node-api">{data.label}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{data.description}</div>
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

function StartEndNode({ data }: NodeProps) {
  return (
    <div
      className="px-3 py-1.5 rounded-full bg-muted border border-muted-foreground/30 text-center min-h-[44px] flex items-center justify-center"
      role="article"
      aria-label={`${data.label} 节点`}
    >
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <div className="text-xs text-muted-foreground">{data.label}</div>
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
    </div>
  );
}

const nodeTypes = {
  llmNode: LLMNode,
  toolNode: ToolNodeComponent,
  checkNode: CheckNode,
  startEnd: StartEndNode,
};

// ============ Graph Builder ============

function buildFlowElements(graph: GraphStructure) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Add start node
  nodes.push({
    id: `${graph.name}__start__`,
    type: "startEnd",
    position: { x: 250, y: 20 },
    data: { label: "START" },
  });

  // Add end node
  nodes.push({
    id: `${graph.name}__end__`,
    type: "startEnd",
    position: { x: 470, y: 270 },
    data: { label: "END" },
  });

  // Position nodes
  const positions: Record<string, { x: number; y: number }> = {
    llm: { x: 180, y: 100 },
    tools: { x: 20, y: 270 },
    check_status: { x: 340, y: 270 },
  };

  graph.nodes.forEach((node) => {
    const pos = positions[node.id] || { x: 180, y: 180 };
    const typeMap: Record<string, string> = { llm: "llmNode", tool: "toolNode", check: "checkNode" };

    nodes.push({
      id: `${graph.name}_${node.id}`,
      type: typeMap[node.type] || "llmNode",
      position: pos,
      data: { label: node.label, description: node.description?.slice(0, 30) || "" },
    });
  });

  // Add edges
  graph.edges.forEach((edge, i) => {
    const sourceId = edge.source === "__start__"
      ? `${graph.name}__start__`
      : `${graph.name}_${edge.source}`;
    const targetId = edge.target === "__end__"
      ? `${graph.name}__end__`
      : `${graph.name}_${edge.target}`;
    const label = edge.source === "__start__"
      ? ""
      : edge.source === "llm" && edge.target === "tools"
        ? "调用工具"
        : edge.source === "llm" && edge.target === "__end__"
          ? "直接结束"
          : edge.source === "tools" && edge.target === "llm"
            ? "继续推理"
            : edge.label?.slice(0, 20) || "";

    edges.push({
      id: `${graph.name}_edge_${i}`,
      source: sourceId,
      target: targetId,
      label,
      type: "smoothstep",
      animated: edge.conditional,
      style: {
        stroke: edge.conditional ? BRAND_COLORS.warning : BRAND_COLORS.primary,
        strokeWidth: 1.5,
      },
      className: edge.conditional ? "motion-reduce:!transition-none motion-reduce:!animate-none" : undefined,
      labelStyle: { fontSize: 11, fill: BRAND_COLORS.muted },
      labelBgStyle: { fill: BRAND_COLORS.background, fillOpacity: 0.92 },
      labelBgPadding: [6, 4],
      labelBgBorderRadius: 4,
    });
  });

  return { nodes, edges };
}

// ============ Main Component ============

export default function LangGraphView({ graph }: LangGraphViewProps) {
  const { nodes, edges } = useMemo(() => {
    return buildFlowElements(graph);
  }, [graph]);

  return (
    <div
      className="w-full h-full relative"
      role="application"
      aria-label="LangGraph 结构可视化图"
    >
      <span className="sr-only">{graph.name}，包含 {nodes.length} 个节点和 {edges.length} 条连线</span>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        className="bg-card"
        nodesDraggable={false}
      >
        <Background color={BRAND_COLORS.borderStrong} gap={20} />
      </ReactFlow>
    </div>
  );
}
