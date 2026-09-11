import {
  coerceSettingsFieldValue,
  getSettingsValue,
  setSettingsValue,
  settingsFieldDisplayValue,
} from "../extensions/plugin-model";
import type {
  PluginObjectSchema,
  PluginSettings,
  PluginSettingsSchemaNode,
} from "../extensions/plugin-types";
import type { SettingsFieldSpec } from "./types";

export function pluginLeafFieldSpec(
  path: string[],
  name: string,
  schema: Exclude<PluginSettingsSchemaNode, PluginObjectSchema>,
  required: boolean,
): SettingsFieldSpec {
  const id = path.join("-");
  const label = schema.title || name;
  if (schema.type === "boolean") {
    return {
      id,
      label,
      kind: "boolean",
      required,
      description: schema.description,
      default: schema.default,
    };
  }
  if (schema.type === "array" || (schema.type === "string" && schema.format === "multiline")) {
    return {
      id,
      label,
      kind: schema.type === "array" ? "string-array" : "multiline",
      required,
      description: schema.description,
      default: schema.default,
    };
  }
  if ("enum" in schema && schema.enum && schema.enum.length > 0) {
    return {
      id,
      label,
      kind: "select",
      required,
      description: schema.description,
      default: schema.default,
      options: schema.enum.map((option) => ({ value: String(option), label: String(option) })),
    };
  }
  if (schema.type === "number" || schema.type === "integer") {
    return {
      id,
      label,
      kind: schema.type,
      required,
      description: schema.description,
      default: schema.default,
      min: schema.minimum,
      max: schema.maximum,
    };
  }
  const format = schema.type === "string" ? schema.format : undefined;
  return {
    id,
    label,
    kind: format === "password" ? "sensitive" : "string",
    required,
    description: schema.description,
    default: schema.default,
  };
}

export function pluginFieldValue(
  schema: Exclude<PluginSettingsSchemaNode, PluginObjectSchema>,
  settings: PluginSettings,
  path: string[],
): unknown {
  return getSettingsValue(settings, path);
}

export function pluginFieldDisplay(
  schema: Exclude<PluginSettingsSchemaNode, PluginObjectSchema>,
  value: unknown,
): string | boolean {
  return settingsFieldDisplayValue(schema, value ?? schema.default);
}

export function applyPluginFieldValue(
  settings: PluginSettings,
  schema: Exclude<PluginSettingsSchemaNode, PluginObjectSchema>,
  path: string[],
  value: unknown,
): PluginSettings {
  if (schema.type === "boolean") {
    return setSettingsValue(settings, path, Boolean(value));
  }
  if (typeof value === "string" || typeof value === "boolean") {
    return setSettingsValue(settings, path, coerceSettingsFieldValue(schema, value));
  }
  return setSettingsValue(settings, path, value);
}
