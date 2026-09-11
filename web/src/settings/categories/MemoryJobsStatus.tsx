import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui/button";
import { fetchMemoryJobs, isMemoryJobActive, MEMORY_JOB_LABELS, retryMemoryJob } from "../memory-jobs";
import type { MemoryJob, MemoryJobs } from "../memory-jobs";
import { isPluginAuthError, parseApiError } from "../parse-api-error";
import { useSettingsWorkspace } from "../SettingsWorkspace";

export function MemoryJobRows({ jobs, busy, enabled, onRetry }: {
  jobs: MemoryJob[]; busy: string | null; enabled: boolean; onRetry: (job: MemoryJob) => void;
}) {
  return <ul className="divide-y divide-border">
    {jobs.filter((job) => job.status === "failed" || isMemoryJobActive(job)).map((job) => (
      <li key={job.session_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
        <div className="min-w-0 text-sm">
          <p className={job.status === "failed" ? "text-destructive" : "text-foreground"}>
            {MEMORY_JOB_LABELS[job.status] || job.status}
            <span className="ml-2 font-mono text-xs text-muted-foreground" title={job.session_id}>会话 {job.session_id.slice(0, 12)}</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {job.pending_turns} 轮待处理 · 约 {job.pending_tokens.toLocaleString()} token · 已尝试 {job.attempt} 次
          </p>
          {job.error ? <p className="mt-1 text-sm text-muted-foreground">{job.error}</p> : null}
        </div>
        {job.status === "failed" ? <Button variant="outline" size="sm"
          disabled={!enabled || busy !== null} onClick={() => onRetry(job)}
          aria-label={`重试会话 ${job.session_id} 的记忆整理`}>
          {busy === job.session_id ? "正在重试…" : "重试"}
        </Button> : null}
      </li>
    ))}
  </ul>;
}

export function MemoryJobsStatus({ enabled }: { enabled: boolean }) {
  const { adminToken, setRevealAdminToken } = useSettingsWorkspace();
  const [snapshot, setSnapshot] = useState<MemoryJobs | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const generation = useRef(0);
  const busyRef = useRef(false);
  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    try {
      const next = await fetchMemoryJobs(adminToken);
      if (current !== generation.current) return;
      setSnapshot(next);
      setError(null);
    } catch (reason) {
      if (current !== generation.current) return;
      setError(parseApiError(reason, "无法加载整理状态"));
      if (isPluginAuthError(reason)) setRevealAdminToken(true);
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, [adminToken, setRevealAdminToken]);
  useEffect(() => { void load(); return () => { generation.current += 1; }; }, [load, enabled]);
  const active = snapshot?.jobs.some(isMemoryJobActive) ?? false;
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => { if (!document.hidden && !busyRef.current) void load(); }, 15000);
    return () => window.clearInterval(timer);
  }, [active, load]);
  const retry = async (job: MemoryJob) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(job.session_id);
    setError(null);
    try {
      await retryMemoryJob(job, adminToken);
      await load();
    } catch (reason) {
      setError(parseApiError(reason, "重试失败"));
      if (isPluginAuthError(reason)) setRevealAdminToken(true);
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  };
  return <section aria-label="后台记忆整理" className="border-t border-border pt-4">
    <div className="flex items-center justify-between gap-3">
      <h3 className="text-sm font-medium">后台整理</h3>
      <Button variant="ghost" size="sm" disabled={loading || busy !== null} onClick={() => void load()}>
        {loading ? "刷新中…" : "刷新"}
      </Button>
    </div>
    {error ? <p role="alert" className="mt-2 text-sm text-destructive">{error}</p> : null}
    {snapshot ? <>
      <p className="mt-2 text-xs text-muted-foreground" role="status">
        {snapshot.total === 0 ? "暂无整理记录" : `${snapshot.total} 个会话 · ${snapshot.counts.pending || 0} 个等待触发 · ${snapshot.counts.failed || 0} 个失败`}
      </p>
      <MemoryJobRows jobs={snapshot.jobs} busy={busy} enabled={enabled} onRetry={(job) => void retry(job)} />
      {snapshot.truncated ? <p className="text-xs text-muted-foreground">仅显示最近 100 个会话，失败任务优先。</p> : null}
      {!enabled && (snapshot.counts.failed || 0) > 0 ? <p className="text-xs text-muted-foreground">启用记忆和自动整理后可重试。</p> : null}
    </> : null}
  </section>;
}
