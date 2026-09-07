import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench, Layers, Edit3 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ToolInfo, ToolGroup, AgentDefinitionData } from "../../types";
import ToolGroupEditor from "./ToolGroupEditor";

interface Props {
  tools: ToolInfo[];
  groups: ToolGroup[];
  agents: AgentDefinitionData[];
  onReload?: () => void;
}

// 前端预定义调色板（按 group_id 映射），不再硬编码 source 映射
const GROUP_COLORS: Record<string, string> = {
  memory: "text-primary",
  coding: "text-success",
  session_main: "text-primary",
  communication: "text-info",
  config: "text-warning",
  skills: "text-primary",
};

const DEFAULT_GROUP_COLOR = "text-muted-foreground";

function getGroupColor(groupId: string): string {
  return GROUP_COLORS[groupId] || DEFAULT_GROUP_COLOR;
}

function getGroupInfo(groups: ToolGroup[], groupId: string): ToolGroup | undefined {
  return groups.find((g) => g.id === groupId);
}

export default function ToolListViewer({ tools, groups, agents, onReload }: Props) {
  const [expandedGroup, setExpandedGroup] = useState<string | null>("memory");
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [showMatrix, setShowMatrix] = useState(false);
  const [showGroupEditor, setShowGroupEditor] = useState(false);

  // Group tools by group_id
  const toolGroups: Record<string, ToolInfo[]> = {};
  tools.forEach((t) => {
    const gid = t.group_id || "__ungrouped__";
    if (!toolGroups[gid]) toolGroups[gid] = [];
    toolGroups[gid].push(t);
  });

  // Build agent-tool matrix
  const agentToolMap = (agent: AgentDefinitionData, toolName: string): boolean => {
    if (agent.disallowed_tools?.includes(toolName)) return false;
    if (!agent.tools) return false;
    if (agent.tools.includes("*")) return true;
    return agent.tools.includes(toolName);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">工具列表</h3>
          <Badge variant="outline" className="text-xs text-success border-success/30">
            {tools.length} 个
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowGroupEditor(true)}
            aria-label="编辑工具分组"
            className="px-2 py-1 min-h-[44px] text-xs rounded-md bg-secondary/60 text-muted-foreground hover:text-foreground transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:outline-none"
          >
            <Edit3 size={12} aria-hidden="true" /> 编辑组
          </button>
          <button
            type="button"
            onClick={() => setShowMatrix(!showMatrix)}
            aria-label={showMatrix ? "隐藏分配矩阵" : "显示分配矩阵"}
            className={`px-2 py-1 min-h-[44px] text-xs rounded-md transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:outline-none ${
              showMatrix ? "bg-primary/20 text-primary" : "bg-secondary/60 text-muted-foreground hover:text-foreground"
            }`}
          >
            <Layers size={12} aria-hidden="true" /> 分配矩阵
          </button>
        </div>
      </div>

      {/* Tool Groups (Accordion) */}
      {!showMatrix && (
        <div className="space-y-2">
          {Object.entries(toolGroups).map(([groupId, groupTools]) => {
            const groupInfo = getGroupInfo(groups, groupId);
            const label = groupInfo?.name || groupId;
            const color = getGroupColor(groupId);
            const isOpen = expandedGroup === groupId;

            return (
              <div key={groupId} className="bg-secondary/80 border border-border/30 rounded-lg overflow-hidden">
                <button
                  type="button"
                  onClick={() => setExpandedGroup(isOpen ? null : groupId)}
                  aria-expanded={isOpen}
                  aria-label={`${isOpen ? "折叠" : "展开"} ${label} 分组`}
                  className="w-full flex items-center gap-2 px-3 py-2.5 text-left cursor-pointer hover:bg-secondary/30 transition-colors focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:outline-none"
                >
                  {isOpen ? <ChevronDown size={14} aria-hidden="true" className="text-muted-foreground" /> : <ChevronRight size={14} aria-hidden="true" className="text-muted-foreground" />}
                  <Wrench size={14} aria-hidden="true" className={color} />
                  <span className={`text-xs font-medium ${color}`}>{label}</span>
                  <Badge variant="outline" className="text-xs ml-auto">{groupTools.length}</Badge>
                </button>

                {isOpen && (
                  <div className="px-3 pb-2 space-y-1.5">
                    {groupTools.map((tool) => {
                      const isToolExpanded = expandedTool === tool.name;
                      return (
                        <div key={tool.name} className="bg-secondary/40 rounded-md px-2.5 py-2">
                          <div
                            className="flex items-center gap-2 cursor-pointer"
                            role="button"
                            tabIndex={0}
                            aria-expanded={isToolExpanded}
                            onClick={() => setExpandedTool(isToolExpanded ? null : tool.name)}
                            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setExpandedTool(isToolExpanded ? null : tool.name); }}
                          >
                            <Wrench size={11} aria-hidden="true" className="text-muted-foreground flex-shrink-0" />
                            <span className="text-xs font-mono text-info flex-1 truncate">{tool.name}</span>
                            {isToolExpanded ? <ChevronDown size={12} aria-hidden="true" className="text-muted-foreground" /> : <ChevronRight size={12} aria-hidden="true" className="text-muted-foreground" />}
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5 ml-5 line-clamp-2">{tool.description}</p>
                          {isToolExpanded && Object.keys(tool.parameters).length > 0 && (
                            <div className="mt-2 ml-5 bg-card/60 rounded px-2 py-1.5">
                              <span className="text-xs text-muted-foreground block mb-1">参数:</span>
                              {Object.entries(tool.parameters).map(([pName, pSchema]) => (
                                <div key={pName} className="flex items-center gap-2 text-xs">
                                  <span className="text-warning font-mono">{pName}</span>
                                  <span className="text-muted-foreground">{(pSchema as { type?: string })?.type || "any"}</span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Agent-Tool Matrix */}
      {showMatrix && (
        <div className="bg-secondary/80 border border-border/30 rounded-lg p-3 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border/50">
                <th scope="col" className="text-left py-1.5 px-2 text-muted-foreground font-medium sticky left-0 bg-secondary/90">工具</th>
                {agents.map((a) => (
                  <th scope="col" key={a.agent_type} className="text-center py-1.5 px-2 text-primary font-medium whitespace-nowrap">
                    {a.agent_type}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tools.filter((t) => t.group_id !== "communication").map((tool) => (
                <tr key={tool.name} className="border-b border-border/20 hover:bg-secondary/20">
                  <td className="py-1 px-2 font-mono text-info sticky left-0 bg-secondary/90 whitespace-nowrap">{tool.name}</td>
                  {agents.map((a) => (
                    <td key={a.agent_type} className="py-1 px-2 text-center">
                      {agentToolMap(a, tool.name) ? (
                        <span className="inline-block w-3 h-3 rounded-full bg-success/30 border border-success/60" aria-hidden="true" />
                      ) : (
                        <span className="inline-block w-3 h-3 rounded-full bg-muted/50 border border-border/30" aria-hidden="true" />
                      )}
                      <span className="sr-only">{agentToolMap(a, tool.name) ? "已分配" : "未分配"}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tool Group Editor Modal */}
      <ToolGroupEditor
        tools={tools}
        groups={groups}
        open={showGroupEditor}
        onClose={() => setShowGroupEditor(false)}
        onGroupsChange={() => onReload?.()}
      />
    </div>
  );
}
