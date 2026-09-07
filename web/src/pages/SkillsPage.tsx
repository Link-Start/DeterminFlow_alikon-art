import { MarketplaceSkillUpdateButton } from "@/components/marketplace/MarketplaceSkillUpdateButton";
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { BookOpen, Code, Search, MessageSquare, Brain, Workflow, GraduationCap, RefreshCw, Eye, Power, PowerOff, Edit2, Check, X, Layers, Trash2, Loader2, AlertCircle, Zap, Snowflake, ChevronRight } from 'lucide-react';
import { SkillGroup } from '../types';
import { fetchSkillGroups, createSkillGroup, updateSkillGroup, deleteSkillGroup, setSkillGroups } from '../lib/api';
import { useToast } from '@/components/ui/use-toast';
import { useUrlParam } from '../hooks/useUrlParam';
import { setSkillEnabled } from '../lib/skill-activation';
import { skillContentLicense, skillUsageAuthorization } from '../lib/skill-license';
import { uninstallLocalSkill } from '../lib/skill-uninstall';
import { filterSkillsBySource, skillMatchesSource, skillSourceFilterForOpen, skillSourceFilters, type SkillSourceFilter } from '../lib/skill-source-filter';

interface Skill {
  id: string;
  name: string;
  description: string;
  content: string;
  category: string;
  agent_types: string[];
  group_ids?: string[];
  priority: number;
  tags: string[];
  enabled: boolean;
  workflow_only: boolean;
  version: string;
  author: string;
  language: string;
  scope: 'all' | 'workflow';
  scope_override?: 'all' | 'workflow' | null;
  license: string;
  compatibility: string;
  requires_core: string;
  allowed_tools: string[];
  required_tools: string[];
  required_plugins: string[];
  required_apps: string[];
  validation_warnings: string[];
  resource_read_only?: boolean;
  local_modified?: boolean;
  provenance?: {
    source?: {
      kind?: 'local' | 'core' | 'plugin' | 'marketplace';
      registry?: string;
      resource_id?: string;
      version_id?: string;
      publisher_id?: string;
      plugin_id?: string;
    };
    package?: {
      version?: string;
      sha256?: string;
      license?: string;
    };
    installed_at?: string | null;
  } | null;
  auto_inject: boolean;
  config?: {
    group_ids?: string[];
  };
}

interface Stats {
  total: number;
  enabled: number;
  disabled: number;
}

const categoryIcons: Record<string, typeof BookOpen> = {
  general: BookOpen, coding: Code, research: Search, communication: MessageSquare,
  memory: Brain, workflow: Workflow, domain: GraduationCap,
};

const sourceLabels: Record<string, string> = {
  local: '本地创建',
  core: 'Core 内置',
  plugin: '插件提供',
  marketplace: '资源广场',
};

function MetadataFact({ label, value, title, href }: { label: string; value: string; title?: string; href?: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{label}</div>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 block truncate text-sm font-medium text-primary underline-offset-4 hover:underline"
          title={title || value}
          aria-label={`查看 ${value} 许可条款`}
        >
          {value}
        </a>
      ) : (
        <div className="mt-1 truncate text-sm font-medium" title={title || value}>{value}</div>
      )}
    </div>
  );
}

export default function SkillsPage() {
  const { toast } = useToast();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SkillSourceFilter>('all');
  const [requestedSkill, setRequestedSkill] = useUrlParam('skill');
  const openRetryRef = useRef<string | null>(null);
  const detailRequestRef = useRef(0);
  const detailPanelRef = useRef<HTMLDivElement>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 组管理状态
  const [groups, setGroups] = useState<SkillGroup[]>([]);
  const [showGroupDialog, setShowGroupDialog] = useState(false);
  const [editingGroup, setEditingGroup] = useState<SkillGroup | null>(null);
  const [groupForm, setGroupForm] = useState({ id: '', name: '', description: '' });

  // skill 组分配编辑状态
  const [isEditingGroups, setIsEditingGroups] = useState(false);
  const [editingGroupIds, setEditingGroupIds] = useState<string[]>([]);

  // 自定义确认对话框状态
  const [confirmDialog, setConfirmDialog] = useState<{ open: boolean; title: string; message: string; onConfirm: () => void }>({ open: false, title: '', message: '', onConfirm: () => {} });
  const groupIdInputRef = useRef<HTMLInputElement>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [isReloading, setIsReloading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uninstallOpen, setUninstallOpen] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);

  const filteredSkills = useMemo(
    () => filterSkillsBySource(skills, sourceFilter),
    [skills, sourceFilter],
  );

  const changeSourceFilter = (filter: SkillSourceFilter) => {
    detailRequestRef.current += 1;
    setDetailLoading(false);
    setSourceFilter(filter);
    if (selectedSkill && !skillMatchesSource(selectedSkill, filter)) {
      setSelectedSkill(null);
      setIsEditingGroups(false);
    }
  };

  const loadGroups = useCallback(async () => {
    try {
      const res = await fetchSkillGroups();
      setGroups(res.groups);
    } catch (error) {
      console.error('Failed to load skill groups:', error);
    }
  }, []);

  const loadSkills = useCallback(async () => {
    const res = await fetch('/api/skills/summary');
    if (!res.ok) throw new Error('无法加载 Skill 列表');
    const data = await res.json();
    if (!Array.isArray(data.skills)) throw new Error('Skill 列表无效');
    setSkills(data.skills);
  }, []);

  const loadStats = useCallback(async () => {
    try {
      const res = await fetch('/api/skills/stats');
      setStats(await res.json());
    } catch (error) {
      console.error('Failed to load stats:', error);
    }
  }, []);

  const loadInitialData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      await Promise.all([loadSkills(), loadStats(), loadGroups()]);
    } catch (err) {
      setError('加载数据失败，请稍后重试');
      console.error('Failed to load initial data:', err);
    } finally {
      setIsLoading(false);
    }
  }, [loadGroups, loadSkills, loadStats]);

  useEffect(() => {
    loadInitialData();
    return () => { detailRequestRef.current += 1; };
  }, [loadInitialData]);

  const loadDetail = useCallback(async (id: string) => {
    const request = ++detailRequestRef.current;
    setDetailLoading(true);
    setSelectedSkill(null);
    try {
      const res = await fetch(`/api/skills/${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error('无法加载 Skill 详情');
      const detail = await res.json();
      if (request !== detailRequestRef.current) return;
      if (!detail || detail.id !== id) throw new Error('Skill 详情无效');
      if (detail.config?.group_ids) detail.group_ids = detail.config.group_ids;
      setSelectedSkill(detail);
    } catch {
      if (request === detailRequestRef.current) {
        toast({ title: '无法加载 Skill 详情', description: '请重新选择该 Skill 重试。', variant: 'destructive' });
      }
    } finally {
      if (request === detailRequestRef.current) setDetailLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    if (!requestedSkill) {
      openRetryRef.current = null;
      return;
    }
    if (isLoading || error || !requestedSkill) return;
    const skillId = requestedSkill;
    const summary = skills.find((skill) => skill.id === skillId);
    if (!summary) {
      if (openRetryRef.current !== skillId) {
        openRetryRef.current = skillId;
        void loadSkills().catch(() => {
          setRequestedSkill(null, { replace: true });
          toast({ title: '该 Skill 已不可用', description: '请刷新 Skill 列表后重试。', variant: 'destructive' });
        });
        return;
      }
      setRequestedSkill(null, { replace: true });
      toast({ title: '该 Skill 已不可用', description: '请刷新 Skill 列表后重试。', variant: 'destructive' });
      return;
    }
    openRetryRef.current = null;
    setRequestedSkill(null, { replace: true });
    setSourceFilter(skillSourceFilterForOpen(summary));
    setIsEditingGroups(false);
    void loadDetail(skillId);
  }, [error, isLoading, loadDetail, loadSkills, requestedSkill, setRequestedSkill, skills, toast]);

  useEffect(() => {
    if (selectedSkill?.id && window.matchMedia('(max-width: 1023px)').matches) {
      detailPanelRef.current?.scrollIntoView({ block: 'start' });
    }
  }, [selectedSkill?.id]);

  useEffect(() => {
    setUninstallOpen(false);
  }, [selectedSkill?.id]);

  const uninstallMarketplaceSkill = async () => {
    if (!selectedSkill || selectedSkill.provenance?.source?.kind !== 'marketplace' || uninstalling) return;
    const skillId = selectedSkill.id;
    const skillName = selectedSkill.name;
    const detailGeneration = detailRequestRef.current;
    setUninstalling(true);
    let removed = false;
    try {
      await uninstallLocalSkill(skillId);
      removed = true;
      if (detailRequestRef.current === detailGeneration) {
        setSelectedSkill(null);
        setUninstallOpen(false);
      }
      await loadSkills();
      loadStats();
      toast({ title: '已卸载', description: `已从本机移除「${skillName}」。` });
    } catch (error) {
      toast({
        title: removed ? '已卸载，但列表刷新失败' : '卸载失败',
        description: removed
          ? '请刷新列表查看当前状态。'
          : error instanceof Error ? error.message : '请检查连接并重试。',
        variant: 'destructive',
      });
    } finally {
      setUninstalling(false);
    }
  };

  const selectedContentLicense = selectedSkill ? skillContentLicense(selectedSkill) : null;
  const selectedUsageAuthorization = selectedSkill ? skillUsageAuthorization(selectedSkill) : null;

  const toggleSkill = async (id: string, enabled: boolean) => {
    const detailGeneration = detailRequestRef.current;
    let updated = false;
    try {
      await setSkillEnabled(id, enabled);
      updated = true;
      await loadSkills();
      loadStats();
      if (selectedSkill?.id === id && detailRequestRef.current === detailGeneration) await loadDetail(id);
    } catch {
      toast({
        title: updated ? '状态已更新，但列表刷新失败' : 'Skill 状态未更新',
        description: updated ? '请刷新列表查看当前状态。' : '请检查连接并重试。',
        variant: 'destructive',
      });
    }
  };

  const toggleAutoInject = async (id: string, enabled: boolean) => {
    try {
      await fetch(`/api/skills/${id}/auto-inject?enabled=${enabled}`, { method: 'POST' });
      await loadSkills();
      if (selectedSkill?.id === id) await loadDetail(id);
    } catch (error) {
      console.error('Error toggling auto-inject:', error);
    }
  };

  const toggleWorkflowOnly = async (id: string, enabled: boolean) => {
    try {
      await fetch(`/api/skills/${id}/workflow-only?enabled=${enabled}`, { method: 'POST' });
      await loadSkills();
      if (selectedSkill?.id === id) await loadDetail(id);
    } catch (error) {
      console.error('Error toggling workflow-only:', error);
    }
  };

  // === 组管理对话框 ===
  const openCreateGroup = () => {
    setEditingGroup(null);
    setGroupForm({ id: '', name: '', description: '' });
    setShowGroupDialog(true);
  };

  const openEditGroup = (group: SkillGroup) => {
    setEditingGroup(group);
    setGroupForm({ id: group.id, name: group.name, description: group.description });
    setShowGroupDialog(true);
  };

  const saveGroup = async () => {
    try {
      if (editingGroup) {
        await updateSkillGroup(editingGroup.id, { name: groupForm.name, description: groupForm.description });
        toast({
          title: "组已更新",
          description: `已更新组 "${groupForm.name}"`,
        });
      } else {
        await createSkillGroup({ id: groupForm.id, name: groupForm.name, description: groupForm.description });
        toast({
          title: "组已创建",
          description: `已创建新组 "${groupForm.name}"`,
        });
      }
      setShowGroupDialog(false);
      await loadGroups();
    } catch (error) {
      console.error('Failed to save group:', error);
      toast({
        title: "保存失败",
        description: "无法保存组，请重试",
        variant: "destructive",
      });
    }
  };

  const handleDeleteGroup = async (groupId: string) => {
    const groupName = groups.find(g => g.id === groupId)?.name || groupId;
    setConfirmDialog({
      open: true,
      title: '删除技能组',
      message: `确定删除组 "${groupName}" 吗？组内的 skill 不会被删除，但会失去所属关系。`,
      onConfirm: async () => {
        try {
          await deleteSkillGroup(groupId);
          await loadGroups();
          toast({ title: "组已删除", description: `已删除组 "${groupName}"` });
        } catch (error) {
          console.error('Failed to delete group:', error);
          toast({ title: "删除失败", description: "无法删除组，请重试", variant: "destructive" });
        }
        setConfirmDialog(prev => ({ ...prev, open: false }));
      },
    });
  };

  // === Skill 组分配 ===
  const startEditingGroups = () => {
    setEditingGroupIds(selectedSkill?.group_ids || selectedSkill?.config?.group_ids || []);
    setIsEditingGroups(true);
  };

  const cancelEditingGroups = () => {
    setIsEditingGroups(false);
    setEditingGroupIds([]);
  };

  const saveSkillGroups = async () => {
    if (!selectedSkill) return;
    try {
      await setSkillGroups(selectedSkill.id, editingGroupIds);
      setIsEditingGroups(false);
      await loadSkills();
      await loadDetail(selectedSkill.id);
      toast({
        title: "组分配已保存",
        description: `已更新 ${selectedSkill.name} 的组分配`,
      });
    } catch (error) {
      console.error('Error saving skill groups:', error);
      toast({
        title: "保存失败",
        description: "无法保存组分配，请重试",
        variant: "destructive",
      });
    }
  };

  const toggleGroup = (groupId: string) => {
    setEditingGroupIds(prev =>
      prev.includes(groupId) ? prev.filter(g => g !== groupId) : [...prev, groupId]
    );
  };

  const getSkillGroupNames = () => {
    const gids = selectedSkill?.group_ids || selectedSkill?.config?.group_ids || [];
    return groups.filter(g => gids.includes(g.id));
  };

  // Escape 关闭对话框 + auto-focus
  useEffect(() => {
    if (!showGroupDialog) return;
    const timer = setTimeout(() => groupIdInputRef.current?.focus(), 50);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowGroupDialog(false);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => { clearTimeout(timer); document.removeEventListener('keydown', handleKeyDown); };
  }, [showGroupDialog]);

  if (isLoading) {
    return (
      <div className="container mx-auto p-6 flex items-center justify-center h-[600px]" role="status">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin motion-reduce:animate-none mx-auto mb-4 text-primary" aria-hidden="true" />
          <p className="text-muted-foreground sr-only">加载技能数据中...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto p-6 flex items-center justify-center h-[600px]">
        <div className="text-center" role="alert">
          <AlertCircle className="w-8 h-8 mx-auto mb-4 text-destructive" aria-hidden="true" />
          <p className="text-destructive mb-4">{error}</p>
          <Button onClick={loadInitialData} variant="outline" aria-label="重试加载">
            <RefreshCw className="w-4 h-4 mr-2" aria-hidden="true" />重试
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto min-w-0 p-6 space-y-6" role="main" aria-label="技能管理页面">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Skills 管理</h1>
          <p className="text-muted-foreground">管理可复用的知识和行为模块</p>
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" onClick={() => { setShowGroupDialog(true); openCreateGroup(); }} aria-label="管理技能组" className="focus-visible:ring-2 focus-visible:ring-primary/50">
            <Layers className="w-4 h-4 mr-2" aria-hidden="true" />管理组
          </Button>
          <Button type="button" onClick={async () => { setIsReloading(true); try { await fetch('/api/skills/reload', { method: 'POST' }); await Promise.all([loadSkills(), loadStats()]); toast({ title: "重新加载完成" }); } catch { toast({ title: "重新加载失败", variant: "destructive" }); } finally { setIsReloading(false); } }} disabled={isReloading} aria-label="重新加载技能" className="focus-visible:ring-2 focus-visible:ring-primary/50">
            <RefreshCw className={`w-4 h-4 mr-2 ${isReloading ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />重新加载
          </Button>
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-3 gap-4" role="region" aria-label="技能统计">
          <Card><CardHeader className="pb-3"><CardTitle className="text-sm">总计</CardTitle></CardHeader>
            <CardContent><div className="text-2xl font-bold tabular-nums">{stats.total}</div></CardContent></Card>
          <Card><CardHeader className="pb-3"><CardTitle className="text-sm">已启用</CardTitle></CardHeader>
            <CardContent><div className="text-2xl font-bold text-success tabular-nums">{stats.enabled}</div></CardContent></Card>
          <Card><CardHeader className="pb-3"><CardTitle className="text-sm">已禁用</CardTitle></CardHeader>
            <CardContent><div className="text-2xl font-bold text-muted-foreground tabular-nums">{stats.disabled}</div></CardContent></Card>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader className="space-y-3">
            <CardTitle>Skills 列表</CardTitle>
            <div className="flex rounded-md border bg-muted/40 p-1" role="group" aria-label="按来源筛选 Skill">
              {skillSourceFilters.map((filter) => (
                <Button
                  key={filter.value}
                  type="button"
                  variant={sourceFilter === filter.value ? 'secondary' : 'ghost'}
                  size="sm"
                  aria-pressed={sourceFilter === filter.value}
                  className="h-8 flex-1 px-2 text-xs"
                  onClick={() => changeSourceFilter(filter.value)}
                >
                  {filter.label}
                </Button>
              ))}
            </div>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[600px]">
              <div className="space-y-2">
                {filteredSkills.map((skill) => {
                  const Icon = categoryIcons[skill.category] || BookOpen;
                  const skillGroupIds = skill.group_ids || skill.config?.group_ids || [];
                  return (
                    <div key={skill.id} className={`p-3 rounded-lg border cursor-pointer ${selectedSkill?.id === skill.id ? 'border-primary bg-primary/5' : 'hover:bg-accent'}`}
                      onClick={() => loadDetail(skill.id)}
                      role="button"
                      tabIndex={0}
                      aria-label={`查看技能 ${skill.name}`}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); loadDetail(skill.id); } }}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex items-start gap-2 flex-1">
                          <Icon className="w-5 h-5 mt-0.5" />
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-sm flex items-center gap-2">
                              {skill.name}
                              {skill.auto_inject && <Zap className="w-3 h-3 text-warning" aria-hidden="true" />}
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{skill.description}</div>
                            <div className="flex gap-1 mt-2 flex-wrap">
                              <Badge variant="outline" className="text-xs">P{skill.priority}</Badge>
                              {skillGroupIds.length > 0 && (
                                <Badge variant="secondary" className="text-xs">{skillGroupIds.length} 个组</Badge>
                              )}
                            </div>
                          </div>
                        </div>
                        {skill.enabled ? <><Power className="w-4 h-4 text-success" aria-hidden="true" /><span className="sr-only">已启用</span></> : <><PowerOff className="w-4 h-4 text-muted-foreground" aria-hidden="true" /><span className="sr-only">已禁用</span></>}
                      </div>
                    </div>
                  );
                })}
                {filteredSkills.length === 0 && (
                  <div className="py-10 text-center text-sm text-muted-foreground" role="status">
                    该来源暂无 Skill
                  </div>
                )}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        <div ref={detailPanelRef} className="min-w-0 scroll-mt-4 lg:col-span-2">
          {detailLoading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
              正在加载 Skill
            </div>
          ) : selectedSkill ? (
            <Card>
              <CardHeader>
                <div className="flex flex-col items-start gap-3">
                  <div className="min-w-0 break-words"><CardTitle>{selectedSkill.name}</CardTitle><CardDescription>{selectedSkill.description}</CardDescription></div>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" variant="outline" size="sm" onClick={() => toggleAutoInject(selectedSkill.id, !selectedSkill.auto_inject)} aria-label={selectedSkill.auto_inject ? '关闭自动注入' : '开启自动注入'} className="focus-visible:ring-2 focus-visible:ring-primary/50">
                      {selectedSkill.auto_inject ? <><Zap className="w-4 h-4 mr-2 text-warning" aria-hidden="true" />自动注入</> : <><Snowflake className="w-4 h-4 mr-2" aria-hidden="true" />手动获取</>}
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => toggleWorkflowOnly(selectedSkill.id, !selectedSkill.workflow_only)} aria-label={selectedSkill.workflow_only ? '设为通用' : '设为工作流专属'} className="focus-visible:ring-2 focus-visible:ring-primary/50">
                      {selectedSkill.workflow_only ? <><Workflow className="w-4 h-4 mr-2 text-primary" aria-hidden="true" />工作流专属</> : <><Workflow className="w-4 h-4 mr-2" aria-hidden="true" />通用</>}
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => toggleSkill(selectedSkill.id, !selectedSkill.enabled)} aria-label={selectedSkill.enabled ? '禁用技能' : '启用技能'} className="focus-visible:ring-2 focus-visible:ring-primary/50">
                      {selectedSkill.enabled ? <><PowerOff className="w-4 h-4 mr-2" aria-hidden="true" />禁用</> : <><Power className="w-4 h-4 mr-2" aria-hidden="true" />启用</>}
                    </Button>
                    {selectedSkill.provenance?.source?.kind === 'marketplace' && (
                      <>
                        <MarketplaceSkillUpdateButton key={selectedSkill.id} skillId={selectedSkill.id} version={selectedSkill.version} />
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={uninstalling}
                          aria-label={`卸载本机 Skill ${selectedSkill.name}`}
                          className="focus-visible:ring-2 focus-visible:ring-primary/50"
                          onClick={() => setUninstallOpen(true)}
                        >
                          <Trash2 className="w-4 h-4 mr-2" aria-hidden="true" />卸载
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <details key={selectedSkill.id} className="group rounded-md border">
                  <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 text-sm font-medium outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-primary/50 [&::-webkit-details-marker]:hidden">
                    <span className="flex items-center gap-2">
                      <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-90" aria-hidden="true" />
                      元数据
                    </span>
                  </summary>
                  <div className="space-y-4 border-t p-4">
                <section aria-labelledby="skill-content-metadata">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <h3 id="skill-content-metadata" className="text-sm font-medium">内容元数据</h3>
                  </div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-4 rounded-md border bg-muted/40 p-4 sm:grid-cols-3">
                    <MetadataFact label="资源标识" value={selectedSkill.id} />
                    <MetadataFact label="版本" value={selectedSkill.version || '未填写'} />
                    <MetadataFact label="作者" value={selectedSkill.author || '未填写'} />
                    <MetadataFact label="主要语言" value={selectedSkill.language || '未填写'} />
                    {selectedContentLicense && (
                      <MetadataFact label="许可证" value={selectedContentLicense} />
                    )}
                    <MetadataFact label="清单适用范围" value={selectedSkill.scope === 'workflow' ? '仅工作流' : '全部场景'} />
                    <MetadataFact label="兼容 Core" value={selectedSkill.requires_core || selectedSkill.compatibility || '未声明'} />
                  </div>
                  {selectedSkill.tags.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2" aria-label="Skill 标签">
                      {selectedSkill.tags.map(t => <Badge key={t} variant="outline">{t}</Badge>)}
                    </div>
                  )}
                </section>

                <section aria-labelledby="skill-local-settings">
                  <h3 id="skill-local-settings" className="mb-2 text-sm font-medium">本地运行设置</h3>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-4 rounded-md border bg-muted/40 p-4 sm:grid-cols-4">
                    <MetadataFact label="优先级" value={String(selectedSkill.priority)} />
                    <MetadataFact label="自动注入" value={selectedSkill.auto_inject ? '是' : '否'} />
                    <MetadataFact
                      label="生效范围"
                      value={selectedSkill.workflow_only ? '仅工作流' : '全部场景'}
                      title={selectedSkill.scope_override ? '使用本机覆盖值' : '沿用 SKILL.md 声明'}
                    />
                    <div>
                      <div className="text-xs text-muted-foreground">状态</div>
                      <div className="mt-1 flex items-center gap-1.5 text-sm font-medium">
                        <span className={`h-2 w-2 rounded-full ${selectedSkill.enabled ? 'bg-success' : 'bg-muted-foreground'}`} aria-hidden="true" />
                        {selectedSkill.enabled ? '已启用' : '已禁用'}
                      </div>
                    </div>
                  </div>
                </section>

                <section aria-labelledby="skill-source">
                  <h3 id="skill-source" className="mb-2 text-sm font-medium">来源与完整性</h3>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-4 rounded-md border bg-muted/40 p-4 sm:grid-cols-3">
                    <MetadataFact label="来源" value={sourceLabels[selectedSkill.provenance?.source?.kind || 'local'] || '未知来源'} />
                    <MetadataFact label="安装版本" value={selectedSkill.provenance?.package?.version || selectedSkill.version || '未记录'} />
                    <MetadataFact label="本地修改" value={selectedSkill.local_modified ? '已偏离安装版本' : '未检测到'} />
                    {selectedUsageAuthorization && (
                      <MetadataFact
                        label="使用授权"
                        value={selectedUsageAuthorization.label}
                        href={selectedUsageAuthorization.href || undefined}
                        title={selectedUsageAuthorization.id}
                      />
                    )}
                    {selectedSkill.provenance?.source?.publisher_id && (
                      <MetadataFact label="发布者标识" value={selectedSkill.provenance.source.publisher_id} />
                    )}
                    {selectedSkill.provenance?.source?.resource_id && (
                      <MetadataFact label="社区资源标识" value={selectedSkill.provenance.source.resource_id} />
                    )}
                    {selectedSkill.provenance?.package?.sha256 && (
                      <MetadataFact label="内容摘要" value={selectedSkill.provenance.package.sha256.slice(0, 12)} title={selectedSkill.provenance.package.sha256} />
                    )}
                  </div>
                </section>

                {(selectedSkill.required_tools.length > 0 || selectedSkill.required_plugins.length > 0 || selectedSkill.required_apps.length > 0) && (
                  <section aria-labelledby="skill-dependencies">
                    <h3 id="skill-dependencies" className="mb-2 text-sm font-medium">运行依赖</h3>
                    <div className="space-y-2 rounded-md border bg-muted/40 p-4 text-sm">
                      {selectedSkill.required_tools.length > 0 && <div><span className="text-muted-foreground">工具：</span>{selectedSkill.required_tools.join('、')}</div>}
                      {selectedSkill.required_plugins.length > 0 && <div><span className="text-muted-foreground">插件：</span>{selectedSkill.required_plugins.join('、')}</div>}
                      {selectedSkill.required_apps.length > 0 && <div><span className="text-muted-foreground">App：</span>{selectedSkill.required_apps.join('、')}</div>}
                    </div>
                  </section>
                )}
                  </div>
                </details>

                {selectedSkill.validation_warnings.length > 0 && (
                  <div className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm" role="status">
                    {selectedSkill.validation_warnings.join('；')}
                  </div>
                )}

                {/* 组配置 (替代 agent_types) */}
                <div>
                  <div className="text-sm font-medium mb-2 flex items-center justify-between">
                    <span>所属组</span>
                    {!isEditingGroups ? (
                      <Button type="button" variant="ghost" size="sm" onClick={startEditingGroups} className="focus-visible:ring-2 focus-visible:ring-primary/50">
                        <Edit2 className="w-3 h-3 mr-1" />编辑
                      </Button>
                    ) : (
                      <div className="flex gap-2">
                        <Button type="button" variant="ghost" size="sm" onClick={cancelEditingGroups} className="focus-visible:ring-2 focus-visible:ring-primary/50">
                          <X className="w-3 h-3 mr-1" />取消
                        </Button>
                        <Button type="button" variant="default" size="sm" onClick={saveSkillGroups} className="focus-visible:ring-2 focus-visible:ring-primary/50">
                          <Check className="w-3 h-3 mr-1" />保存
                        </Button>
                      </div>
                    )}
                  </div>
                  {!isEditingGroups ? (
                    <div className="flex flex-wrap gap-2">
                      {getSkillGroupNames().length > 0 ? (
                        getSkillGroupNames().map(g => (
                          <Badge key={g.id} variant="secondary" className="flex items-center gap-1">
                            <Layers className="w-3 h-3" />{g.name}
                          </Badge>
                        ))
                      ) : (
                        <Badge variant="outline">未分配到任何组</Badge>
                      )}
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {groups.length > 0 ? (
                        <div className="grid grid-cols-2 gap-2">
                          {groups.map(group => (
                            <label
                              key={group.id}
                              className="flex items-start gap-2 p-2 border rounded cursor-pointer hover:bg-accent min-h-[44px]"
                            >
                              <input
                                type="checkbox"
                                checked={editingGroupIds.includes(group.id)}
                                onChange={() => toggleGroup(group.id)}
                                aria-label={`将技能分配到组 ${group.name}`}
                                className="mt-1"
                              />
                              <div className="flex-1 min-w-0">
                                <div className="font-medium text-sm">{group.name}</div>
                                <div className="text-xs text-muted-foreground line-clamp-1">{group.description || '无描述'}</div>
                              </div>
                            </label>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">暂无组，请先点击"管理组"按钮创建</p>
                      )}
                      <p className="text-xs text-muted-foreground">
                        Skill 与组是多对多关系。Agent 通过可见的组来间接访问此 Skill。
                      </p>
                    </div>
                  )}
                </div>

                <div>
                  <div className="text-sm font-medium mb-2">内容</div>
                  <ScrollArea className="h-[400px] rounded-md border p-4">
                    <pre className="text-sm whitespace-pre-wrap">{selectedSkill.content}</pre>
                  </ScrollArea>
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card><CardContent className="flex items-center justify-center h-[600px]">
              <div className="text-center text-muted-foreground" role="status"><Eye className="w-12 h-12 mx-auto mb-4 opacity-50" aria-hidden="true" /><p>选择一个 Skill 查看详情</p></div>
            </CardContent></Card>
          )}
        </div>
      </div>

      {/* 组管理对话框 */}
      {showGroupDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={() => setShowGroupDialog(false)}>
          <div className="bg-secondary border border-border/50 rounded-xl p-6 w-[500px] max-h-[80vh] overflow-y-auto" role="dialog" aria-modal="true" aria-labelledby="group-dialog-title" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 id="group-dialog-title" className="text-lg font-semibold text-foreground">管理技能组</h2>
              <button type="button" onClick={() => setShowGroupDialog(false)} className="p-1 text-muted-foreground hover:text-foreground cursor-pointer" aria-label="关闭">
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            {/* 已有组列表 */}
            <div className="space-y-2 mb-4">
              {groups.map(group => (
                <div key={group.id} className="flex items-center justify-between p-3 bg-secondary/60 rounded-lg border border-border/30">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground">{group.name}</div>
                    <div className="text-xs text-muted-foreground truncate">{group.description || '无描述'}</div>
                  </div>
                  <div className="flex gap-1">
                    <button type="button" onClick={() => openEditGroup(group)} className="p-1.5 text-muted-foreground hover:text-primary transition-colors cursor-pointer min-w-[44px] min-h-[44px] flex items-center justify-center" aria-label={`编辑组 ${group.name}`}>
                      <Edit2 size={14} aria-hidden="true" />
                    </button>
                    <button type="button" onClick={() => handleDeleteGroup(group.id)} className="p-1.5 text-muted-foreground hover:text-destructive transition-colors cursor-pointer min-w-[44px] min-h-[44px] flex items-center justify-center" aria-label={`删除组 ${group.name}`}>
                      <Trash2 size={14} aria-hidden="true" />
                    </button>
                  </div>
                </div>
              ))}
              {groups.length === 0 && (
                <p className="text-sm text-muted-foreground text-center py-4">暂无组，请创建</p>
              )}
            </div>

            {/* 创建/编辑表单 */}
            <div className="border-t border-border/30 pt-4">
              <h3 className="text-sm font-medium text-foreground mb-3">{editingGroup ? '编辑组' : '新建组'}</h3>
              <div className="space-y-3">
                <div>
                  <label htmlFor="group-id" className="text-xs text-muted-foreground block mb-1">组 ID</label>
                  <input
                    ref={groupIdInputRef}
                    id="group-id"
                    value={groupForm.id}
                    onChange={e => setGroupForm(p => ({ ...p, id: e.target.value }))}
                    disabled={!!editingGroup}
                    placeholder="unique-group-id"
                    className="w-full bg-secondary/60 border border-border/50 rounded-md px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-primary/50 min-h-[44px]"
                  />
                </div>
                <div>
                  <label htmlFor="group-name" className="text-xs text-muted-foreground block mb-1">组名称</label>
                  <input
                    id="group-name"
                    value={groupForm.name}
                    onChange={e => setGroupForm(p => ({ ...p, name: e.target.value }))}
                    placeholder="我的技能组"
                    className="w-full bg-secondary/60 border border-border/50 rounded-md px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-primary/50 min-h-[44px]"
                  />
                </div>
                <div>
                  <label htmlFor="group-desc" className="text-xs text-muted-foreground block mb-1">描述</label>
                  <input
                    id="group-desc"
                    value={groupForm.description}
                    onChange={e => setGroupForm(p => ({ ...p, description: e.target.value }))}
                    placeholder="可选描述"
                    className="w-full bg-secondary/60 border border-border/50 rounded-md px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-primary/50 min-h-[44px]"
                  />
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <Button type="button" variant="outline" size="sm" onClick={() => setShowGroupDialog(false)} className="focus-visible:ring-2 focus-visible:ring-primary/50">取消</Button>
                  <Button type="button" size="sm" onClick={saveGroup} disabled={!groupForm.id || !groupForm.name} className="focus-visible:ring-2 focus-visible:ring-primary/50">
                    {editingGroup ? '保存修改' : '创建'}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {selectedSkill?.provenance?.source?.kind === 'marketplace' && (
        <Dialog
          open={uninstallOpen}
          title="卸载本机 Skill"
          description={`将删除本机安装的「${selectedSkill.name}」及其来源记录和本地配置。资源广场上的在线资源和其他 Skill 不受影响。`}
          onClose={() => { if (!uninstalling) setUninstallOpen(false); }}
        >
          <div className="mt-6 flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" disabled={uninstalling} onClick={() => setUninstallOpen(false)}>
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              disabled={uninstalling}
              aria-busy={uninstalling}
              onClick={() => { void uninstallMarketplaceSkill(); }}
            >
              {uninstalling ? '正在卸载' : '确认卸载'}
            </Button>
          </div>
        </Dialog>
      )}

      {/* 自定义确认对话框 */}
      {confirmDialog.open && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60" onClick={() => setConfirmDialog(prev => ({ ...prev, open: false }))}>
          <div className="bg-secondary border border-border/50 rounded-xl p-6 w-[400px]" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" onClick={e => e.stopPropagation()}>
            <h2 id="confirm-dialog-title" className="text-lg font-semibold text-foreground mb-2">{confirmDialog.title}</h2>
            <p className="text-sm text-muted-foreground mb-6">{confirmDialog.message}</p>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => setConfirmDialog(prev => ({ ...prev, open: false }))} className="focus-visible:ring-2 focus-visible:ring-primary/50">取消</Button>
              <Button type="button" variant="destructive" size="sm" onClick={confirmDialog.onConfirm} className="focus-visible:ring-2 focus-visible:ring-primary/50">确认删除</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
