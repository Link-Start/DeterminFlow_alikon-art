import assert from "node:assert/strict";
import test from "node:test";

import type { ModelProvider } from "../types";
import {
  absorbLoadedProviders,
  dirtyProviderIds,
  providersFromResponse,
} from "./models-draft.ts";

const base = {
  provider_type: "openai",
  base_url: "https://example.invalid/v1",
  api_key: "secret",
  models: ["demo"],
  hyperparameter_values: {},
} satisfies Omit<ModelProvider, "id" | "name">;

test("keeps dirty provider drafts when the list reloads", () => {
  const loaded = providersFromResponse({
    a: { ...base, name: "A" },
    b: { ...base, name: "B" },
  });
  const drafts = {
    a: { ...loaded.a, api_key: "changed" },
    b: loaded.b,
  };
  const next = absorbLoadedProviders(loaded, drafts);
  assert.equal(next.a.api_key, "changed");
  assert.equal(next.b.api_key, "secret");
  assert.deepEqual(dirtyProviderIds(loaded, next), ["a"]);
});


test("accepts refreshed provider data when its draft was clean", () => {
  const previous = providersFromResponse({a: {...base, name: "Old"}});
  const loaded = providersFromResponse({a: {...base, name: "New"}});
  assert.equal(absorbLoadedProviders(loaded, previous, previous).a.name, "New");
});
