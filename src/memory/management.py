"""Administrative job summaries and fenced recovery without exposing source text."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping
from typing import Any

from src.memory.contracts import MemoryBinding, MemoryUnavailableError
from src.memory.provider_status import probe_provider_health
from src.memory.store import STATUS_FAILED, STATUS_RETRY_WAIT, active_job, utc_now_iso
from src.memory.turns import snapshot_token_count


class MemoryJobConflict(ValueError):
    pass


def job_error_summary(error: str) -> tuple[str, str]:
    text = str(error or "").lower()
    if "json" in text or "extract output" in text or "extract fact" in text:
        return "invalid_output", "提炼结果格式无效"
    if "timeout" in text or "timed out" in text:
        return "timeout", "提炼或写入超时"
    if "unauthorized" in text or "scope" in text:
        return "unauthorized", "会话记忆授权未通过"
    if "budget" in text:
        return "budget", "完整轮次超过单批处理容量"
    if "retain" in text:
        return "retain_unconfirmed", "记忆写入尚未确认"
    return "failed", "整理失败，请重试；持续失败时检查服务日志"


def summarize_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    job = active_job(ledger) or {}
    pending = [t for t in ledger.get("turns") or []
               if t.get("skip_reason") not in {"action_observation", "non_human"}]
    idle_status = "completed" if ledger.get("watermarks") or ledger.get("last_completed") else "idle"
    status = str(job.get("status") or ("pending" if pending else idle_status))
    code, error = job_error_summary(job.get("error") or "") if job.get("error") or status == STATUS_FAILED else ("", "")
    return {
        "session_id": str(ledger.get("session_id") or ""),
        "job_id": str(job.get("id") or ""),
        "status": status,
        "pending_turns": len(pending),
        "pending_tokens": sum(snapshot_token_count(t) for t in pending),
        "attempt": int(job.get("attempt") or 0),
        "error_code": code,
        "error": error,
        "has_frozen_facts": job.get("frozen_facts") is not None,
        "updated_at": str(ledger.get("updated_at") or ""),
        "last_completed_at": str((ledger.get("last_completed") or {}).get("at") or ""),
    }


class MemoryJobManagementMixin:
    def memory_job_status(self) -> dict[str, Any]:
        rows = [summarize_ledger(ledger) for sid in self._store.list_session_ids()
                if (ledger := self._store.load(sid)) is not None]
        counts = Counter(row["status"] for row in rows)
        # Failed jobs must not disappear behind recent successful sessions.
        rows.sort(key=lambda row: (row["status"] == STATUS_FAILED, row["updated_at"]), reverse=True)
        return {
            "counts": dict(counts),
            "total": len(rows),
            "jobs": rows[:100],
            "truncated": len(rows) > 100,
        }

    async def retry_failed_memory_job(self, session_id: str, expected_job_id: str) -> dict[str, Any]:
        ledger = self._store.load(session_id)
        if ledger is None:
            raise KeyError(session_id)
        job = active_job(ledger)
        if not job or job.get("status") != STATUS_FAILED or job.get("id") != expected_job_id:
            raise MemoryJobConflict("任务状态已变化，请刷新后重试")
        provider_id = str(ledger.get("provider_id") or "")
        provider = self.running_providers().get(provider_id)
        if provider is None:
            raise MemoryUnavailableError("记忆未启用或提供者未运行")
        policy = self.effective_runtime_policy(provider)
        if not policy.auto_consolidate_enabled:
            raise MemoryUnavailableError("请先启用自动整理")
        healthy, _, exposes_health = await probe_provider_health(provider)
        if not healthy or not exposes_health:
            raise MemoryUnavailableError("记忆提供者健康检查未通过")
        binding = MemoryBinding(
            provider_id=provider_id,
            scope="user" if job.get("memory_scope") else "local",
            bank_id=str(job.get("bank_id") or ""),
            memory_scope=str(job.get("memory_scope") or ""),
            policy=policy,
        )
        if not await self._authorize_ledger(ledger, binding):
            raise MemoryUnavailableError("会话记忆授权未通过")
        # Re-check gates after async health/owner authorization, before mutating.
        if self.running_providers().get(provider_id) is not provider or not self.effective_runtime_policy(provider).auto_consolidate_enabled:
            raise MemoryUnavailableError("记忆配置已变化，请刷新后重试")

        def requeue(current, _conn):
            existing = active_job(current)
            if not existing or existing.get("id") != expected_job_id or existing.get("status") != STATUS_FAILED:
                raise MemoryJobConflict("任务已被重试或状态已变化")
            if any(current.get(key) != ledger.get(key) for key in ("provider_id", "resource_owner", "external_ref")):
                raise MemoryJobConflict("会话归属已变化")
            if any(existing.get(key) != job.get(key) for key in ("bank_id", "memory_scope", "partition", "turn_ids")):
                raise MemoryJobConflict("任务范围已变化")
            # Preserve frozen facts, deterministic document IDs and source range.
            # A new fence makes a stale browser click or worker unable to retry twice.
            current["job"] = {
                **existing, "id": uuid.uuid4().hex, "status": STATUS_RETRY_WAIT,
                "worker_id": "", "attempt": 1, "error": "", "retry_at": utc_now_iso(),
                "lease_until": utc_now_iso(), "manual_retry_at": utc_now_iso(),
            }
            return current

        updated = self._store.transact(session_id, requeue)
        await self.start()
        return summarize_ledger(updated)
