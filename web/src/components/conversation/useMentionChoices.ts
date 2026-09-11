import type { MentionResourceType } from "../../types";
import {
  filterMentionTypes, matchesFileMention, MENTION_FILE_OPTION, MENTION_TYPE_OPTIONS,
  type MentionChoiceOption, type MentionChoiceType,
} from "./mentionCatalog";
import { useMentionResources } from "./useMentionResources";

/** Reuse the existing paginated readers; only search all types after typing. */
export function useMentionChoices(
  sessionId: string | null, query: string, searchAll: boolean,
  selectedType: MentionChoiceType | null, open: boolean,
) {
  const globalSearch = open && searchAll && Boolean(query.trim());
  const matchingTypes = filterMentionTypes(query);
  const queryFor = (type: MentionResourceType) => globalSearch
    && matchingTypes.some((option) => option.type === type) ? "" : query;
  const enabled = (type: MentionResourceType) => open && (globalSearch || selectedType === type);
  const groups = {
    prompt: useMentionResources(sessionId, "prompt", queryFor("prompt"), enabled("prompt")),
    agent: useMentionResources(sessionId, "agent", queryFor("agent"), enabled("agent")),
    skill: useMentionResources(sessionId, "skill", queryFor("skill"), enabled("skill")),
    rule: useMentionResources(sessionId, "rule", queryFor("rule"), enabled("rule")),
    workflow: useMentionResources(sessionId, "workflow", queryFor("workflow"), enabled("workflow")),
    session: useMentionResources(sessionId, "session", queryFor("session"), enabled("session")),
  };
  // Keep incomplete/failed categories reachable so a partial search cannot hide them.
  const resourceOptions = globalSearch ? MENTION_TYPE_OPTIONS.filter(({ type }) =>
    groups[type].status !== "empty" || matchingTypes.some((option) => option.type === type),
  ) : MENTION_TYPE_OPTIONS;
  const showFile = !globalSearch || matchesFileMention(query);
  const typeOptions: readonly MentionChoiceOption[] = showFile
    ? [MENTION_FILE_OPTION, ...resourceOptions] : resourceOptions;
  const preferredType = showFile ? "file" : matchingTypes.find(({ type }) => groups[type].items.length > 0)?.type
    ?? resourceOptions.find(({ type }) => groups[type].items.length > 0)?.type
    ?? resourceOptions[0]?.type ?? null;
  const choiceType = selectedType && typeOptions.some(({ type }) => type === selectedType)
    ? selectedType : globalSearch ? preferredType : null;
  const resourceType = choiceType === "file" ? null : choiceType;
  return {
    typeOptions, selectedType: choiceType, resourceType, globalSearch,
    resources: groups[resourceType ?? "prompt"],
  };
}
