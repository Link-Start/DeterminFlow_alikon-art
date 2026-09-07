"""One local account session shared by Core and official capabilities."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from uuid import uuid4

from .browser_auth import AccountBrowserAuthorizationFlow
from .portal import AccountPortalClient, AccountRequestError

_STATE_SCHEMA_VERSION = 1
_MAX_ISSUER_CHARS = 256
_MAX_SUBJECT_CHARS = 128
_PROFILE_WAIT_SECONDS = 4


def _discard_task_result(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()


def _login_cancelled() -> AccountRequestError:
    return AccountRequestError(
        "authorization_denied",
        "账号登录已取消",
        status_code=400,
    )


class CoreAccountService:
    def __init__(
        self,
        *,
        data_dir: Path,
        portal: AccountPortalClient | None,
        browser_auth: AccountBrowserAuthorizationFlow | None = None,
        login_timeout_seconds: float = 180,
    ) -> None:
        self.portal = portal
        self.browser_auth = browser_auth or AccountBrowserAuthorizationFlow()
        self.state_path = data_dir.expanduser().resolve() / "account" / "session.json"
        self._operation_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._profile_lock = asyncio.Lock()
        self._profile_task: asyncio.Task[None] | None = None
        self._profile_name: str | None = None
        self._profile_loaded = False
        self._profile_retry_after = 0.0
        self._generation = 0
        self._session_epoch = 0
        self._session_tokens: OrderedDict[str, None] = OrderedDict()
        self._login_epoch = 0
        self._login_flight: asyncio.Task[dict[str, Any]] | None = None
        self._authorize_task: asyncio.Task[dict[str, str]] | None = None
        self._login_attempt_ids: set[str] = set()
        self._cancelled_attempts: OrderedDict[str, float] = OrderedDict()
        self._login_timeout_seconds = login_timeout_seconds
        self.state = self._load_state()
        self._remember_session_access_token()

    @property
    def installation_id(self) -> str:
        return str(self.state["installation_id"])

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.portal is not None,
            "signed_in": self.access_token() is not None,
        }

    def access_token(self) -> str | None:
        session = self._session()
        return session["access_token"] if session is not None else None

    def public_name(self) -> str | None:
        """Prefer current account profile data, with the login claim as fallback."""
        if self._profile_loaded and self.access_token() is not None:
            return self._profile_name
        payload = self._jwt_payload()
        if payload is None:
            return None
        name = payload.get("name")
        if not isinstance(name, str):
            return None
        normalized = name.strip()
        return normalized[:80] or None

    async def refresh_public_name(self) -> None:
        """Best-effort, bounded profile refresh; never mix identities across logout."""
        if self.portal is None or not callable(getattr(self.portal, "profile", None)):
            return
        if self.access_token() is None or time.monotonic() < self._profile_retry_after:
            return
        if self._profile_task is None or self._profile_task.done():
            self._profile_task = asyncio.create_task(self._refresh_public_name())
            self._profile_task.add_done_callback(_discard_task_result)
        try:
            # A status request must not cancel an in-progress token rotation.
            await asyncio.wait_for(asyncio.shield(self._profile_task), timeout=_PROFILE_WAIT_SECONDS)
        except TimeoutError:
            pass

    async def _refresh_public_name(self) -> None:
        async with self._profile_lock:
            token = self.access_token()
            if token is None or time.monotonic() < self._profile_retry_after:
                return
            generation = self._generation

            async def fetch_profile() -> dict[str, Any] | None:
                nonlocal token, generation
                try:
                    return await self.portal.profile(token)
                except AccountRequestError as exc:
                    if exc.status_code != 401 or generation != self._generation:
                        raise
                    token = await self.refresh_access_token(token)
                    if token is None:
                        return None
                    generation = self._generation
                    return await self.portal.profile(token)

            try:
                profile = await fetch_profile()
            except (AccountRequestError, TimeoutError):
                if generation == self._generation:
                    self._profile_retry_after = time.monotonic() + 30
                return
            if generation != self._generation or token != self.access_token() or profile is None:
                return
            identity = self.local_identity_claims()
            if identity is None or profile.get("sub") != identity[1]:
                self._profile_retry_after = time.monotonic() + 30
                return
            self._profile_name = profile.get("name")
            self._profile_loaded = True
            self._profile_retry_after = time.monotonic() + 300

    def local_identity_claims(self) -> tuple[str, str] | None:
        """Stable issuer and subject for local partitioning. Not a display name."""
        payload = self._jwt_payload()
        if payload is None:
            return None
        issuer = payload.get("iss")
        subject = payload.get("sub")
        if not isinstance(issuer, str) or not isinstance(subject, str):
            return None
        issuer = issuer.strip()
        subject = subject.strip()
        if (
            not issuer
            or not subject
            or "\0" in issuer
            or "\0" in subject
            or len(issuer) > _MAX_ISSUER_CHARS
            or len(subject) > _MAX_SUBJECT_CHARS
        ):
            return None
        return issuer, subject

    async def login(self, attempt_id: str | None = None) -> dict[str, Any]:
        self._require_portal()
        async with self._operation_lock:
            self._prune_cancelled_attempts()
            if attempt_id in self._cancelled_attempts:
                raise _login_cancelled()
            flight = self._login_flight
            if flight is None or flight.done():
                flight = asyncio.create_task(self._complete_login(self._login_epoch))
                flight.add_done_callback(_discard_task_result)
                self._login_flight = flight
                self._login_attempt_ids.clear()
            if attempt_id:
                self._login_attempt_ids.add(attempt_id)
        # Shield so one HTTP waiter cancelling cannot abort the shared authorize.
        try:
            return await asyncio.shield(flight)
        except asyncio.CancelledError:
            if flight.cancelled():
                raise _login_cancelled() from None
            raise

    def _prune_cancelled_attempts(self) -> None:
        cutoff = time.monotonic() - 300
        while self._cancelled_attempts:
            first = next(iter(self._cancelled_attempts))
            if len(self._cancelled_attempts) <= 128 and self._cancelled_attempts[first] >= cutoff:
                break
            self._cancelled_attempts.popitem(last=False)

    async def cancel_login(self, attempt_id: str) -> dict[str, Any]:
        """Cancel one shared authorization without logging out an existing session."""
        async with self._operation_lock:
            # A cancellation can arrive before its login HTTP request.
            self._cancelled_attempts[attempt_id] = time.monotonic()
            self._cancelled_attempts.move_to_end(attempt_id)
            self._prune_cancelled_attempts()
            if attempt_id not in self._login_attempt_ids:
                return self.status()
            self._login_epoch += 1
            flight, authorize = self._login_flight, self._authorize_task
            self._login_flight = self._authorize_task = None
            self._login_attempt_ids.clear()
        for task in (authorize, flight):
            if task is not None and not task.done():
                task.cancel()
        if flight is not None:
            await asyncio.wait({flight}, timeout=1)
        return self.status()

    async def logout(self) -> dict[str, Any]:
        async with self._operation_lock:
            self._login_epoch += 1
            authorize = self._authorize_task
            self._authorize_task = None
            self._login_flight = None
            self._login_attempt_ids.clear()
            session = self._session()
            self._replace_session(None)
        if authorize is not None and not authorize.done():
            authorize.cancel()
        if session is not None and self.portal is not None:
            try:
                await self.portal.logout(session["refresh_token"])
            except AccountRequestError:
                pass
        return self.status()

    async def refresh_access_token(self, stale_access_token: str) -> str | None:
        portal = self._require_portal()
        async with self._refresh_lock:
            current = self._session()
            if current is None:
                return None
            epoch = self._session_epoch
            if current["access_token"] != stale_access_token:
                if (
                    stale_access_token in self._session_tokens
                    and epoch == self._session_epoch
                ):
                    return current["access_token"]
                return None
            try:
                tokens = await portal.refresh(current["refresh_token"])
            except AccountRequestError as exc:
                if exc.code != "authentication_failed":
                    raise
                async with self._operation_lock:
                    if epoch != self._session_epoch:
                        return None
                    self._replace_session(None)
                    return None
            async with self._operation_lock:
                if epoch != self._session_epoch:
                    return None
                self._replace_session(tokens, rotate=True)
                return tokens["access_token"]

    async def _complete_login(self, epoch: int) -> dict[str, Any]:
        portal = self._require_portal()
        authorize = asyncio.create_task(
            self.browser_auth.authorize(portal, self.installation_id),
        )
        previous = None
        try:
            async with self._operation_lock:
                if epoch != self._login_epoch:
                    raise _login_cancelled()
                self._authorize_task = authorize
            try:
                done, _ = await asyncio.wait({authorize}, timeout=self._login_timeout_seconds)
                if not done:
                    raise AccountRequestError("authorization_timeout", "账号登录已超时，请重试")
                tokens = authorize.result()
            except asyncio.CancelledError:
                raise _login_cancelled() from None
            async with self._operation_lock:
                if epoch != self._login_epoch:
                    raise _login_cancelled()
                previous = self._session()
                self._replace_session(tokens)
            if previous is not None:
                try:
                    await portal.logout(previous["refresh_token"])
                except AccountRequestError:
                    pass
            return self.status()
        finally:
            if not authorize.done():
                authorize.cancel()
            authorize.add_done_callback(_discard_task_result)
            async with self._operation_lock:
                if self._authorize_task is authorize:
                    self._authorize_task = None
                if self._login_flight is asyncio.current_task():
                    self._login_flight = None
                    self._login_attempt_ids.clear()

    def current_session_id(self) -> int:
        return self._session_epoch

    def is_current_session(self, session_id: int) -> bool:
        return self.access_token() is not None and session_id == self._session_epoch

    def is_current_access_token(self, access_token: str) -> bool:
        return self.access_token() == access_token

    def _jwt_payload(self) -> dict[str, Any] | None:
        token = self.access_token()
        if token is None:
            return None
        try:
            payload_segment = token.split(".")[1]
            padding = "=" * (-len(payload_segment) % 4)
            payload = json.loads(
                base64.urlsafe_b64decode(payload_segment + padding).decode("utf-8")
            )
        except (IndexError, UnicodeDecodeError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    def clear_invalid_access_token(self, access_token: str) -> None:
        if self.is_current_access_token(access_token):
            self._replace_session(None)

    def _replace_session(self, tokens: dict[str, str] | None, *, rotate: bool = False) -> None:
        self._generation += 1
        if not rotate:
            self._session_epoch += 1
            self._session_tokens.clear()
        self._profile_name = None
        self._profile_loaded = False
        self._profile_retry_after = 0.0
        self.state["session"] = tokens
        self._remember_session_access_token()
        self._save_state()

    def _remember_session_access_token(self) -> None:
        session = self._session()
        if session is None:
            return
        token = session["access_token"]
        self._session_tokens[token] = None
        self._session_tokens.move_to_end(token)
        while len(self._session_tokens) > 8:
            self._session_tokens.popitem(last=False)

    def _session(self) -> dict[str, str] | None:
        value = self.state.get("session")
        if not isinstance(value, dict):
            return None
        access_token = value.get("access_token")
        refresh_token = value.get("refresh_token")
        if not isinstance(access_token, str) or not access_token:
            return None
        if not isinstance(refresh_token, str) or not refresh_token:
            return None
        return {"access_token": access_token, "refresh_token": refresh_token}

    def _new_state(self) -> dict[str, Any]:
        return {
            "schema_version": _STATE_SCHEMA_VERSION,
            "installation_id": f"desktop:{uuid4()}",
            "session": None,
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            state = self._new_state()
            self._save_state(state)
            return state
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if (
                not isinstance(state, dict)
                or state.get("schema_version") != _STATE_SCHEMA_VERSION
                or not isinstance(state.get("installation_id"), str)
                or not state["installation_id"]
            ):
                raise ValueError("unsupported account state")
            os.chmod(self.state_path, 0o600)
            return state
        except (OSError, ValueError):
            state = self._new_state()
            self._save_state(state)
            return state

    def _save_state(self, state: dict[str, Any] | None = None) -> None:
        target = self.state if state is None else state
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".json.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(target, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _require_portal(self) -> AccountPortalClient:
        if self.portal is None:
            raise AccountRequestError(
                "account_not_configured",
                "DeterminFlow 账号服务尚未配置",
                status_code=503,
            )
        return self.portal
