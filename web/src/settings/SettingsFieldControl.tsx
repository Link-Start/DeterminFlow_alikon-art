import { useState, type ReactNode } from "react";
import { Eye, EyeOff, Lock } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { displayFieldValue, numericDisplayValue, parseNumericInput } from "./field-model";
import type { SettingsFieldSpec } from "./types";

interface SettingsFieldControlProps {
  spec: SettingsFieldSpec;
  value: unknown;
  error?: string;
  disabled?: boolean;
  onChange: (value: unknown) => void;
}

export function SettingsFieldControl({
  spec,
  value,
  error,
  disabled = false,
  onChange,
}: SettingsFieldControlProps) {
  const [revealSecret, setRevealSecret] = useState(false);
  const describedBy = [
    spec.description ? `${spec.id}-description` : "",
    error ? `${spec.id}-error` : "",
  ].filter(Boolean).join(" ") || undefined;
  const current = displayFieldValue(spec, value);
  const readonly = spec.readonly || spec.kind === "readonly";

  if (readonly) {
    return (
      <div className="flex min-h-11 items-center gap-2 text-sm text-muted-foreground">
        <Lock size={14} aria-hidden="true" />
        <span className="font-mono">{String(current ?? "")}</span>
      </div>
    );
  }

  if (spec.kind === "boolean") {
    return (
      <Switch
        id={spec.id}
        checked={Boolean(current)}
        onCheckedChange={onChange}
        disabled={disabled}
        aria-label={spec.label}
        aria-describedby={describedBy}
      />
    );
  }

  if (spec.kind === "select") {
    const selected = spec.options?.find((option) => option.value === String(current ?? ""));
    return (
      <Select
        value={String(current ?? "")}
        onValueChange={(next) => onChange(next)}
        disabled={disabled}
      >
        <SelectTrigger id={spec.id} aria-label={spec.label} className="min-h-11 w-full">
          <span className="truncate">{selected?.label || spec.placeholder || "请选择"}</span>
        </SelectTrigger>
        <SelectContent>
          {(spec.options || []).map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (spec.kind === "multiline" || spec.kind === "string-array") {
    return (
      <Textarea
        id={spec.id}
        value={String(current ?? "")}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        required={spec.required}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        placeholder={spec.kind === "string-array" ? "每行一个值" : spec.placeholder}
      />
    );
  }

  if (spec.kind === "number" || spec.kind === "integer") {
    const display = numericDisplayValue(spec, current);
    const showSlider = spec.scale != null && spec.min != null && spec.max != null && spec.step != null;
    const numericValue = display === "" ? spec.min ?? 0 : display;
    return (
      <div className="flex items-center gap-3">
        {showSlider ? (
          <Slider
            id={`${spec.id}-range`}
            min={spec.min}
            max={spec.max}
            step={spec.step}
            value={[numericValue]}
            onValueChange={([next]) => onChange(parseNumericInput(spec, String(next)))}
            disabled={disabled}
          />
        ) : null}
        <div className="flex items-center gap-2">
          <Input
            id={spec.id}
            type="number"
            min={spec.min}
            max={spec.max}
            step={spec.step ?? (spec.kind === "integer" ? 1 : "any")}
            value={display}
            onChange={(event) => onChange(parseNumericInput(spec, event.target.value))}
            disabled={disabled}
            required={spec.required}
            aria-invalid={Boolean(error)}
            aria-describedby={describedBy}
            className="min-h-11 w-28 text-center font-mono"
          />
          {spec.suffix ? <span className="text-xs text-muted-foreground">{spec.suffix}</span> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex items-center gap-2">
      <Input
        id={spec.id}
        type={spec.kind === "sensitive" && !revealSecret ? "password" : "text"}
        value={String(current ?? "")}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        required={spec.required}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        placeholder={spec.placeholder}
        autoComplete="off"
        className="min-h-11 font-mono"
      />
      {spec.kind === "sensitive" ? (
        <button
          type="button"
          onClick={() => setRevealSecret((currentState) => !currentState)}
          aria-label={revealSecret ? "隐藏密钥" : "显示密钥"}
          className="flex min-h-11 min-w-11 items-center justify-center text-muted-foreground hover:text-foreground"
        >
          {revealSecret ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      ) : null}
    </div>
  );
}

export function SettingsFieldList({ children }: { children: ReactNode }) {
  return (
    <div className="divide-y divide-border/30">
      {children}
    </div>
  );
}

export function SettingsFieldRow({
  spec,
  value,
  error,
  disabled,
  onChange,
}: SettingsFieldControlProps) {
  return (
    <div className="flex flex-col justify-between gap-2 py-4 sm:flex-row sm:items-center sm:gap-6">
      <div className="flex min-w-0 flex-col gap-1 sm:w-48 sm:flex-none">
        <Label htmlFor={spec.id} className="cursor-pointer">
          {spec.label}
          {spec.required ? <span className="text-destructive" aria-label="必填"> *</span> : null}
        </Label>
        {spec.description ? (
          <p id={`${spec.id}-description`} className="text-xs leading-5 text-muted-foreground">
            {spec.description}
          </p>
        ) : null}
      </div>
      <div className="min-w-0 flex-1 sm:max-w-md">
        <SettingsFieldControl
          spec={spec}
          value={value}
          error={error}
          disabled={disabled}
          onChange={onChange}
        />
        {error ? (
          <p id={`${spec.id}-error`} className="mt-1 text-xs text-destructive" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
