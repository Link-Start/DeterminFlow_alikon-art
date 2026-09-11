"""Claim, fence, extract, and retain without holding locks across network IO."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import uuid
from collections.abc import Mapping
from typing import Any

from src.memory.contracts import (
    SCOPE_USER,
    MemoryBinding,
    MemoryExtractRequest,
    MemoryLeaseLostError,
    MemoryUnavailableError,
)
from src.memory.extract import (
    all_confirmed,
    facts_from_frozen,
    retain_frozen_facts,
    serialize_facts,
    validate_extracted_facts,
)
from src.memory.store import (
    STATUS_CLAIMED,
    STATUS_EXTRACTED,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_RETAINING,
    STATUS_RETRY_WAIT,
    active_job,
    job_expired,
    new_job,
    parse_iso,
    refresh_lease,
    retry_due,
    schedule_retry,
    set_watermark,
    utc_now,
    utc_now_iso,
)
from src.memory.turns import (
    bound_extract_turns,
    extractable_turns,
    partition_key,
    select_extract_batch,
    turn_partition,
)

logger = logging.getLogger(__name__)


class MemoryJobMixin:
    async def process_due_jobs(self, *, force: bool = False) -> int:
        processed = 0
        attempted: set[str] = set()
        while True:
            claimed_ids = []
            async with self._tick_lock:
                for session_id in self._store.list_session_ids():
                    if session_id in attempted:
                        continue
                    if await self._claim_if_due(session_id, force=force) is not None:
                        claimed_ids.append(session_id)
                        attempted.add(session_id)
            if not claimed_ids:
                return processed
            await asyncio.gather(*(self._run_claimed_job(sid) for sid in claimed_ids))
            processed += len(claimed_ids)

    async def _claim_if_due(
        self,
        session_id: str,
        *,
        force: bool = False,
    ) -> dict[str, Any] | None:
        ledger = self._store.load(session_id)
        if ledger is None:
            return None
        provider_id = str(ledger.get("provider_id") or "")
        provider = self.running_providers().get(provider_id)
        if provider is None:
            return None
        policy = self.effective_runtime_policy(provider)
        if not policy.auto_consolidate_enabled and not force:
            return None
        job = active_job(ledger)
        now = utc_now()
        if job and str(job.get("status") or "") == STATUS_FAILED:
            return None
        if (
            job
            and str(job.get("status") or "") == STATUS_RETRY_WAIT
            and not retry_due(job, now)
        ):
            return None
        if job and str(job.get("status") or "") not in {"", "completed"}:
            held_by_other = (
                not job_expired(job, now)
                and str(job.get("status") or "") != STATUS_RETRY_WAIT
            )
            if held_by_other:
                return None
            if str(job.get("status") or "") in {
                STATUS_CLAIMED,
                STATUS_EXTRACTING,
                STATUS_EXTRACTED,
                STATUS_RETAINING,
                STATUS_RETRY_WAIT,
            }:
                binding = MemoryBinding(
                    provider_id=provider_id,
                    scope=SCOPE_USER if str(job.get("memory_scope") or "") else "local",
                    bank_id=str(job.get("bank_id") or ""),
                    memory_scope=str(job.get("memory_scope") or ""),
                    policy=policy,
                )
                if not await self._authorize_ledger(ledger, binding):
                    return None
                job_id = str(job.get("id") or "")

                def take_over(
                    current: dict[str, Any], conn: sqlite3.Connection
                ) -> dict[str, Any] | None:
                    current_job = active_job(current)
                    if (
                        current_job is None
                        or str(current_job.get("id") or "") != job_id
                    ):
                        return None
                    status = str(current_job.get("status") or "")
                    if status == STATUS_FAILED:
                        return None
                    expired = job_expired(current_job)
                    if not expired and status != STATUS_RETRY_WAIT:
                        return None
                    if status == STATUS_RETRY_WAIT and not retry_due(current_job):
                        return None
                    if status in {STATUS_RETRY_WAIT} or expired:
                        active = self._store.count_active_jobs(
                            conn=conn,
                            exclude_session_id=session_id,
                        )
                        if active >= max(int(policy.max_concurrent_jobs), 1):
                            return None
                    current_job = refresh_lease(
                        dict(current_job),
                        lease_seconds=policy.lease_seconds,
                    )
                    current_job["worker_id"] = self._worker_id
                    current_job["id"] = uuid.uuid4().hex
                    current_job["retry_at"] = ""
                    current_job["error"] = ""
                    if status == STATUS_RETRY_WAIT:
                        current_job["status"] = (
                            STATUS_EXTRACTED
                            if current_job.get("frozen_facts") is not None
                            else STATUS_CLAIMED
                        )
                    current["job"] = current_job
                    return current

                return self._store.transact(session_id, take_over)

        batch = self._next_batch(ledger, policy.max_batch_turns)
        if batch is None:
            return None
        partition, memory_scope, bank_id, turns = batch
        if not force and not self._trigger_met(ledger, turns, policy):
            return None
        binding = MemoryBinding(
            provider_id=provider_id,
            scope=SCOPE_USER if memory_scope else "local",
            bank_id=bank_id,
            memory_scope=memory_scope,
            policy=policy,
        )
        if not await self._authorize_ledger(ledger, binding):
            return None
        job_id = uuid.uuid4().hex

        def install(
            current: dict[str, Any], conn: sqlite3.Connection
        ) -> dict[str, Any] | None:
            existing = active_job(current)
            if existing is not None:
                status = str(existing.get("status") or "")
                if status == STATUS_FAILED:
                    return None
                if not job_expired(existing) and status != STATUS_RETRY_WAIT:
                    return None
                if status == STATUS_RETRY_WAIT and not retry_due(existing):
                    return None
            active = self._store.count_active_jobs(
                conn=conn, exclude_session_id=session_id
            )
            if active >= max(int(policy.max_concurrent_jobs), 1):
                return None
            pending = self._next_batch(current, policy.max_batch_turns)
            if pending is None:
                return None
            part, scope, bank, batch_turns = pending
            if not force and not self._trigger_met(current, batch_turns, policy):
                return None
            current["job"] = new_job(
                job_id=job_id,
                worker_id=self._worker_id,
                partition=part,
                memory_scope=scope,
                bank_id=bank,
                turn_ids=[str(item.get("turn_id") or "") for item in batch_turns],
                lease_seconds=policy.lease_seconds,
            )
            return current

        return self._store.transact(session_id, install)

    def _next_batch(
        self,
        ledger: Mapping[str, Any],
        max_batch_turns: int,
    ) -> tuple[str, str, str, list[dict[str, Any]]] | None:
        from src.memory.store import watermark_for

        seen_partitions: set[str] = set()
        for turn in ledger.get("turns") or []:
            if not isinstance(turn, Mapping):
                continue
            skip = str(turn.get("skip_reason") or "")
            if skip in {"action_observation", "non_human"}:
                continue
            partition = turn_partition(turn)
            if not partition or partition in seen_partitions:
                continue
            seen_partitions.add(partition)
            pending = [
                item
                for item in extractable_turns(
                    ledger.get("turns") or [],
                    watermark_turn_id=watermark_for(ledger, partition),
                    partition=partition,
                )
                if str(item.get("skip_reason") or "")
                not in {"action_observation", "non_human"}
            ]
            if not pending:
                continue
            memory_scope = str(pending[0].get("memory_scope") or "")
            bank_id = str(pending[0].get("bank_id") or "")
            return (
                partition,
                memory_scope,
                bank_id,
                select_extract_batch(pending, max_turns=max_batch_turns),
            )
        return None

    def _trigger_met(
        self, ledger: Mapping[str, Any], turns: list[dict[str, Any]], policy
    ) -> bool:
        part = turn_partition(turns[0]) if turns else ""
        from src.memory.turns import snapshot_token_count

        length = sum(
            snapshot_token_count(item)
            for item in ledger.get("turns") or []
            if turn_partition(item) == part
            and item.get("skip_reason") not in {"action_observation", "non_human"}
        )
        if length >= policy.consolidate_length_tokens:
            return True
        stamp = parse_iso(str(ledger.get("activity_at") or ""))
        if stamp is None:
            return False
        idle = (utc_now() - stamp).total_seconds()
        return idle >= policy.consolidate_idle_seconds and bool(turns)

    async def _run_claimed_job(self, session_id: str) -> None:
        ledger = self._store.load(session_id)
        if ledger is None:
            return
        job = active_job(ledger)
        if job is None or str(job.get("worker_id") or "") != self._worker_id:
            return
        if str(job.get("status") or "") == STATUS_FAILED:
            return
        job_id = str(job.get("id") or "")
        provider_id = str(ledger.get("provider_id") or "")
        provider = self.running_providers().get(provider_id)
        if provider is None:
            return
        policy = self.effective_runtime_policy(provider)
        turn_ids = {str(item) for item in job.get("turn_ids") or [] if str(item)}
        turns = [
            dict(item)
            for item in ledger.get("turns") or []
            if str(item.get("turn_id") or "") in turn_ids
        ]

        async def authorize_write() -> None:
            latest = self._store.load(session_id)
            active_provider = self.running_providers().get(provider_id)
            if (
                latest is None
                or active_provider is None
                or not self.effective_runtime_policy(active_provider).auto_consolidate_enabled
            ):
                raise MemoryUnavailableError("memory consolidation is disabled")
            if not self._store.renew_lease(
                session_id, job_id, self._worker_id, policy.lease_seconds
            ):
                raise MemoryLeaseLostError("memory job lease lost")
            binding = MemoryBinding(
                provider_id=provider_id,
                scope=SCOPE_USER if job.get("memory_scope") else "local",
                bank_id=str(job.get("bank_id") or ""),
                memory_scope=str(job.get("memory_scope") or ""),
                policy=policy,
            )
            if not await self._authorize_ledger(latest, binding):
                raise MemoryUnavailableError("memory scope unauthorized")
            active_provider = self.running_providers().get(provider_id)
            if (
                active_provider is None
                or not self.effective_runtime_policy(active_provider).auto_consolidate_enabled
            ):
                raise MemoryUnavailableError("memory consolidation is disabled")

        try:
            await authorize_write()
            if job.get("frozen_facts") is None:
                marked = self._store.mutate_job(
                    session_id,
                    job_id,
                    self._worker_id,
                    lambda current, current_job: self._set_job_status(
                        current,
                        current_job,
                        STATUS_EXTRACTING,
                        policy.lease_seconds,
                    ),
                )
                if marked is None:
                    return
                agent_type = self._extract_agent_type(provider_id, provider)
                bounded = bound_extract_turns(turns, max_turns=max(len(turns), 1))
                facts = await self._run_with_heartbeat(
                    session_id,
                    job_id,
                    policy,
                    self._extract_runner.extract(
                        MemoryExtractRequest(
                            session_id=session_id,
                            bank_id=str(job.get("bank_id") or ""),
                            memory_scope=str(job.get("memory_scope") or ""),
                            extract_agent_type=agent_type,
                            turns=tuple(bounded),
                            timeout_seconds=policy.extract_timeout_seconds,
                            model_override=policy.extract_model,
                        )
                    ),
                )
                facts = validate_extracted_facts(facts, bounded)
                frozen = self._store.mutate_job(
                    session_id,
                    job_id,
                    self._worker_id,
                    lambda current, current_job: self._freeze_facts(
                        current,
                        current_job,
                        facts,
                        policy.lease_seconds,
                    ),
                )
                if frozen is None:
                    return
                ledger = frozen
                job = active_job(ledger) or job

            provider = self.running_providers().get(provider_id)
            if provider is None:
                return
            policy = self.effective_runtime_policy(provider)
            if not policy.auto_consolidate_enabled:
                return
            latest = self._store.load(session_id) or ledger
            binding = MemoryBinding(
                provider_id=provider_id,
                scope=SCOPE_USER if str(job.get("memory_scope") or "") else "local",
                bank_id=str(job.get("bank_id") or ""),
                memory_scope=str(job.get("memory_scope") or ""),
                policy=policy,
            )
            if not await self._authorize_ledger(latest, binding):
                self._retry_or_fail(
                    session_id,
                    job_id,
                    policy,
                    "memory scope unauthorized",
                )
                return
            facts = facts_from_frozen(job.get("frozen_facts"))
            if not facts:
                self._complete_job(session_id, job_id, policy, watermark=True)
                return
            retaining = self._store.mutate_job(
                session_id,
                job_id,
                self._worker_id,
                lambda current, current_job: self._set_job_status(
                    current,
                    current_job,
                    STATUS_RETAINING,
                    policy.lease_seconds,
                ),
            )
            if retaining is None:
                return
            results = await self._run_with_heartbeat(
                session_id,
                job_id,
                policy,
                retain_frozen_facts(
                    provider=provider,
                    session_id=session_id,
                    partition=str(
                        job.get("partition")
                        or partition_key(
                            str(job.get("memory_scope") or ""),
                            str(job.get("bank_id") or ""),
                        )
                    ),
                    bank_id=str(job.get("bank_id") or ""),
                    facts=facts,
                    before_retain=authorize_write,
                    timeout_seconds=policy.extract_timeout_seconds,
                ),
                timeout_seconds=policy.extract_timeout_seconds * max(len(facts), 1),
            )
            payload = [
                {
                    "status": item.status,
                    "document_id": item.document_id,
                    "operation_id": item.operation_id,
                    "message": item.message,
                }
                for item in results
            ]
            if all_confirmed(results):
                self._complete_job(
                    session_id,
                    job_id,
                    policy,
                    watermark=True,
                    retain_results=payload,
                )
                return
            self._retry_or_fail(
                session_id,
                job_id,
                policy,
                "retain not confirmed",
                retain_results=payload,
            )
        except MemoryLeaseLostError:
            logger.warning(
                "memory extract lease lost session=%s job=%s", session_id, job_id
            )
        except Exception as exc:
            logger.warning("memory extract job failed", exc_info=True)
            self._retry_or_fail(session_id, job_id, policy, str(exc) or type(exc).__name__)

    async def _run_with_heartbeat(
        self, session_id: str, job_id: str, policy, awaitable, *, timeout_seconds=None
    ):
        lost = asyncio.Event()

        async def beat() -> None:
            interval = max(float(policy.lease_seconds) / 3.0, 0.05)
            while not lost.is_set():
                try:
                    await asyncio.wait_for(lost.wait(), timeout=interval)
                    return
                except asyncio.TimeoutError:
                    if not self._store.renew_lease(
                        session_id,
                        job_id,
                        self._worker_id,
                        policy.lease_seconds,
                    ):
                        lost.set()
                        return

        beater = asyncio.create_task(beat())
        try:
            result = await asyncio.wait_for(
                awaitable,
                timeout=timeout_seconds
                if timeout_seconds is not None
                else policy.extract_timeout_seconds,
            )
            if lost.is_set():
                raise MemoryLeaseLostError("memory job lease lost")
            return result
        except asyncio.TimeoutError as exc:
            raise TimeoutError("memory job timed out") from exc
        finally:
            lost.set()
            beater.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await beater

    def _set_job_status(
        self,
        ledger: dict[str, Any],
        job: dict[str, Any],
        status: str,
        lease_seconds: int,
    ) -> dict[str, Any]:
        job["status"] = status
        ledger["job"] = refresh_lease(job, lease_seconds=lease_seconds)
        return ledger

    def _freeze_facts(
        self,
        ledger: dict[str, Any],
        job: dict[str, Any],
        facts,
        lease_seconds: int,
    ) -> dict[str, Any]:
        job["frozen_facts"] = serialize_facts(facts)
        job["status"] = STATUS_EXTRACTED
        ledger["job"] = refresh_lease(job, lease_seconds=lease_seconds)
        return ledger

    def _complete_job(
        self,
        session_id: str,
        job_id: str,
        policy,
        *,
        watermark: bool,
        retain_results: list[dict[str, Any]] | None = None,
    ) -> None:
        def mutator(ledger: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
            if retain_results is not None:
                job["retain_results"] = retain_results
            if watermark:
                last_turn_id = str((job.get("turn_ids") or [""])[-1] or "")
                if last_turn_id:
                    set_watermark(
                        ledger,
                        str(job.get("partition") or ""),
                        last_turn_id,
                    )
            ledger["last_completed"] = {
                "at": utc_now_iso(),
                "turns": len(job.get("turn_ids") or []),
                "facts": len(job.get("frozen_facts") or []),
            }
            ledger["job"] = None
            return ledger

        self._store.mutate_job(session_id, job_id, self._worker_id, mutator)

    def _retry_or_fail(
        self,
        session_id: str,
        job_id: str,
        policy,
        error: str,
        *,
        retain_results: list[dict[str, Any]] | None = None,
    ) -> None:
        max_retries = max(int(getattr(policy, "max_retries", 1) or 1), 1)

        def mutator(ledger: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
            attempt = int(job.get("attempt") or 1)
            if retain_results is not None:
                job["retain_results"] = retain_results
            job["error"] = error
            if attempt >= max_retries:
                job["status"] = STATUS_FAILED
                ledger["job"] = job
                return ledger
            job["attempt"] = attempt + 1
            ledger["job"] = schedule_retry(
                job,
                delay_seconds=getattr(policy, "retry_delay_seconds", 1),
                lease_seconds=policy.lease_seconds,
            )
            return ledger

        updated = self._store.mutate_job(
            session_id,
            job_id,
            self._worker_id,
            mutator,
            allow_expired=True,
        )
        if updated is None:
            logger.debug("memory job failure persist skipped", exc_info=False)
