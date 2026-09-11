import { parsePluginSettingsSchema } from "../extensions/plugin-model";
import type { PluginSettingsSchemaNode } from "../extensions/plugin-types";
import { MEMORY_FIELD_LABELS, MEMORY_FIELD_LIMITS } from "./memory-model";
import type { MemorySettings, SettingsFieldGroup, SettingsFieldSpec } from "./types";

function specFromSchemaNode(
  id: string,
  fallbackLabel: string,
  schema: PluginSettingsSchemaNode,
): SettingsFieldSpec | null {
  if (schema.type === "object") return null;
  const label = schema.title || fallbackLabel;
  if (schema.type === "boolean") {
    return { id, label, kind: "boolean", description: schema.description, default: schema.default };
  }
  if (schema.type === "array") {
    return { id, label, kind: "string-array", description: schema.description, default: schema.default };
  }
  if (schema.type === "string") {
    if (schema.enum?.length) {
      return {
        id,
        label,
        kind: "select",
        description: schema.description,
        default: schema.default,
        options: schema.enum.map((option) => ({ value: option, label: option })),
      };
    }
    return {
      id,
      label,
      kind: schema.format === "password" ? "sensitive" : schema.format === "multiline" ? "multiline" : "string",
      description: schema.description,
      default: schema.default,
    };
  }
  return {
    id,
    label,
    kind: schema.type === "integer" ? "integer" : "number",
    description: schema.description,
    default: schema.default,
    min: schema.minimum,
    max: schema.maximum,
    options: schema.enum?.map((option) => ({ value: String(option), label: String(option) })),
  };
}

function fallbackMemoryGroups(): SettingsFieldGroup[] {
  const numberSpec = (id: keyof MemorySettings, kind: "number" | "integer"): SettingsFieldSpec => ({
    id,
    label: MEMORY_FIELD_LABELS[id],
    kind,
    ...MEMORY_FIELD_LIMITS[id],
  });
  return [
    {
      id: "enable",
      title: "启用",
      fields: [
        { id: "enabled", label: MEMORY_FIELD_LABELS.enabled, kind: "boolean" },
        { id: "external_enabled", label: MEMORY_FIELD_LABELS.external_enabled, kind: "boolean" },
        { id: "provider_id", label: MEMORY_FIELD_LABELS.provider_id, kind: "select", options: [] },
      ],
    },
    {
      id: "recall",
      title: "自动召回",
      fields: [
        { id: "auto_recall_enabled", label: MEMORY_FIELD_LABELS.auto_recall_enabled, kind: "boolean" },
        {
          id: "recall_mode",
          label: MEMORY_FIELD_LABELS.recall_mode,
          kind: "select",
          options: [
            { value: "first", label: "首次有效输入" },
            { value: "every", label: "每次有效输入" },
          ],
        },
        numberSpec("recall_timeout_seconds", "number"),
        numberSpec("recall_max_chars", "integer"),
        numberSpec("recall_max_bytes", "integer"),
      ],
    },
    {
      id: "scheduler",
      title: "整理与调度",
      fields: [
        { id: "auto_consolidate_enabled", label: MEMORY_FIELD_LABELS.auto_consolidate_enabled, kind: "boolean" },
        numberSpec("consolidate_idle_seconds", "integer"),
        numberSpec("consolidate_length_tokens", "integer"),
        numberSpec("max_batch_turns", "integer"),
        numberSpec("max_concurrent_jobs", "integer"),
        numberSpec("max_retries", "integer"),
        numberSpec("lease_seconds", "integer"),
        numberSpec("extract_timeout_seconds", "number"),
        { id: "extract_model", label: MEMORY_FIELD_LABELS.extract_model, kind: "string" },
      ],
    },
  ];
}

export function memoryFieldGroups(schema: unknown): SettingsFieldGroup[] {
  const groups = fallbackMemoryGroups();
  const parsed = schema === undefined ? null : parsePluginSettingsSchema(schema);
  if (!parsed?.ok) return groups;
  for (const group of groups) {
    group.fields = group.fields.map((field) => {
      const node = parsed.schema.properties[field.id];
      if (!node || node.type === "object") return field;
      const overlay = specFromSchemaNode(field.id, field.label, node);
      if (!overlay) return field;
      return {
        ...field,
        ...overlay,
        kind: field.id === "provider_id" ? "select" : overlay.kind,
        options: overlay.options?.length ? overlay.options.map((option) => ({
          ...option,
          label: field.options?.find((original) => original.value === option.value)?.label || option.label,
        })) : field.options,
      };
    });
  }
  return groups;
}
