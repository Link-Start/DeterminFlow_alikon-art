import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TriangleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import {
  parsePluginSettingsSchema,
  schemaHasConfigurableFields,
  validatePluginSettings,
} from "@/extensions/plugin-model";
import type { PluginSettings } from "@/extensions/plugin-types";
import { resetPluginConfig, savePluginConfig } from "@/lib/plugin-api";
import { cloneJson, valuesEqual } from "../field-model";
import { isPluginAuthError, parseApiError } from "../parse-api-error";
import { PluginSettingsFields } from "../PluginSettingsFields";
import { useSettingsPlugins } from "../plugins-context";
import { SettingsCategoryPanel } from "../SettingsCategoryPanel";
import { useRegisterSettingsStore, useSettingsWorkspace } from "../SettingsWorkspace";
import type { SettingsSection } from "../types";

export function PluginCategory({ section }: { section: SettingsSection }) {
  const pluginId = section.plugin_id || "";
  const plugins = useSettingsPlugins();
  const { adminToken, setRevealAdminToken } = useSettingsWorkspace();
  const plugin = plugins.plugins.find((item) => item.id === pluginId);
  const [draft, setDraft] = useState<PluginSettings>({});
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const draftRef = useRef<PluginSettings>({});
  const pluginRef = useRef(plugin);
  const initializedId = useRef("");
  pluginRef.current = plugin;
  draftRef.current = draft;

  useEffect(() => {
    if (!plugin) return;
    if (initializedId.current !== plugin.id) {
      initializedId.current = plugin.id;
      setDraft(cloneJson(plugin.settings));
    }
  }, [plugin]);

  const parsedSchema = useMemo(
    () => plugin ? parsePluginSettingsSchema(plugin.settings_schema) : null,
    [plugin],
  );
  const validationErrors = useMemo(
    () => parsedSchema?.ok ? validatePluginSettings(parsedSchema.schema, draft) : {},
    [draft, parsedSchema],
  );

  const save = useCallback(async () => {
    const currentPlugin = pluginRef.current;
    if (!currentPlugin) throw new Error("插件不存在");
    if (parsedSchema?.ok && Object.keys(validatePluginSettings(parsedSchema.schema, draftRef.current)).length > 0) {
      throw new Error("请先修正字段错误");
    }
    const captured = cloneJson(draftRef.current);
    try {
      const result = await savePluginConfig(currentPlugin.id, captured, adminToken);
      if (result.plugin) {
        plugins.replacePlugin(result.plugin);
        if (valuesEqual(draftRef.current, captured)) {
          setDraft(cloneJson(result.plugin.settings));
        }
      }
    } catch (error) {
      if (isPluginAuthError(error)) setRevealAdminToken(true);
      throw new Error(parseApiError(error, "插件配置保存失败"));
    }
  }, [adminToken, parsedSchema, plugins, setRevealAdminToken]);

  const discard = useCallback(() => {
    if (pluginRef.current) setDraft(cloneJson(pluginRef.current.settings));
  }, []);

  useRegisterSettingsStore({
    id: section.id,
    title: section.title,
    dirty: Boolean(plugin && !valuesEqual(plugin.settings, draft)),
    requiresAdminToken: true,
    save,
    discard,
  });

  const loadError = !plugins.loading && !plugin
    ? "未找到该插件，仍可稍后重试加载。"
    : plugins.error;

  return (
    <SettingsCategoryPanel
      sectionId={section.id}
      title={section.title}
      description={section.description}
      loading={plugins.loading}
      loadError={actionError || loadError}
      onRetry={() => {
        setActionError(null);
        void plugins.load();
      }}
    >
      {plugin ? (
        <div className="flex flex-col gap-5">
          {plugin.restart_required ? (
            <p className="text-sm text-warning" role="status">配置已保存，重启后生效。</p>
          ) : null}
          {plugin.error ? (
            <p className="rounded-md border border-warning/40 bg-warning/5 p-3 text-sm text-warning" role="status">
              {plugin.error}
            </p>
          ) : null}
          {parsedSchema && !parsedSchema.ok ? (
            <p className="flex items-start gap-2 text-sm text-destructive" role="alert">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {parsedSchema.error}
            </p>
          ) : null}
          {parsedSchema?.ok && schemaHasConfigurableFields(parsedSchema.schema) ? (
            <PluginSettingsFields
              schema={parsedSchema.schema}
              settings={draft}
              errors={validationErrors}
              onChange={setDraft}
            />
          ) : parsedSchema?.ok ? (
            <p className="text-sm text-muted-foreground">该插件没有可配置字段。</p>
          ) : null}
          <div>
            <Button
              type="button"
              variant="outline"
              disabled={!plugin.config_present || resetting}
              onClick={() => setConfirmReset(true)}
            >
              清空已保存配置
            </Button>
          </div>
        </div>
      ) : null}
      <Dialog
        open={confirmReset}
        title="清空已保存配置"
        description="将删除该插件已保存的配置。此操作不可撤销。"
        onClose={() => setConfirmReset(false)}
      >
        <div className="mt-6 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => setConfirmReset(false)}>取消</Button>
          <Button
            type="button"
            variant="destructive"
            data-dialog-autofocus="true"
            disabled={resetting}
            onClick={async () => {
              if (!plugin) return;
              setResetting(true);
              try {
                const result = await resetPluginConfig(plugin.id, adminToken);
                if (result.plugin) {
                  plugins.replacePlugin(result.plugin);
                  setDraft(cloneJson(result.plugin.settings));
                }
                setConfirmReset(false);
              } catch (error) {
                if (isPluginAuthError(error)) setRevealAdminToken(true);
                setActionError(parseApiError(error, "清空插件配置失败"));
                setConfirmReset(false);
              } finally {
                setResetting(false);
              }
            }}
          >
            确认清空
          </Button>
        </div>
      </Dialog>
    </SettingsCategoryPanel>
  );
}
