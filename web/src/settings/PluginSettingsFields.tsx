import { SettingsFieldList, SettingsFieldRow } from "./SettingsFieldControl";
import {
  applyPluginFieldValue,
  pluginFieldDisplay,
  pluginLeafFieldSpec,
} from "./plugin-fields";
import type {
  PluginObjectSchema,
  PluginSettings,
  PluginSettingsSchemaNode,
} from "../extensions/plugin-types";

interface PluginSettingsFieldsProps {
  schema: PluginObjectSchema;
  settings: PluginSettings;
  path?: string[];
  errors: Record<string, string>;
  disabled?: boolean;
  onChange: (next: PluginSettings) => void;
}

function PluginLeaf({
  name,
  schema,
  path,
  settings,
  required,
  error,
  disabled,
  onChange,
}: {
  name: string;
  schema: Exclude<PluginSettingsSchemaNode, PluginObjectSchema>;
  path: string[];
  settings: PluginSettings;
  required: boolean;
  error?: string;
  disabled?: boolean;
  onChange: (next: PluginSettings) => void;
}) {
  const spec = pluginLeafFieldSpec(path, name, schema, required);
  const raw = path.reduce<unknown>((current, segment) => (
    current && typeof current === "object"
      ? (current as Record<string, unknown>)[segment]
      : undefined
  ), settings);
  const display = (schema.type === "integer" || schema.type === "number")
    ? raw ?? schema.default
    : pluginFieldDisplay(schema, raw);

  return (
    <SettingsFieldRow
      spec={spec}
      value={schema.type === "boolean" ? Boolean(display) : display}
      error={error}
      disabled={disabled}
      onChange={(value) => onChange(applyPluginFieldValue(settings, schema, path, value))}
    />
  );
}

export function PluginSettingsFields({
  schema,
  settings,
  path = [],
  errors,
  disabled,
  onChange,
}: PluginSettingsFieldsProps) {
  return (
    <SettingsFieldList>
      {Object.entries(schema.properties).map(([name, childSchema]) => {
        if (childSchema.deprecated) return null;
        const childPath = [...path, name];
        const childKey = childPath.join(".");
        if (childSchema.type === "object") {
          return (
            <fieldset key={childKey} className="flex flex-col gap-4 rounded-md border p-4">
              <legend className="px-1 text-sm font-medium">
                {childSchema.title || name}
              </legend>
              {childSchema.description ? (
                <p className="text-xs text-muted-foreground">{childSchema.description}</p>
              ) : null}
              <PluginSettingsFields
                schema={childSchema}
                settings={settings}
                path={childPath}
                errors={errors}
                disabled={disabled}
                onChange={onChange}
              />
            </fieldset>
          );
        }
        return (
          <PluginLeaf
            key={childKey}
            name={name}
            schema={childSchema}
            path={childPath}
            settings={settings}
            required={Boolean(schema.required?.includes(name))}
            error={errors[childKey]}
            disabled={disabled}
            onChange={onChange}
          />
        );
      })}
    </SettingsFieldList>
  );
}
