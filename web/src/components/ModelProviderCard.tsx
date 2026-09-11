import { useState } from "react";
import {
  ArrowUp,
  ChevronDown,
  ChevronUp,
  LockKeyhole,
  RefreshCw,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SettingsFieldRow } from "@/settings/SettingsFieldControl";
import ModelListEditor from "./ModelListEditor";
import { mergeUniqueModels } from "../lib/model-options";
import type { ModelProvider, ProviderSchema } from "../types";

export type { ModelProvider, ProviderSchema } from "../types";

interface Props {
  provider: ModelProvider;
  schemas: Record<string, ProviderSchema>;
  isDefault: boolean;
  onChange: (provider: ModelProvider) => void;
  onDelete: (providerId: string) => void;
  onPrioritize: (providerId: string) => void;
  onDiscoverModels: (input: {
    provider_id: string;
    provider_type?: string;
    base_url?: string;
    api_key?: string;
  }) => Promise<string[]>;
}

export default function ModelProviderCard({
  provider,
  schemas,
  isDefault,
  onChange,
  onDelete,
  onPrioritize,
  onDiscoverModels,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [apiAddressExpanded, setApiAddressExpanded] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const schema = schemas[provider.provider_type] || null;
  const isManaged = provider.is_managed === true;

  const discoverModels = async () => {
    setDiscovering(true);
    setDiscoverError(null);
    try {
      const models = await onDiscoverModels({
        provider_id: provider.id,
        provider_type: provider.provider_type,
        base_url: provider.base_url,
        api_key: provider.api_key,
      });
      if (models.length === 0) {
        setDiscoverError("供应商未返回可选模型");
        return;
      }
      onChange({ ...provider, models: mergeUniqueModels(provider.models, models) });
    } catch (error) {
      setDiscoverError(error instanceof Error ? error.message : "拉取模型失败");
    } finally {
      setDiscovering(false);
    }
  };

  const updateProviderType = (providerType: string) => {
    const allowedHyperparams = new Set(Object.keys(schemas[providerType]?.hyperparams || {}));
    onChange({
      ...provider,
      provider_type: providerType,
      hyperparameter_values: Object.fromEntries(
        Object.entries(provider.hyperparameter_values).filter(([key]) => allowedHyperparams.has(key)),
      ),
    });
  };

  return (
    <article className={`rounded-xl border bg-card p-4 ${isDefault ? "border-primary/50" : "border-border"}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
            aria-label={expanded ? "折叠供应商配置" : "展开供应商配置"}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate text-base font-semibold text-foreground">{provider.name}</h3>
              {isManaged ? (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-primary/25 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                  <LockKeyhole size={11} aria-hidden="true" />
                  插件托管
                </span>
              ) : null}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {schema?.display_name || provider.provider_type} · {provider.models.length} 个模型
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {!isManaged && !isDefault ? (
            <Button type="button" variant="ghost" onClick={() => onPrioritize(provider.id)}>
              <ArrowUp data-icon="inline-start" aria-hidden="true" />
              设为首位
            </Button>
          ) : null}
          {!isManaged ? (
            <Button
              type="button"
              variant="ghost"
              onClick={() => onDelete(provider.id)}
              aria-label="删除供应商"
            >
              <Trash2 aria-hidden="true" />
            </Button>
          ) : null}
        </div>
      </div>

      {expanded && isManaged ? (
        <div className="mt-4 border-t border-border pt-4">
          <h4 className="text-sm font-medium text-foreground">可用模型</h4>
          <div className="mt-2 flex min-h-12 flex-wrap items-center gap-2 rounded-xl border border-border bg-secondary/40 p-2">
            {provider.models.length > 0 ? provider.models.map((model) => (
              <span
                key={model}
                className="max-w-full truncate rounded-lg border border-border bg-muted px-2.5 py-2 font-mono text-xs text-foreground"
              >
                {model}
              </span>
            )) : (
              <span className="px-2 text-sm text-muted-foreground">暂无可用模型</span>
            )}
          </div>
        </div>
      ) : null}

      {expanded && !isManaged ? (
        <div className="mt-4 space-y-4 border-t border-border pt-4">
          <SettingsFieldRow
            spec={{
              id: `provider-${provider.id}-type`,
              label: "供应商类型",
              kind: "select",
              options: Object.entries(schemas).map(([providerType, providerSchema]) => ({
                value: providerType,
                label: providerSchema.display_name,
              })),
            }}
            value={provider.provider_type}
            onChange={(value) => updateProviderType(String(value))}
          />
          <SettingsFieldRow
            spec={{
              id: `provider-${provider.id}-api-key`,
              label: "API Key",
              kind: "sensitive",
            }}
            value={provider.api_key}
            onChange={(value) => onChange({ ...provider, api_key: String(value ?? "") })}
          />
          <div>
            <div className="mb-2 flex items-end justify-between gap-4">
              <div>
                <h4 className="text-sm font-medium text-foreground">模型列表</h4>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {isDefault
                    ? "第一个会成为 Main 的默认模型，可拖动排序"
                    : "第一个是该供应商默认模型；设为首位后供 Main 使用"}
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => void discoverModels()}
                disabled={discovering}
              >
                <RefreshCw className={discovering ? "animate-spin motion-reduce:animate-none" : ""} data-icon="inline-start" />
                {discovering ? "拉取中" : "拉取模型"}
              </Button>
            </div>
            <ModelListEditor
              models={provider.models}
              onChange={(models) => onChange({ ...provider, models })}
              inputLabel={`为 ${provider.name} 输入模型`}
            />
            {discoverError ? <p className="mt-1 text-xs text-warning" role="alert">{discoverError}</p> : null}
          </div>
          <div className="rounded-lg border border-border bg-secondary/30">
            <button
              type="button"
              onClick={() => setApiAddressExpanded(!apiAddressExpanded)}
              aria-expanded={apiAddressExpanded}
              className="flex min-h-11 w-full items-center justify-between px-3 text-sm text-foreground hover:bg-secondary"
            >
              API 地址
              {apiAddressExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {apiAddressExpanded ? (
              <div className="border-t border-border p-3">
                <Input
                  value={provider.base_url}
                  onChange={(event) => onChange({ ...provider, base_url: event.target.value })}
                  aria-label="API 地址"
                  className="min-h-11 font-mono"
                />
              </div>
            ) : null}
          </div>
          <div className="space-y-3 border-t border-border pt-4">
            <h4 className="text-sm font-medium text-foreground">模型参数</h4>
            <SettingsFieldRow
              spec={{
                id: `provider-${provider.id}-max-context`,
                label: "最大上下文 Tokens",
                kind: "integer",
                min: 1000,
                step: 1000,
              }}
              value={provider.maxContextTokens ?? 128000}
              onChange={(value) => onChange({
                ...provider,
                maxContextTokens: typeof value === "number" ? value : 128000,
              })}
            />
            {schema ? Object.entries(schema.hyperparams).map(([key, param]) => (
              <SettingsFieldRow
                key={key}
                spec={{
                  id: `provider-${provider.id}-${key}`,
                  label: param.label,
                  kind: param.type === "boolean" ? "boolean" : param.type === "select" ? "select" : "number",
                  min: param.min,
                  max: param.max,
                  options: param.options?.map((option) => ({ value: option, label: option })),
                }}
                value={provider.hyperparameter_values[key] ?? param.default}
                onChange={(value) => onChange({
                  ...provider,
                  hyperparameter_values: {
                    ...provider.hyperparameter_values,
                    [key]: value,
                  },
                })}
              />
            )) : null}
          </div>
        </div>
      ) : null}
    </article>
  );
}
