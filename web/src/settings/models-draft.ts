import type { ModelProvider } from "../types";
import { valuesEqual } from "./field-model";

export function providersFromResponse(
  providers: Record<string, Omit<ModelProvider, "id">>,
): Record<string, ModelProvider> {
  return Object.fromEntries(
    Object.entries(providers).map(([id, provider]) => [
      id,
      {
        id,
        ...provider,
        hyperparameter_values: provider.hyperparameter_values || {},
      },
    ]),
  );
}

export function absorbLoadedProviders(
  loaded: Record<string, ModelProvider>,
  drafts: Record<string, ModelProvider>,
  baseline: Record<string, ModelProvider> = loaded,
): Record<string, ModelProvider> {
  const next = { ...loaded };
  for (const [id, draft] of Object.entries(drafts)) {
    const current = loaded[id];
    if (!current || current.is_managed) continue;
    if (baseline[id] && !valuesEqual(draft, baseline[id])) next[id] = draft;
  }
  return next;
}

export function dirtyProviderIds(
  baseline: Record<string, ModelProvider>,
  drafts: Record<string, ModelProvider>,
): string[] {
  return Object.keys(drafts).filter((id) => {
    const draft = drafts[id];
    const original = baseline[id];
    if (!draft || !original || draft.is_managed) return false;
    return !valuesEqual(draft, original);
  });
}

export function providerUpdatePayload(provider: ModelProvider): Partial<ModelProvider> {
  return {
    provider_type: provider.provider_type,
    name: provider.name,
    base_url: provider.base_url,
    api_key: provider.api_key,
    models: provider.models,
    maxContextTokens: provider.maxContextTokens,
    models_config: provider.models_config,
    hyperparameter_values: provider.hyperparameter_values,
  };
}
