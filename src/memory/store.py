"""SQLite ledgers with transactional compare-and-swap and job fencing."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SCHEMA_VERSION = 1
STATUS_IDLE = "idle"
STATUS_CLAIMED = "claimed"
STATUS_EXTRACTING = "extracting"
STATUS_EXTRACTED = "extracted"
STATUS_RETAINING = "retaining"
STATUS_RETRY_WAIT = "retry_wait"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
_ACTIVE_JOB_STATUSES = frozenset(
    {
        STATUS_CLAIMED,
        STATUS_EXTRACTING,
        STATUS_EXTRACTED,
        STATUS_RETAINING,
    }
)
_BUSY_RETRIES = 8


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class MemoryLedgerConflict(RuntimeError):
    """CAS rejected because another writer advanced the ledger."""


class MemoryLedgerStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "ledgers.sqlite"
        self._guard = threading.Lock()
        self._init_schema()

    def path_for(self, session_id: str) -> Path:
        if not _SAFE_SESSION_ID.fullmatch(session_id):
            raise ValueError("memory ledger session_id 无效")
        return self.db_path

    def load(self, session_id: str) -> dict[str, Any] | None:
        self._require_session_id(session_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload, version FROM ledgers WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return self._payload_from_row(row[0], row[1])

    def create(
        self,
        *,
        session_id: str,
        provider_id: str,
        resource_owner: str,
        external_ref: str,
        agent_type: str,
    ) -> dict[str, Any]:
        self._require_session_id(session_id)
        ledger = empty_ledger(
            session_id=session_id,
            provider_id=provider_id,
            resource_owner=resource_owner,
            external_ref=external_ref,
            agent_type=agent_type,
        )
        last_error: Exception | None = None
        for attempt in range(_BUSY_RETRIES):
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT payload, version FROM ledgers WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                if row is not None:
                    conn.execute("ROLLBACK")
                    return self._payload_from_row(row[0], row[1])
                ledger["updated_at"] = utc_now_iso()
                self._upsert(conn, session_id, ledger)
                conn.execute("COMMIT")
                return ledger
            except sqlite3.OperationalError as exc:
                last_error = exc
                message = str(exc).lower()
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                if "busy" not in message and "locked" not in message:
                    raise
                time.sleep(0.01 * (attempt + 1))
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                conn.close()
        if last_error is not None:
            raise last_error
        raise MemoryLedgerConflict("memory ledger create failed")

    def save(self, ledger: Mapping[str, Any]) -> dict[str, Any]:
        session_id = str(ledger.get("session_id") or "")
        expected = int(ledger.get("version") or 0)
        incoming = dict(ledger)

        def mutator(current: dict[str, Any]) -> dict[str, Any]:
            if int(current.get("version") or 0) != expected:
                raise MemoryLedgerConflict("memory ledger version conflict")
            return incoming

        result = self.mutate(session_id, mutator)
        if result is None:
            raise MemoryLedgerConflict("memory ledger version conflict")
        return result

    def compare_and_set(
        self,
        session_id: str,
        expected_version: int,
        mutator,
    ) -> dict[str, Any] | None:
        def guarded(current: dict[str, Any]) -> dict[str, Any] | None:
            if int(current.get("version") or 0) != expected_version:
                return None
            return mutator(dict(current))

        try:
            return self.mutate(session_id, guarded)
        except MemoryLedgerConflict:
            return None

    def mutate(
        self,
        session_id: str,
        mutator: Callable[[dict[str, Any]], dict[str, Any] | None],
        *,
        factory: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        return self.transact(
            session_id,
            lambda current, _conn: mutator(current),
            factory=factory,
        )

    def transact(
        self,
        session_id: str,
        mutator: Callable[[dict[str, Any], sqlite3.Connection], dict[str, Any] | None],
        *,
        factory: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        self._require_session_id(session_id)
        last_error: Exception | None = None
        for attempt in range(_BUSY_RETRIES):
            try:
                return self._mutate_once(session_id, mutator, factory=factory)
            except sqlite3.OperationalError as exc:
                last_error = exc
                message = str(exc).lower()
                if "busy" not in message and "locked" not in message:
                    raise
                time.sleep(0.01 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return None

    def mutate_job(
        self,
        session_id: str,
        job_id: str,
        worker_id: str,
        mutator: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None],
        *,
        allow_expired: bool = False,
    ) -> dict[str, Any] | None:
        wanted_job = str(job_id or "")
        wanted_worker = str(worker_id or "")
        if not wanted_job or not wanted_worker:
            return None

        def guarded(current: dict[str, Any]) -> dict[str, Any] | None:
            job = active_job(current)
            if job is None:
                return None
            if str(job.get("id") or "") != wanted_job:
                return None
            if str(job.get("worker_id") or "") != wanted_worker:
                return None
            if not allow_expired and job_expired(job):
                return None
            return mutator(current, job)

        return self.mutate(session_id, guarded)

    def renew_lease(
        self,
        session_id: str,
        job_id: str,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        def mutator(ledger: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
            ledger["job"] = refresh_lease(job, lease_seconds=lease_seconds)
            return ledger

        return self.mutate_job(session_id, job_id, worker_id, mutator) is not None

    def count_active_jobs(
        self,
        now: datetime | None = None,
        *,
        conn: sqlite3.Connection | None = None,
        exclude_session_id: str = "",
    ) -> int:
        stamp = now or utc_now()
        owned = conn is None
        handle = conn or self._connect()
        try:
            rows = handle.execute(
                "SELECT session_id, job_status, job_lease_until FROM ledgers "
                "WHERE job_id IS NOT NULL"
            ).fetchall()
        finally:
            if owned:
                handle.close()
        count = 0
        for session_id, status, lease_until in rows:
            if exclude_session_id and str(session_id) == exclude_session_id:
                continue
            if str(status or "") not in _ACTIVE_JOB_STATUSES:
                continue
            deadline = parse_iso(str(lease_until or ""))
            if deadline is None or deadline <= stamp:
                continue
            count += 1
        return count

    def list_session_ids(self) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT session_id FROM ledgers ORDER BY session_id"
            ).fetchall()
        finally:
            conn.close()
        return [str(row[0]) for row in rows if _SAFE_SESSION_ID.fullmatch(str(row[0]))]

    def _mutate_once(
        self,
        session_id: str,
        mutator: Callable[[dict[str, Any], sqlite3.Connection], dict[str, Any] | None],
        *,
        factory: Callable[[], dict[str, Any]] | None,
    ) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload, version FROM ledgers WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                if factory is None:
                    conn.execute("ROLLBACK")
                    return None
                current = factory()
                current["session_id"] = session_id
                current["version"] = int(current.get("version") or 0)
                inserted = mutator(dict(current), conn)
                if inserted is None:
                    conn.execute("ROLLBACK")
                    return None
                inserted["version"] = int(current.get("version") or 0)
                inserted["updated_at"] = utc_now_iso()
                self._upsert(conn, session_id, inserted)
                conn.execute("COMMIT")
                return inserted
            current = self._payload_from_row(row[0], row[1])
            updated = mutator(dict(current), conn)
            if updated is None:
                conn.execute("ROLLBACK")
                return None
            next_version = int(current.get("version") or 0) + 1
            updated["session_id"] = session_id
            updated["version"] = next_version
            updated["updated_at"] = utc_now_iso()
            self._upsert(conn, session_id, updated)
            conn.execute("COMMIT")
            return updated
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._guard:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ledgers (
                        session_id TEXT PRIMARY KEY,
                        version INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        job_id TEXT,
                        job_status TEXT,
                        job_worker_id TEXT,
                        job_lease_until TEXT,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_ledgers_job_status "
                    "ON ledgers(job_status)"
                )
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _upsert(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        ledger: Mapping[str, Any],
    ) -> None:
        job = ledger.get("job")
        job_id = None
        job_status = None
        job_worker_id = None
        job_lease_until = None
        if isinstance(job, Mapping) and job:
            job_id = str(job.get("id") or "") or None
            job_status = str(job.get("status") or "") or None
            job_worker_id = str(job.get("worker_id") or "") or None
            job_lease_until = str(job.get("lease_until") or "") or None
        conn.execute(
            """
            INSERT INTO ledgers (
                session_id, version, payload, job_id, job_status,
                job_worker_id, job_lease_until, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                version = excluded.version,
                payload = excluded.payload,
                job_id = excluded.job_id,
                job_status = excluded.job_status,
                job_worker_id = excluded.job_worker_id,
                job_lease_until = excluded.job_lease_until,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                int(ledger.get("version") or 0),
                json.dumps(dict(ledger), ensure_ascii=False),
                job_id,
                job_status,
                job_worker_id,
                job_lease_until,
                str(ledger.get("updated_at") or utc_now_iso()),
            ),
        )

    @staticmethod
    def _payload_from_row(payload: str, version: int) -> dict[str, Any]:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise MemoryLedgerConflict("memory ledger payload 无效")
        data["version"] = int(version)
        return data

    @staticmethod
    def _require_session_id(session_id: str) -> None:
        if not _SAFE_SESSION_ID.fullmatch(session_id):
            raise ValueError("memory ledger session_id 无效")


def empty_ledger(
    *,
    session_id: str,
    provider_id: str,
    resource_owner: str,
    external_ref: str,
    agent_type: str,
) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schema_version": SCHEMA_VERSION,
        "version": 0,
        "session_id": session_id,
        "provider_id": provider_id,
        "resource_owner": resource_owner,
        "external_ref": external_ref,
        "agent_type": agent_type,
        "closed": False,
        "activity_at": now,
        "created_at": now,
        "updated_at": now,
        "turns": [],
        "watermarks": {},
        "seen_turn_ids": [],
        "job": None,
        "recall": {"effective_turns": 0, "last_bank_id": "", "last_memory_scope": ""},
    }


def append_turn(ledger: dict[str, Any], turn: Mapping[str, Any]) -> dict[str, Any]:
    turns = list(ledger.get("turns") or [])
    turn_id = str(turn.get("turn_id") or "")
    seen = [str(item) for item in ledger.get("seen_turn_ids") or [] if str(item)]
    if turn_id and (
        turn_id in seen
        or any(str(item.get("turn_id") or "") == turn_id for item in turns)
    ):
        ledger["activity_at"] = utc_now_iso()
        if turn_id not in seen:
            seen.append(turn_id)
            ledger["seen_turn_ids"] = seen
        return ledger
    turns.append(dict(turn))
    ledger["turns"] = turns
    if turn_id and turn_id not in seen:
        seen.append(turn_id)
    ledger["seen_turn_ids"] = seen
    ledger["activity_at"] = utc_now_iso()
    return ledger


def watermark_for(ledger: Mapping[str, Any], partition: str) -> str:
    watermarks = ledger.get("watermarks") or {}
    if not isinstance(watermarks, Mapping):
        return ""
    return str(watermarks.get(partition) or "")


def set_watermark(ledger: dict[str, Any], partition: str, turn_id: str) -> None:
    from src.memory.turns import turn_partition

    watermarks = dict(ledger.get("watermarks") or {})
    watermarks[partition] = turn_id
    ledger["watermarks"] = watermarks
    seen = [str(item) for item in ledger.get("seen_turn_ids") or [] if str(item)]
    if turn_id and turn_id not in seen:
        seen.append(turn_id)
    retained: list[dict[str, Any]] = []
    dropping = bool(turn_id)
    found = False
    for turn in ledger.get("turns") or []:
        current_id = str(turn.get("turn_id") or "")
        current_partition = turn_partition(turn)
        if current_partition != partition:
            retained.append(dict(turn))
            continue
        if current_id and current_id not in seen:
            seen.append(current_id)
        if dropping:
            if current_id == turn_id:
                dropping = False
                found = True
            continue
        retained.append(dict(turn))
    if turn_id and not found:
        retained = [dict(turn) for turn in ledger.get("turns") or []]
    ledger["turns"] = retained
    ledger["seen_turn_ids"] = seen


def job_expired(job: Mapping[str, Any] | None, now: datetime | None = None) -> bool:
    if not job:
        return True
    deadline = parse_iso(str(job.get("lease_until") or ""))
    if deadline is None:
        return True
    return deadline <= (now or utc_now())


def retry_due(job: Mapping[str, Any] | None, now: datetime | None = None) -> bool:
    if not job:
        return True
    stamp = now or utc_now()
    if job_expired(job, stamp):
        return True
    retry_at = parse_iso(str(job.get("retry_at") or ""))
    if retry_at is None:
        return True
    return retry_at <= stamp


def active_job(ledger: Mapping[str, Any]) -> dict[str, Any] | None:
    job = ledger.get("job")
    if isinstance(job, Mapping) and job:
        return dict(job)
    return None


def new_job(
    *,
    job_id: str,
    worker_id: str,
    partition: str,
    memory_scope: str,
    bank_id: str,
    turn_ids: list[str],
    lease_seconds: int,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "id": job_id,
        "status": STATUS_CLAIMED,
        "worker_id": worker_id,
        "partition": partition,
        "memory_scope": memory_scope,
        "bank_id": bank_id,
        "turn_ids": list(turn_ids),
        "attempt": 1,
        "lease_until": (
            now + timedelta(seconds=max(int(lease_seconds), 1))
        ).isoformat(),
        "retry_at": "",
        "frozen_facts": None,
        "retain_results": [],
        "error": "",
        "claimed_at": now.isoformat(),
    }


def refresh_lease(job: dict[str, Any], *, lease_seconds: int) -> dict[str, Any]:
    job["lease_until"] = (
        utc_now() + timedelta(seconds=max(int(lease_seconds), 1))
    ).isoformat()
    return job


def schedule_retry(
    job: dict[str, Any], *, delay_seconds: float, lease_seconds: int
) -> dict[str, Any]:
    delay = max(float(delay_seconds or 0), 0.0)
    retry_at = utc_now() + timedelta(seconds=delay)
    job["status"] = STATUS_RETRY_WAIT
    job["retry_at"] = retry_at.isoformat()
    hold = max(delay, float(max(int(lease_seconds), 1)))
    job["lease_until"] = (utc_now() + timedelta(seconds=hold)).isoformat()
    return job
