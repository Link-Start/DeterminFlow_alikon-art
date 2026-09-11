import { SettingsFieldList, SettingsFieldRow } from "./SettingsFieldControl";
import type { SettingsFieldGroup } from "./types";

interface SettingsFieldGroupsProps {
  groups: SettingsFieldGroup[];
  values: Record<string, unknown> | unknown;
  errors?: Record<string, string>;
  disabled?: boolean;
  isFieldDisabled?: (fieldId: string) => boolean;
  onChange: (fieldId: string, value: unknown) => void;
  resolveValue?: (fieldId: string) => unknown;
}

export function SettingsFieldGroups({
  groups,
  values,
  errors = {},
  disabled,
  isFieldDisabled,
  onChange,
  resolveValue,
}: SettingsFieldGroupsProps) {
  return (
    <div className="flex flex-col gap-8">
      {groups.map((group) => (
        <section key={group.id} aria-labelledby={`${group.id}-heading`} className="flex flex-col gap-4">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <h3 id={`${group.id}-heading`} className="text-sm font-semibold text-foreground">
              {group.title}
            </h3>
            {group.description ? (
              <p className="text-xs text-muted-foreground">{group.description}</p>
            ) : null}
          </div>
          <SettingsFieldList>
            {group.fields.map((field) => (
              <SettingsFieldRow
                key={field.id}
                spec={field}
                value={
                  resolveValue
                    ? resolveValue(field.id)
                    : (values as Record<string, unknown>)[field.id]
                }
                error={errors[field.id]}
                disabled={disabled || isFieldDisabled?.(field.id)}
                onChange={(value) => onChange(field.id, value)}
              />
            ))}
          </SettingsFieldList>
        </section>
      ))}
    </div>
  );
}
