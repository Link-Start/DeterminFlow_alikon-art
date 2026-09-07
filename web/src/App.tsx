import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { MessageSquare, LayoutDashboard, GitBranch, Users, Layers, Settings, BookOpen, Wifi, WifiOff, FileText, Workflow, Clock, Boxes, Loader2, Store, type LucideIcon } from "lucide-react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ToastProvider } from "@/components/ui/toast-provider";
import { CORE_PAGE_SCROLL_MODE, CORE_TAB_IDS, isCoreTabId, type CoreTabId } from "@/core-tabs";
import { PRODUCT_NAME } from "@/brand";
import { BrandMark } from "@/components/BrandMark";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useGlobalEvents } from "./hooks/useGlobalEvents";
import { patchSearchParams, useUrlParam } from "./hooks/useUrlParam";
import { useExtensions } from "./extensions/context-value";
import { ExtensionHeaderStatusSlot } from "./extensions/ExtensionHeaderStatusSlot";
import { DesktopUpdateProvider } from "./desktop-updater/context";
import { DesktopUpdateNotice } from "./desktop-updater/DesktopUpdateNotice";
import { useNavigationSettings } from "./hooks/useNavigationSettings";
import FirstRunOnboarding from "./components/onboarding/FirstRunOnboarding";
import { AccountControl } from "./components/AccountControl";

const ChatPage = lazy(() => import("./pages/ChatPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const GraphPage = lazy(() => import("./pages/GraphPage"));
const RoundtablePage = lazy(() => import("./pages/RoundtablePage"));
const OrchestrationPage = lazy(() => import("./pages/OrchestrationPage"));
const WorkflowPage = lazy(() => import("./pages/WorkflowPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const ResourceMarketplacePage = lazy(() => import("./pages/ResourceMarketplacePage"));
const SkillsPage = lazy(() => import("./pages/SkillsPage"));
const RulesPage = lazy(() => import("./pages/RulesPage"));
const SystemPromptPage = lazy(() => import("./pages/SystemPromptPage"));
const CronPage = lazy(() => import("./pages/CronPage"));
const ExtensionsPage = lazy(() => import("./pages/ExtensionsPage"));

/** Tab 配置：value + 图标 + 标签 + active 样式 */
interface TabConfig {
  value: string;
  icon: LucideIcon;
  label: string;
  activeClass: string;
}

const CORE_ACTIVE_TAB_CLASS = "data-[state=active]:bg-primary/15 data-[state=active]:text-primary";

const CORE_TAB_METADATA: Record<CoreTabId, Omit<TabConfig, "value">> = {
  chat: { icon: MessageSquare, label: "对话", activeClass: CORE_ACTIVE_TAB_CLASS },
  dashboard: { icon: LayoutDashboard, label: "看板", activeClass: CORE_ACTIVE_TAB_CLASS },
  graph: { icon: GitBranch, label: "图谱", activeClass: CORE_ACTIVE_TAB_CLASS },
  roundtable: { icon: Users, label: "圆桌", activeClass: CORE_ACTIVE_TAB_CLASS },
  orchestration: { icon: Layers, label: "编排", activeClass: CORE_ACTIVE_TAB_CLASS },
  workflow: { icon: Workflow, label: "工作流", activeClass: CORE_ACTIVE_TAB_CLASS },
  cron: { icon: Clock, label: "定时", activeClass: CORE_ACTIVE_TAB_CLASS },
  marketplace: { icon: Store, label: "资源广场", activeClass: CORE_ACTIVE_TAB_CLASS },
  skills: { icon: BookOpen, label: "Skills", activeClass: CORE_ACTIVE_TAB_CLASS },
  rules: { icon: BookOpen, label: "Rules", activeClass: CORE_ACTIVE_TAB_CLASS },
  "system-prompt": { icon: FileText, label: "系统提示词", activeClass: CORE_ACTIVE_TAB_CLASS },
  settings: { icon: Settings, label: "配置", activeClass: CORE_ACTIVE_TAB_CLASS },
  extensions: { icon: Boxes, label: "插件", activeClass: CORE_ACTIVE_TAB_CLASS },
};

const CORE_TAB_CONFIG: TabConfig[] = CORE_TAB_IDS.map((value) => ({
  value,
  ...CORE_TAB_METADATA[value],
}));

/** 页面路由映射 */
const CORE_PAGE_MAP: Record<CoreTabId, React.ComponentType> = {
  chat: ChatPage,
  dashboard: DashboardPage,
  graph: GraphPage,
  roundtable: RoundtablePage,
  orchestration: OrchestrationPage,
  workflow: WorkflowPage,
  cron: CronPage,
  marketplace: ResourceMarketplacePage,
  skills: SkillsPage,
  rules: RulesPage,
  "system-prompt": SystemPromptPage,
  settings: SettingsPage,
  extensions: ExtensionsPage,
};

function GlobalConnectionStatus() {
  const { connected } = useGlobalEvents();

  return (
    <div className="flex shrink-0 items-center gap-3" aria-live="polite">
      <div className="flex items-center gap-2 text-sm">
        {connected ? (
          <Wifi size={14} className="text-success" aria-hidden="true" />
        ) : (
          <WifiOff size={14} className="text-destructive" aria-hidden="true" />
        )}
        <span className={`hidden xl:inline ${connected ? "text-success" : "text-destructive"}`}>
          {connected ? "已连接" : "断开"}
        </span>
        <span className="sr-only">
          {connected ? "WebSocket 已连接" : "WebSocket 连接断开"}
        </span>
      </div>
    </div>
  );
}

function PageLoadingFallback() {
  return (
    <div className="flex h-full min-h-0 items-center justify-center" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
        <span>正在加载页面...</span>
      </div>
    </div>
  );
}

function App() {
  const extensions = useExtensions();
  const showSystemPromptTab = useNavigationSettings();
  const [marketplaceAvailable, setMarketplaceAvailable] = useState(false);
  const [requestedTab, setRequestedTab] = useUrlParam("tab");
  const extensionPages = useMemo(() => extensions.flatMap((extension) => extension.pages || []), [extensions]);

  useEffect(() => {
    let active = true;
    fetch("/api/resource-marketplace/status")
      .then((response) => {
        if (active) setMarketplaceAvailable(response.ok);
      })
      .catch(() => {
        if (active) setMarketplaceAvailable(false);
      });
    return () => { active = false; };
  }, []);

  const tabs = useMemo<TabConfig[]>(() => [
    ...CORE_TAB_CONFIG.filter((tab) => (
      (tab.value !== "system-prompt" || showSystemPromptTab)
      && (tab.value !== "marketplace" || marketplaceAvailable)
    )),
    ...extensionPages.map((page) => ({
      value: page.id,
      icon: page.icon,
      label: page.label,
      activeClass: CORE_ACTIVE_TAB_CLASS,
    })),
  ], [extensionPages, marketplaceAvailable, showSystemPromptTab]);
  const activeTab = tabs.some((tab) => tab.value === requestedTab)
    ? requestedTab!
    : "chat";
  const ExtensionPage = extensionPages.find((page) => page.id === activeTab)?.component;
  const coreTabId = isCoreTabId(activeTab) ? activeTab : null;
  const CorePage = coreTabId ? CORE_PAGE_MAP[coreTabId] : undefined;
  const pageScrollMode = coreTabId ? CORE_PAGE_SCROLL_MODE[coreTabId] : "document";

  const handleTabChange = (value: string) => {
    setRequestedTab(value === "chat" ? null : value);
  };

  const handleManageExtension = (extensionId: string) => {
    const nextSearch = patchSearchParams(window.location.search, {
      tab: "extensions",
      plugin: extensionId,
    });
    window.history.pushState(window.history.state, "", `${window.location.pathname}${nextSearch}${window.location.hash}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  };

  return (
    <DesktopUpdateProvider>
      <ToastProvider>
        <FirstRunOnboarding>
          <div className="flex h-dvh flex-col overflow-hidden bg-background">
            {/* Top Navigation Bar */}
            <header className="fixed top-0 left-0 right-0 z-50 h-14 border-b border-border bg-card">
              <div className="h-full flex items-center gap-3 px-4">
                {/* Brand */}
                <div className="flex shrink-0 items-center gap-3">
                  <BrandMark
                    alt={PRODUCT_NAME}
                    className="h-8 w-8 shrink-0"
                  />
                  <h1
                    className="hidden text-lg font-semibold tracking-tight text-foreground 2xl:block"
                    aria-hidden="true"
                  >
                    {PRODUCT_NAME}
                  </h1>
                </div>

                {/* Tabs */}
                <Tabs className="min-w-0 flex-1" value={activeTab} onValueChange={handleTabChange}>
                  <div className="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                    <TabsList className="w-max justify-start border border-border bg-secondary/60" role="tablist" aria-label="主导航">
                      {tabs.map((tab) => {
                        const Icon = tab.icon;
                        return (
                          <TabsTrigger
                            key={tab.value}
                            value={tab.value}
                            className={`gap-2 ${tab.activeClass}`}
                            role="tab"
                            aria-selected={activeTab === tab.value}
                          >
                            <Icon size={16} aria-hidden="true" />
                            <span>{tab.label}</span>
                          </TabsTrigger>
                        );
                      })}
                    </TabsList>
                  </div>
                </Tabs>

                <ExtensionHeaderStatusSlot onManage={handleManageExtension} />
                <AccountControl />
                <GlobalConnectionStatus />
                <ThemeToggle />
              </div>
            </header>

            {/* Main Content */}
            <main className="min-h-0 min-w-0 flex-1 overflow-hidden pt-14" role="main" aria-label="主内容区域">
              <div
                className={`h-full min-h-0 min-w-0 ${
                  pageScrollMode === "document"
                    ? "overflow-y-auto overscroll-contain"
                    : "overflow-hidden"
                }`}
                data-page-scroll-mode={pageScrollMode}
              >
                <Suspense fallback={<PageLoadingFallback />}>
                  {CorePage ? <CorePage /> : ExtensionPage ? <ExtensionPage /> : null}
                </Suspense>
              </div>
            </main>
            <DesktopUpdateNotice onOpenSettings={() => handleTabChange("settings")} />
          </div>
        </FirstRunOnboarding>
      </ToastProvider>
    </DesktopUpdateProvider>
  );
}

export default App;
