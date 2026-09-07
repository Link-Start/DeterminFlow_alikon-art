import { useUrlParam } from "@/hooks/useUrlParam";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useDialog } from "@/components/ui/use-dialog";
import { useAccountLogin } from "@/components/ui/use-account-login";
import { useToast } from "@/components/ui/use-toast";
import { ACCOUNT_STATUS_EVENT, AccountApiError, fetchAccountStatus } from "@/lib/account";
import {
  createMarketplaceBridgeInvoker,
  isAllowedMarketplaceEmbedUrl,
  MARKETPLACE_BRIDGE_METHODS,
  MARKETPLACE_BRIDGE_READY_TIMEOUT_MS,
  MARKETPLACE_IFRAME_SANDBOX,
  MarketplaceBridgeHost,
  MarketplaceBridgeError,
  marketplaceConfirmPrompt,
  marketplaceEmbedOrigin,
  marketplaceHostLocale,
  type MarketplaceBridgeConfirmMethod,
  type MarketplaceBridgeApiMethod,
} from "@/lib/marketplace-bridge";
import { fetchMarketplaceStatus, navigateToCoreSkill, marketplaceSkillEmbedUrl, type MarketplaceStatus } from "@/lib/skill-marketplace";
import { useTheme } from "@/theme-context";
import { MarketplaceReportForm } from "./MarketplaceReportForm";
import type { MarketplaceConfirmationContext } from "@/lib/marketplace-request-lifecycle";

type HostPhase = "loading" | "unconfigured" | "connecting" | "ready" | "failed";

const invokeBridge = createMarketplaceBridgeInvoker();

export default function MarketplaceEmbedHost() {
  const { theme } = useTheme();
  const [requestedSkill] = useUrlParam("marketplace_skill");
  const { toast } = useToast();
  const dialog = useDialog();
  const login = useAccountLogin();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const hostRef = useRef<MarketplaceBridgeHost | null>(null);
  const accountLoginInFlight = useRef(0);
  const dialogEpoch = useRef(0);
  const statusRequestRef = useRef(0);
  const themeRef = useRef(theme);
  const locale = marketplaceHostLocale();
  const localeRef = useRef(locale);
  const [status, setStatus] = useState<MarketplaceStatus | null>(null);
  const [phase, setPhase] = useState<HostPhase>("loading");
  const [contentReady, setContentReady] = useState(false);
  const [generation, setGeneration] = useState(0);
  themeRef.current = theme;
  localeRef.current = locale;

  const embedUrl = status?.embed_url && isAllowedMarketplaceEmbedUrl(status.embed_url)
    ? marketplaceSkillEmbedUrl(status.embed_url, requestedSkill)
    : null;
  const expectedOrigin = embedUrl && status?.embed_url ? marketplaceEmbedOrigin(status.embed_url) : null;
  const recoveryUrl = status?.marketplace_url && isAllowedMarketplaceEmbedUrl(status.marketplace_url)
    ? status.marketplace_url
    : embedUrl;
  const showFrame = Boolean(embedUrl && expectedOrigin && (phase === "connecting" || phase === "ready"));

  const closeConfirmation = useCallback(() => {
    dialogEpoch.current += 1;
    dialog.cancelMatching("marketplace:");
  }, [dialog]);

  const loadStatus = useCallback(async () => {
    const requestId = ++statusRequestRef.current;
    closeConfirmation();
    setContentReady(false);
    setPhase("loading");
    setStatus(null);
    try {
      const next = await fetchMarketplaceStatus();
      if (requestId !== statusRequestRef.current) return;
      setStatus(next);
      if (!next.configured || !next.embed_url) {
        setPhase("unconfigured");
        return;
      }
      if (!isAllowedMarketplaceEmbedUrl(next.embed_url) || !marketplaceEmbedOrigin(next.embed_url)) {
        setPhase("failed");
        return;
      }
      setPhase("connecting");
    } catch {
      if (requestId === statusRequestRef.current) setPhase("failed");
    }
  }, [closeConfirmation]);

  useEffect(() => {
    void loadStatus();
    const onAccountChanged = () => {
      // Let a bridge-triggered login return to its caller before rebuilding private state.
      if (accountLoginInFlight.current > 0) return;
      hostRef.current?.reset();
      setGeneration((value) => value + 1);
      void loadStatus();
    };
    window.addEventListener(ACCOUNT_STATUS_EVENT, onAccountChanged);
    return () => {
      statusRequestRef.current += 1;
      window.removeEventListener(ACCOUNT_STATUS_EVENT, onAccountChanged);
    };
  }, [loadStatus]);

  const requestConfirmation = useCallback(async (
    method: MarketplaceBridgeConfirmMethod,
    payload: Record<string, unknown>,
    context: MarketplaceConfirmationContext,
  ) => {
    if (context.signal.aborted) return false;
    const key = `marketplace:confirm:${context.requestId}`;
    const cancel = () => dialog.cancelMatching(key);
    context.signal.addEventListener("abort", cancel, { once: true });
    try {
      return await dialog.confirm({ key, ...marketplaceConfirmPrompt(method, payload) });
    } finally {
      context.signal.removeEventListener("abort", cancel);
    }
  }, [dialog]);

  const requestLogin = useCallback(async () => {
    accountLoginInFlight.current += 1;
    try {
      await login();
      return await fetchMarketplaceStatus();
    } catch (error) {
      if (error instanceof AccountApiError) throw new MarketplaceBridgeError(error.code, error.message);
      throw error;
    } finally { accountLoginInFlight.current -= 1; }
  }, [login]);

  const invoke = useCallback((method: MarketplaceBridgeApiMethod, payload: Record<string, unknown>) => (
    method === "auth.login" ? requestLogin() : invokeBridge(method, payload)
  ), [requestLogin]);

  const openReport = useCallback(async (payload: Record<string, unknown>) => {
    const epoch = dialogEpoch.current;
    const account = await fetchAccountStatus();
    if (epoch !== dialogEpoch.current) return { reported: false };
    if (!account.signed_in) {
      const next = await requestLogin();
      if (!next.signed_in) return { reported: false };
    }
    if (epoch !== dialogEpoch.current) return { reported: false };
    const reported = await dialog.open<boolean>({
      key: `marketplace:report:${String(payload.slug)}:${String(payload.review_id ?? "resource")}`,
      title: payload.review_id ? "举报评价" : "举报资源",
      description: typeof payload.display_name === "string" ? payload.display_name : String(payload.slug),
      render: ({ resolve, cancel }) => <MarketplaceReportForm payload={payload} onSubmitted={() => resolve(true)} onCancel={cancel} />,
    });
    return { reported: reported === true };
  }, [dialog, requestLogin]);

  useEffect(() => {
    if (!embedUrl || !expectedOrigin) return;
    const host = new MarketplaceBridgeHost({
      expectedOrigin,
      getContentWindow: () => iframeRef.current?.contentWindow ?? null,
      postMessage: (message, targetOrigin) => {
        iframeRef.current?.contentWindow?.postMessage(message, targetOrigin);
      },
      invoke,
      openReport,
      openInstalledSkill: navigateToCoreSkill,
      confirm: requestConfirmation,
      notify: ({ title, detail, variant }) => {
        toast({ title, description: detail, variant });
      },
      onReady: () => setPhase("ready"),
      onRequest: () => setContentReady(true),
    });
    hostRef.current = host;
    const onMessage = (event: MessageEvent) => host.handleMessage(event);
    window.addEventListener("message", onMessage);
    const timer = window.setTimeout(() => {
      if (!host.isReady) setPhase("failed");
    }, MARKETPLACE_BRIDGE_READY_TIMEOUT_MS);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      host.reset();
      if (hostRef.current === host) hostRef.current = null;
      closeConfirmation();
    };
  }, [closeConfirmation, embedUrl, expectedOrigin, generation, invoke, openReport, requestConfirmation, toast]);

  useEffect(() => {
    if (phase !== "ready") return;
    hostRef.current?.sendHostInit({
      locale: localeRef.current,
      theme: themeRef.current,
      capabilities: [...MARKETPLACE_BRIDGE_METHODS],
    });
  }, [locale, phase, theme]);

  useEffect(() => {
    if (phase !== "ready" || contentReady) return;
    const timer = window.setTimeout(() => setPhase("failed"), MARKETPLACE_BRIDGE_READY_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [contentReady, phase]);

  const retry = () => {
    hostRef.current?.reset();
    setGeneration((value) => value + 1);
    void loadStatus();
  };

  const openInBrowser = () => {
    if (!recoveryUrl) return;
    window.open(recoveryUrl, "_blank", "noopener,noreferrer");
  };

  return (
    <div
      className="relative flex h-full min-h-0 min-w-0 flex-col bg-background"
      aria-label="资源广场"
      aria-busy={showFrame && !contentReady}
    >
      {phase === "unconfigured" ? (
        <HostNotice
          title="资源广场服务尚未配置"
          body="当前没有可用的资源广场地址。"
        />
      ) : null}
      {phase === "failed" ? (
        <HostNotice
          title="资源广场无法加载"
          action={(
            <>
              <Button type="button" onClick={retry}>重试</Button>
              {recoveryUrl ? (
                <Button type="button" variant="outline" onClick={openInBrowser}>
                  在浏览器打开
                </Button>
              ) : null}
            </>
          )}
        />
      ) : null}
      {phase === "loading" ? <HostNotice loading /> : null}
      {showFrame ? (
        <>
          {!contentReady ? (
            <div className="absolute inset-0 z-10 bg-background">
              <HostNotice loading />
            </div>
          ) : null}
          <iframe
            key={generation}
            ref={iframeRef}
            title="资源广场"
            src={embedUrl ?? undefined}
            sandbox={MARKETPLACE_IFRAME_SANDBOX}
            referrerPolicy="no-referrer"
            className={`h-full min-h-0 w-full flex-1 border-0 bg-background ${contentReady ? "opacity-100" : "opacity-0"}`}
            onError={() => setPhase("failed")}
          />
        </>
      ) : null}
    </div>
  );
}

function HostNotice({
  title,
  body,
  action,
  loading = false,
}: {
  title?: string;
  body?: string;
  action?: ReactNode;
  loading?: boolean;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col items-center justify-center gap-3 p-6 text-center">
      {loading ? (
        <p className="text-sm text-muted-foreground" role="status">正在加载资源广场</p>
      ) : (
        <>
          {title ? <p className="font-medium text-foreground" role="alert">{title}</p> : null}
          {body ? <p className="max-w-lg text-sm text-muted-foreground">{body}</p> : null}
          {action ? <div className="mt-2 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
        </>
      )}
    </div>
  );
}
