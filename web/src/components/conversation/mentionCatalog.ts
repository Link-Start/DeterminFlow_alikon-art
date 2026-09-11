import type { MentionResourceType } from "../../types";

export type MentionChoiceType = MentionResourceType | "file";
export interface MentionChoiceOption { type: MentionChoiceType; label: string }
export const MENTION_FILE_OPTION: MentionChoiceOption = { type: "file", label: "文件附件" };

export function matchesFileMention(query: string): boolean {
  return query.trim().toLocaleLowerCase().split(/\s+/).every(
    (term) => "file attachment 文件附件".includes(term),
  );
}

export const MENTION_TYPE_OPTIONS: readonly {
  type: MentionResourceType;
  label: string;
}[] = [
  { type: "prompt", label: "Prompt 提示词" },
  { type: "agent", label: "Agent 智能体" },
  { type: "skill", label: "Skill 技能" },
  { type: "rule", label: "Rule 规则" },
  { type: "workflow", label: "Workflow 工作流" },
  { type: "session", label: "会话" },
];

export function mentionTypeLabel(type: MentionResourceType): string {
  return MENTION_TYPE_OPTIONS.find((option) => option.type === type)?.label ?? type;
}

export function filterMentionTypes(query: string) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return MENTION_TYPE_OPTIONS.filter((option) => terms.every(
    (term) => `${option.type} ${option.label}`.toLocaleLowerCase().includes(term),
  ));
}

export function mentionOptionId(listboxId: string, index: number): string {
  return `${listboxId}-option-${index}`;
}
