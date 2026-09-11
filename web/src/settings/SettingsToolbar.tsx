import { Loader2, RotateCcw, Save, Settings } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSettingsWorkspace } from "./SettingsWorkspace";

export function SettingsToolbar() {
  const {
    stores,
    dirty,
    saving,
    outcome,
    categoryErrors,
    adminToken,
    setAdminToken,
    revealAdminToken,
    setRevealAdminToken,
    saveAll,
    discardAll,
  } = useSettingsWorkspace();
  const needsToken = stores.some((store) => store.requiresAdminToken);
  const dirtyTitles = stores.filter((store) => store.dirty).map((store) => store.title);
  const failedEntries = Object.entries(categoryErrors);

  return (
    <div className="sticky top-0 z-20 border-b border-border bg-background">
      <div className="flex w-full flex-col gap-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <Settings size={22} className="shrink-0 text-primary" aria-hidden="true" />
            <div className="min-w-0">
              <h1 className="text-xl font-bold text-foreground">系统配置</h1>
              {dirty ? <p className="mt-1 text-xs text-muted-foreground">{dirtyTitles.join("、")} 有未保存更改</p> : null}
              {outcome ? (
                <p
                  className={
                    outcome.tone === "success"
                      ? "mt-1 text-xs text-success"
                      : outcome.tone === "warning"
                        ? "mt-1 text-xs text-warning"
                        : "mt-1 text-xs text-destructive"
                  }
                  role="status"
                >
                  {outcome.text}
                </p>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {needsToken ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => setRevealAdminToken(!revealAdminToken)}
              >
                管理令牌
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              onClick={discardAll}
              disabled={!dirty || saving}
            >
              <RotateCcw data-icon="inline-start" aria-hidden="true" />
              放弃更改
            </Button>
            <Button
              type="button"
              onClick={() => void saveAll()}
              disabled={!dirty || saving}
            >
              {saving
                ? <Loader2 data-icon="inline-start" className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                : <Save data-icon="inline-start" aria-hidden="true" />}
              {saving ? "保存中" : "保存配置"}
            </Button>
          </div>
        </div>
        {needsToken && revealAdminToken ? (
          <div className="flex max-w-md flex-col gap-2">
            <Label htmlFor="settings-plugin-admin-token">远程管理令牌</Label>
            <Input
              id="settings-plugin-admin-token"
              type="password"
              autoComplete="off"
              value={adminToken}
              onChange={(event) => setAdminToken(event.target.value)}
              placeholder="本机直连且服务端未配置时可留空"
            />
          </div>
        ) : null}
        {failedEntries.length > 0 ? (
          <ul className="space-y-1 text-sm text-destructive" role="alert">
            {failedEntries.map(([id, message]) => {
              const title = stores.find((store) => store.id === id)?.title || id;
              return <li key={id}>{title}：{message}</li>;
            })}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
