import { useCallback, useEffect, useRef, useState } from "react";
import { Plus } from "lucide-react";

import AddModelProviderDialog from "@/components/AddModelProviderDialog";
import ModelProviderCard, { type ModelProvider, type ProviderSchema } from "@/components/ModelProviderCard";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  addModelProvider,
  deleteModelProvider,
  discoverProviderModels,
  getModelProviders,
  getProviderSchemas,
  prioritizeModelProvider,
  updateModelProvider,
} from "@/lib/api";
import { cloneJson } from "../field-model";
import {
  absorbLoadedProviders,
  dirtyProviderIds,
  providersFromResponse,
  providerUpdatePayload,
} from "../models-draft";
import { parseApiError } from "../parse-api-error";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import { useRegisterSettingsStore } from "../SettingsWorkspace";
import type { SettingsSection } from "../types";

export function ModelsCategory({ section }: { section: SettingsSection }) {
  const [baseline, setBaseline] = useState<Record<string, ModelProvider>>({});
  const [drafts, setDrafts] = useState<Record<string, ModelProvider>>({});
  const [schemas, setSchemas] = useState<Record<string, ProviderSchema>>({});
  const [defaultProvider, setDefaultProvider] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const draftsRef = useRef(drafts);
  const baselineRef = useRef(baseline);
  draftsRef.current = drafts;
  baselineRef.current = baseline;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [providersData, schemasData] = await Promise.all([
        getModelProviders(),
        getProviderSchemas(),
      ]);
      const loaded = providersFromResponse(providersData.providers);
      const previous = baselineRef.current;
      setBaseline(loaded);
      setDrafts((current) => absorbLoadedProviders(loaded, current, previous));
      setDefaultProvider(providersData.default_provider || "");
      setSchemas(schemasData.schemas);
    } catch (loadError) {
      setError(parseApiError(loadError, "加载模型供应商失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = useCallback(async () => {
    const currentDrafts = draftsRef.current;
    const dirtyIds = dirtyProviderIds(baseline, currentDrafts);
    const failures: string[] = [];
    const saved: Record<string, ModelProvider> = {};
    for (const id of dirtyIds) {
      const captured = cloneJson(currentDrafts[id]);
      try {
        await updateModelProvider(id, providerUpdatePayload(captured));
        saved[id] = captured;
      } catch (saveError) {
        failures.push(`${captured.name || id}：${parseApiError(saveError)}`);
      }
    }
    if (Object.keys(saved).length > 0) {
      setBaseline((current) => ({ ...current, ...saved }));
    }
    if (failures.length > 0) throw new Error(failures.join("\n"));
  }, [baseline]);

  const discard = useCallback(() => {
    setDrafts(cloneJson(baseline));
  }, [baseline]);

  useRegisterSettingsStore({
    id: section.id,
    title: section.title,
    dirty: dirtyProviderIds(baseline, drafts).length > 0,
    save,
    discard,
  });

  return (
    <SettingsCategoryPanel
      sectionId={section.id}
      title={section.title}
      headerMeta={`${Object.keys(drafts).length} 个供应商`}
      headerActions={
        <Button type="button" variant="outline" onClick={() => setAddOpen(true)}>
          <Plus data-icon="inline-start" aria-hidden="true" />
          添加供应商
        </Button>
      }
      loading={loading}
      loadError={error}
      onRetry={() => void load()}
    >
      <div className="flex flex-col gap-4">
        {Object.values(drafts).map((provider) => (
          <ModelProviderCard
            key={provider.id}
            provider={provider}
            schemas={schemas}
            isDefault={provider.id === defaultProvider}
            onChange={(next) => setDrafts((current) => ({ ...current, [next.id]: next }))}
            onDelete={(id) => setDeleteId(id)}
            onPrioritize={async (id) => {
              try {
                await prioritizeModelProvider(id);
                await load();
              } catch (actionError) {
                setError(parseApiError(actionError, "设置首位供应商失败"));
              }
            }}
            onDiscoverModels={async (input) => {
              const result = await discoverProviderModels(input);
              return result.models;
            }}
          />
        ))}
        {!error && Object.keys(drafts).length === 0 ? (
          <p className="text-sm text-muted-foreground">还没有模型供应商。</p>
        ) : null}
      </div>
      <AddModelProviderDialog
        open={addOpen}
        schemas={schemas}
        existingProviderIds={Object.keys(drafts)}
        onClose={() => setAddOpen(false)}
        onAdd={async (input) => {
          await addModelProvider(input);
          await load();
        }}
        onDiscoverModels={async (input) => {
          const result = await discoverProviderModels(input);
          return result.models;
        }}
      />
      <Dialog
        open={Boolean(deleteId)}
        title="删除供应商"
        description={`确定删除供应商 ${deleteId || ""} 吗？此操作不可撤销。`}
        onClose={() => setDeleteId(null)}
      >
        <div className="mt-6 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setDeleteId(null)}>取消</Button>
          <Button
            type="button"
            variant="destructive"
            data-dialog-autofocus="true"
            onClick={async () => {
              if (!deleteId) return;
              try {
                await deleteModelProvider(deleteId);
                await load();
              } catch (deleteError) {
                setError(parseApiError(deleteError, "删除供应商失败"));
              } finally {
                setDeleteId(null);
              }
            }}
          >
            删除
          </Button>
        </div>
      </Dialog>
    </SettingsCategoryPanel>
  );
}
