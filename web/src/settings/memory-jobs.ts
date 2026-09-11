import { request } from "../lib/http-client";

export interface MemoryJob {
  session_id: string;
  job_id: string;
  status: string;
  pending_turns: number;
  pending_tokens: number;
  attempt: number;
  error_code: string;
  error: string;
  has_frozen_facts: boolean;
  updated_at: string;
  last_completed_at: string;
}

export interface MemoryJobs {
  counts: Record<string, number>;
  total: number;
  jobs: MemoryJob[];
  truncated: boolean;
}

export const MEMORY_JOB_LABELS: Record<string, string> = {
  idle: "暂无待处理内容", pending: "等待触发", claimed: "准备整理", extracting: "正在提炼",
  extracted: "等待写入", retaining: "正在写入", retry_wait: "等待重试",
  failed: "整理失败", completed: "已处理",
};

export function isMemoryJobActive(job: Pick<MemoryJob, "status">): boolean {
  return ["claimed", "extracting", "extracted", "retaining", "retry_wait"].includes(job.status);
}

export function readMemoryJobs(payload: unknown): MemoryJobs {
  if (!payload || typeof payload !== "object") throw new Error("整理状态响应无效");
  const value = payload as MemoryJobs;
  if (!Array.isArray(value.jobs) || !value.counts || typeof value.counts !== "object"
      || typeof value.total !== "number" || typeof value.truncated !== "boolean"
      || !Object.values(value.counts).every((n) => Number.isInteger(n) && n >= 0)) {
    throw new Error("整理状态响应无效");
  }
  for (const job of value.jobs) {
    if (!job || typeof job !== "object"
        || !["session_id", "job_id", "status", "error_code", "error", "updated_at", "last_completed_at"].every((key) => typeof job[key as keyof MemoryJob] === "string")
        || ![job.pending_turns, job.pending_tokens, job.attempt].every((n) => Number.isInteger(n) && n >= 0)
        || typeof job.has_frozen_facts !== "boolean") throw new Error("整理状态响应无效");
  }
  return value;
}

function auth(adminToken: string) {
  return adminToken.trim() ? { Authorization: `Bearer ${adminToken.trim()}` } : undefined;
}

export async function fetchMemoryJobs(adminToken = ""): Promise<MemoryJobs> {
  return readMemoryJobs(await request<unknown>("/memory/jobs", { headers: auth(adminToken) }));
}

export async function retryMemoryJob(job: MemoryJob, adminToken = ""): Promise<void> {
  await request(`/memory/jobs/${encodeURIComponent(job.session_id)}/retry`, {
    method: "POST", headers: auth(adminToken), body: JSON.stringify({ job_id: job.job_id }),
  });
}
