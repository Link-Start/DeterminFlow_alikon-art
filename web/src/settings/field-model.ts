import type { ConfigItemMeta } from "../types";
import type { SettingsFieldSpec, SettingsScalar } from "./types";

export function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function stableSerialize(value: unknown): string {
  return JSON.stringify(value);
}

export function valuesEqual(left: unknown, right: unknown): boolean {
  return stableSerialize(left) === stableSerialize(right);
}

export function displayFieldValue(spec: SettingsFieldSpec, value: unknown): unknown {
  return value === undefined || value === null ? spec.default : value;
}

export function numericDisplayValue(spec: SettingsFieldSpec, value: unknown): number | "" {
  const raw = displayFieldValue(spec, value);
  if (typeof raw !== "number" || !Number.isFinite(raw)) return "";
  return spec.scale ? raw * spec.scale : raw;
}

export function parseNumericInput(
  spec: SettingsFieldSpec,
  input: string,
): number | undefined {
  if (input.trim() === "") return undefined;
  const parsed = Number(input);
  if (!Number.isFinite(parsed)) return undefined;
  const stored = spec.scale ? parsed / spec.scale : parsed;
  return spec.kind === "integer" ? Math.trunc(stored) : stored;
}

export function fieldSpecFromConfigMeta(item: ConfigItemMeta): SettingsFieldSpec {
  if (item.readonly) {
    return {
      id: item.key,
      label: item.label,
      kind: "readonly",
      readonly: true,
    };
  }
  if (item.type === "boolean") {
    return { id: item.key, label: item.label, kind: "boolean" };
  }
  if (item.type === "select") {
    return {
      id: item.key,
      label: item.label,
      kind: "select",
      options: (item.options || []).map((option) => ({ value: option, label: option })),
    };
  }
  if (item.type === "number") {
    return {
      id: item.key,
      label: item.label,
      kind: "number",
      min: item.min,
      max: item.max,
      step: item.step,
    };
  }
  return {
    id: item.key,
    label: item.label,
    kind: item.sensitive ? "sensitive" : "string",
  };
}

export function editedKeysForGroup(
  edited: Record<string, SettingsScalar>,
  meta: ConfigItemMeta[],
  group: string,
): string[] {
  const groupKeys = new Set(
    meta.filter((item) => item.group === group).map((item) => item.key),
  );
  return Object.keys(edited).filter((key) => groupKeys.has(key));
}

export function reconcileEditedAfterSave(args: {
  edited: Record<string, SettingsScalar>;
  captured: Record<string, SettingsScalar>;
  nextConfig: Record<string, SettingsScalar>;
  savedKeys: string[];
}): Record<string, SettingsScalar> {
  const next = { ...args.edited };
  for (const key of args.savedKeys) {
    if (!(key in next)) continue;
    if (valuesEqual(next[key], args.captured[key]) || valuesEqual(next[key], args.nextConfig[key])) {
      delete next[key];
    }
  }
  return next;
}

export function updateEditedValue(
  edited: Record<string, SettingsScalar>,
  baseline: Record<string, SettingsScalar>,
  key: string,
  value: SettingsScalar,
  inFlightKeys: ReadonlySet<string>,
): Record<string, SettingsScalar> {
  const next = { ...edited, [key]: value };
  // Returning to the old baseline while a write is pending is still a new edit.
  if (baseline[key] === value && !inFlightKeys.has(key)) delete next[key];
  return next;
}

export function isSensitiveField(spec: SettingsFieldSpec): boolean {
  return spec.kind === "sensitive";
}

export function isEnumField(spec: SettingsFieldSpec): boolean {
  return spec.kind === "select" && Boolean(spec.options?.length);
}
