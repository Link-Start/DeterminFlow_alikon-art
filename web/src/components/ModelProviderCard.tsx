import { useEffect, useState } from "react";
import {
  ArrowUp,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  LockKeyhole,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import ModelListEditor from "./ModelListEditor";
import { mergeUniqueModels } from "../lib/model-options";
import type { ModelProvider, ProviderSchema } from "../types";

export type { ModelProvider, ProviderSchema } from "../types";

interface Props {
  provider: ModelProvider;
  schemas: Record<string, ProviderSchema>;
  isDefault: boolean;
  onUpdate: (providerId: string, updates: Partial<ModelProvider>) => Promise<void>;
  onDelete: (providerId: string) => Promise<void>;
  onPrioritize: (providerId: string) => Promise<void>;
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
  onUpdate,
  onDelete,
  onPrioritize,
  onDiscoverModels,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const [apiAddressExpanded, setApiAddressExpanded] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);
  const [localProvider, setLocalProvider] = useState(provider);
  const [edited, setEdited] = useState(false);
  const [saving, setSaving] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const schema = schemas[localProvider.provider_type] || null;
  const isManaged = localProvider.is_managed === true;

  useEffect(() => {
    setLocalProvider(provider);
    setEdited(false);
  }, [provider]);

  const discoverModels = async () => {
    setDiscovering(true);
    setDiscoverError(null);
    try {
      const models = await onDiscoverModels({
        provider_id: provider.id,
        provider_type: localProvider.provider_type,
        base_url: localProvider.base_url,
        api_key: localProvider.api_key,
      });
      if (models.length === 0) {
        setDiscoverError("供应商未返回可选模型");
        return;
      }
      setLocalProvider((current) => {
        const nextModels = mergeUniqueModels(current.models, models);
        if (nextModels.length !== current.models.length) setEdited(true);
        return { ...current, models: nextModels };
      });
    } catch (error) {
      setDiscoverError(error instanceof Error ? error.message : "拉取模型失败");
    } finally {
      setDiscovering(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onUpdate(provider.id, {
        provider_type: localProvider.provider_type,
        name: localProvider.name,
        base_url: localProvider.base_url,
        api_key: localProvider.api_key,
        models: localProvider.models,
        maxContextTokens: localProvider.maxContextTokens,
        models_config: localProvider.models_config,
        hyperparameter_values: localProvider.hyperparameter_values,
      });
      setEdited(false);
    } finally {
      setSaving(false);
    }
  };

  const updateHyperparam = (key: string, value: unknown) => {
    setLocalProvider({
      ...localProvider,
      hyperparameter_values: {
        ...localProvider.hyperparameter_values,
        [key]: value,
      },
    });
    setEdited(true);
  };

  const updateProviderType = (providerType: string) => {
    const allowedHyperparams = new Set(
      Object.keys(schemas[providerType]?.hyperparams || {}),
    );
    setLocalProvider({
      ...localProvider,
      provider_type: providerType,
      hyperparameter_values: Object.fromEntries(
        Object.entries(localProvider.hyperparameter_values).filter(([key]) => (
          allowedHyperparams.has(key)
        )),
      ),
    });
    setEdited(true);
  };

  return (
    <article className={`rounded-xl border bg-card/50 p-4 ${isDefault ? "border-primary/50" : "border-border"}`}>
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
              <h4 className="truncate text-base font-semibold text-foreground">{localProvider.name}</h4>
              {isManaged && (
                <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-primary/25 bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                  <LockKeyhole size={11} aria-hidden="true" />
                  插件托管
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {schema?.display_name || localProvider.provider_type} · {localProvider.models.length} 个模型
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {!isManaged && !isDefault && (
            <button
              type="button"
              onClick={() => onPrioritize(provider.id)}
              className="flex min-h-11 items-center gap-1.5 rounded-lg px-3 text-xs text-muted-foreground hover:bg-primary/10 hover:text-primary"
            >
              <ArrowUp size={14} aria-hidden="true" />
              设为首位
            </button>
          )}
          {!isManaged && (
            <>
              <button
                type="button"
                onClick={handleSave}
                disabled={!edited || saving}
                aria-label="保存供应商配置"
                className="flex min-h-11 min-w-11 items-center justify-center rounded-lg text-success hover:bg-success/10 disabled:cursor-not-allowed disabled:text-muted-foreground"
              >
                {saving ? <RefreshCw size={16} className="animate-spin motion-reduce:animate-none" /> : <Save size={16} />}
              </button>
              <button
                type="button"
                onClick={() => onDelete(provider.id)}
                aria-label="删除供应商"
                className="flex min-h-11 min-w-11 items-center justify-center rounded-lg text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 size={16} />
              </button>
            </>
          )}
        </div>
      </div>

      {expanded && isManaged && (
        <div className="mt-4 border-t border-border/70 pt-4">
          <h5 className="text-sm font-medium text-foreground">可用模型</h5>
          <div className="mt-2 flex min-h-12 flex-wrap items-center gap-2 rounded-xl border border-border/80 bg-secondary/40 p-2">
            {localProvider.models.length > 0 ? localProvider.models.map((model) => (
              <span
                key={model}
                className="max-w-full truncate rounded-lg border border-border/80 bg-muted/70 px-2.5 py-2 font-mono text-xs text-foreground"
              >
                {model}
              </span>
            )) : (
              <span className="px-2 text-sm text-muted-foreground">暂无可用模型</span>
            )}
          </div>
        </div>
      )}

      {expanded && !isManaged && (
        <div className="mt-4 space-y-4 border-t border-border/70 pt-4">
          <label className="block text-sm text-foreground">
            供应商类型
            <select
              value={localProvider.provider_type}
              onChange={(event) => updateProviderType(event.target.value)}
              className="mt-1 min-h-11 w-full rounded-lg border border-border bg-secondary px-3 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
            >
              {Object.entries(schemas).map(([providerType, providerSchema]) => (
                <option key={providerType} value={providerType}>
                  {providerSchema.display_name}
                </option>
              ))}
            </select>
          </label>

          <div>
            <label htmlFor={`provider-${provider.id}-api-key`} className="mb-1 block text-sm text-foreground">API Key</label>
            <div className="relative">
              <input
                id={`provider-${provider.id}-api-key`}
                type={showApiKey ? "text" : "password"}
                value={localProvider.api_key}
                onChange={(event) => {
                  setLocalProvider({ ...localProvider, api_key: event.target.value });
                  setEdited(true);
                }}
                placeholder="输入 API Key"
                className="min-h-11 w-full rounded-lg border border-border bg-secondary px-3 pr-12 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                aria-label={showApiKey ? "隐藏 API Key" : "显示 API Key"}
                className="absolute right-1 top-0 flex min-h-11 min-w-11 items-center justify-center text-muted-foreground hover:text-foreground"
              >
                {showApiKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-end justify-between gap-4">
              <div>
                <h5 className="text-sm font-medium text-foreground">模型列表</h5>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {isDefault
                    ? "第一个会成为 Main 的默认模型，可拖动排序"
                    : "第一个是该供应商默认模型；设为首位后供 Main 使用"}
                </p>
              </div>
              <button
                type="button"
                onClick={discoverModels}
                disabled={discovering}
                className="flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-xs text-primary hover:bg-primary/10 disabled:opacity-50"
              >
                <RefreshCw size={14} className={discovering ? "animate-spin motion-reduce:animate-none" : ""} />
                {discovering ? "拉取中" : "拉取模型"}
              </button>
            </div>

            <ModelListEditor
              models={localProvider.models}
              onChange={(models) => {
                setLocalProvider({ ...localProvider, models });
                setEdited(true);
              }}
              inputLabel={`为 ${localProvider.name} 输入模型`}
            />
            {discoverError && <p className="mt-1 text-xs text-warning" role="alert">{discoverError}</p>}
          </div>

          <div className="rounded-lg border border-border/80 bg-secondary/30">
            <button
              type="button"
              onClick={() => setApiAddressExpanded(!apiAddressExpanded)}
              aria-expanded={apiAddressExpanded}
              className="flex min-h-11 w-full items-center justify-between px-3 text-sm text-foreground hover:bg-secondary/60"
            >
              API 地址
              {apiAddressExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {apiAddressExpanded && (
              <div className="border-t border-border/80 p-3">
                <input
                  value={localProvider.base_url}
                  onChange={(event) => {
                    setLocalProvider({ ...localProvider, base_url: event.target.value });
                    setEdited(true);
                  }}
                  aria-label="API 地址"
                  className="min-h-11 w-full rounded-lg border border-border bg-secondary px-3 font-mono text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  完整 API Base URL，包含版本路径（v1，不带末尾斜杠/）
                </p>
              </div>
            )}
          </div>

          <div className="space-y-3 border-t border-border/70 pt-4">
            <h5 className="text-sm font-medium text-foreground">模型参数</h5>
            <label className="flex items-center justify-between gap-4 text-sm text-foreground">
              最大上下文 Tokens
              <input
                type="number"
                min={1000}
                step={1000}
                value={localProvider.maxContextTokens ?? 128000}
                onChange={(event) => {
                  setLocalProvider({
                    ...localProvider,
                    maxContextTokens: Number(event.target.value) || 128000,
                  });
                  setEdited(true);
                }}
                className="min-h-10 w-36 rounded-lg border border-border bg-secondary px-3 text-right font-mono text-sm text-foreground outline-none focus:border-primary"
              />
            </label>
            {schema && Object.entries(schema.hyperparams).map(([key, param]) => {
                const value = localProvider.hyperparameter_values[key] ?? param.default;
                return (
                  <label key={key} className="flex items-center justify-between gap-4 text-sm text-foreground">
                    {param.label}
                    <input
                      type="number"
                      min={param.min}
                      max={param.max}
                      value={value == null ? "" : Number(value)}
                      onChange={(event) => updateHyperparam(key, event.target.value === "" ? null : Number(event.target.value))}
                      className="min-h-10 w-36 rounded-lg border border-border bg-secondary px-3 text-right font-mono text-sm text-foreground outline-none focus:border-primary"
                    />
                  </label>
                );
              })}
          </div>
        </div>
      )}
    </article>
  );
}
