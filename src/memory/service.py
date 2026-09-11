"""Public Core memory runtime used by sessions, tools, and background extract."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.memory.binding import (
    invocation_memory_scope,
    is_valid_memory_scope,
    resolve_memory_binding,
)
from src.memory.contracts import (
    GRAPH_DEFAULT_LIMIT,
    GRAPH_LIMIT_MAX,
    GRAPH_LIMIT_MIN,
    SCOPE_USER,
    SKIP_RESUME,
    MemoryBinding,
    MemoryExtractRunner,
    MemoryGraph,
    MemoryGraphRequest,
    MemoryProvider,
    MemoryRecallRequest,
    MemoryReflectRequest,
    MemoryRetainRequest,
    MemoryRetainResult,
    MemoryScopeAuthorizer,
    MemoryUnavailableError,
)
from src.memory.graph import project_memory_graph
from src.memory.extract import DefaultExtractRunner
from src.memory.jobs import MemoryJobMixin
from src.memory.management import MemoryJobManagementMixin
from src.memory.recall import (
    build_auto_recall_query,
    memory_ids_in_model_messages,
    recall_into_model_context,
    strip_foreign_memory_context,
)
from src.memory.provider_status import build_provider_statuses
from src.memory.settings import (
    MemorySettings,
    MemorySettingsStore,
    default_memory_settings,
    overlay_memory_policy,
)
from src.memory.store import (
    MemoryLedgerStore,
    append_turn,
    utc_now_iso,
)
from src.memory.turns import latest_complete_turn, skip_reason_for_turn
from src.session.context import get_session_context

logger = logging.getLogger(__name__)

OwnerStatus = Callable[[str], Mapping[str, Any]]
ResolveResource = Callable[[str, str, str], str]
_CONFIGURED_STATUSES = frozenset({"running", "degraded"})

_runtime: "MemoryRuntimeService | None" = None


def get_memory_runtime() -> "MemoryRuntimeService | None":
    return _runtime


def set_memory_runtime(service: "MemoryRuntimeService | None") -> None:
    global _runtime
    _runtime = service


class MemoryRuntimeService(MemoryJobMixin, MemoryJobManagementMixin):
    def __init__(
        self,
        root: Path,
        *,
        extract_runner: MemoryExtractRunner | None = None,
        worker_id: str | None = None,
        settings_store: MemorySettingsStore | None = None,
    ):
        self._store = MemoryLedgerStore(Path(root))
        self._extract_runner = extract_runner or DefaultExtractRunner()
        self._worker_id = worker_id or f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._settings_store = settings_store or MemorySettingsStore()
        self._authorizers: dict[str, MemoryScopeAuthorizer] = {}
        self._providers: dict[str, MemoryProvider] = {}
        self._owner_status: OwnerStatus | None = None
        self._resolve_resource: ResolveResource | None = None
        self._tick_lock = asyncio.Lock()
        self._scheduler_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def attach(
        self,
        *,
        authorizers: Mapping[str, MemoryScopeAuthorizer] | None = None,
        providers: Mapping[str, MemoryProvider] | None = None,
        owner_status: OwnerStatus | None = None,
        resolve_resource: ResolveResource | None = None,
        extract_runner: MemoryExtractRunner | None = None,
    ) -> None:
        if authorizers is not None:
            self._authorizers = dict(authorizers)
        if providers is not None:
            self._providers = dict(providers)
        if owner_status is not None:
            self._owner_status = owner_status
        if resolve_resource is not None:
            self._resolve_resource = resolve_resource
        if extract_runner is not None:
            self._extract_runner = extract_runner
        self.migrate_settings_if_needed()

    @property
    def store(self) -> MemoryLedgerStore:
        return self._store

    def owner_status_name(self, owner: str) -> str:
        if not owner:
            return "missing"
        if self._owner_status is None:
            if owner in self._providers or owner in self._authorizers:
                return "running"
            return "missing"
        state = self._owner_status(owner) or {}
        return str(state.get("status") or "") or "missing"

    def owner_is_running(self, owner: str) -> bool:
        return self.owner_status_name(owner) == "running"

    def owner_is_degraded(self, owner: str) -> bool:
        return self.owner_status_name(owner) == "degraded"

    def owner_is_configured(self, owner: str) -> bool:
        return (
            owner in self._providers
            and self.owner_status_name(owner) in _CONFIGURED_STATUSES
        )

    def registered_providers(self) -> dict[str, MemoryProvider]:
        return dict(self._providers)

    def running_providers(self) -> dict[str, MemoryProvider]:
        return self._apply_provider_gate(
            {
                owner: provider
                for owner, provider in self._providers.items()
                if self.owner_is_running(owner)
            }
        )

    def configured_providers(self) -> dict[str, MemoryProvider]:
        return self._apply_provider_gate(
            {
                owner: provider
                for owner, provider in self._providers.items()
                if self.owner_is_configured(owner)
            }
        )

    def migrate_settings_if_needed(self) -> MemorySettings | None:
        # Contributions are registered before plugin start/configure. Migrate
        # only after start, otherwise constructor defaults replace saved values.
        configured = {
            owner: provider for owner, provider in self._providers.items()
            if self.owner_is_configured(owner)
        }
        return self._settings_store.migrate_from_providers(configured)

    def resolved_memory_settings(self) -> MemorySettings:
        migrated = self.migrate_settings_if_needed()
        if migrated is not None:
            return migrated
        return default_memory_settings()

    def persisted_memory_settings(self) -> MemorySettings | None:
        return self._settings_store.persisted_settings()

    @property
    def settings_read_error(self) -> bool:
        return self._settings_store.read_error

    def effective_runtime_policy(
        self,
        provider: MemoryProvider,
        agent_type: str = "",
    ):
        agent_policy = getattr(provider, "runtime_policy_for_agent", None)
        if agent_type and callable(agent_policy):
            policy = agent_policy(agent_type)
        else:
            policy = provider.runtime_policy()
        settings = self.persisted_memory_settings()
        if settings is None:
            return policy
        return overlay_memory_policy(policy, settings)

    async def replace_settings(self, settings: MemorySettings) -> MemorySettings:
        saved = self._settings_store.save(settings)
        await self.stop()
        await self.start()
        return saved

    async def provider_statuses(self, management: Any = None) -> list[dict[str, Any]]:
        settings = self.resolved_memory_settings()
        provider_ids = list(self._providers)
        if settings.provider_id:
            provider_ids.append(settings.provider_id)
        return await build_provider_statuses(
            provider_ids=provider_ids,
            providers=self._providers,
            owner_status_name=self.owner_status_name,
            management=management,
        )

    def _apply_provider_gate(
        self,
        providers: Mapping[str, MemoryProvider],
    ) -> dict[str, MemoryProvider]:
        settings = self.persisted_memory_settings()
        if settings is None:
            return dict(providers)
        if not settings.enables_external() or not settings.provider_id:
            return {}
        provider = providers.get(settings.provider_id)
        if provider is None:
            return {}
        return {settings.provider_id: provider}

    async def start(self) -> None:
        if not any(
            self.effective_runtime_policy(provider).auto_consolidate_enabled
            for provider in self.configured_providers().values()
        ):
            return
        if self._scheduler_task and not self._scheduler_task.done():
            return
        self._stop_event.clear()
        self._scheduler_task = asyncio.create_task(
            self._run_loop(),
            name="memory-extract-scheduler",
        )

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._scheduler_task
        self._scheduler_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def note_activity(self, session: Any) -> None:
        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id:
            return
        self._store.mutate(
            session_id,
            lambda ledger: {**ledger, "activity_at": utc_now_iso()},
        )

    async def prepare_turn_model_context(
        self,
        *,
        session: Any,
        content: str,
        source: str,
        invocation_context: Mapping[str, str] | None,
        model_context: Mapping[str, Any] | None,
    ) -> Mapping[str, Any] | None:
        if source == "human":
            await self.note_activity(session)
        original = deepcopy(dict(model_context)) if model_context is not None else None
        skip = skip_reason_for_turn(
            content=content,
            source=source,
            append_input=True,
            model_context=model_context,
        )
        if skip:
            return original
        binding = await self._binding_for_session(
            session,
            invocation_context=invocation_context,
            require_scope=True,
            providers=self.running_providers(),
        )
        if binding is None or not binding.policy.auto_recall_enabled:
            return original
        provider = self.running_providers().get(binding.provider_id)
        if provider is None:
            return original
        strip_foreign_memory_context(
            getattr(session, "lc_messages", None),
            bank_id=binding.bank_id,
            memory_scope=binding.memory_scope,
        )
        strip_foreign_memory_context(
            getattr(session, "record", None),
            bank_id=binding.bank_id,
            memory_scope=binding.memory_scope,
        )
        ledger = self._store.load(str(getattr(session, "session_id", "") or ""))
        effective_turns = int(
            (ledger or {}).get("recall", {}).get("effective_turns") or 0
        )
        first_effective = effective_turns == 0
        exclude_ids = memory_ids_in_model_messages(
            getattr(session, "lc_messages", []) or []
        )
        query = build_auto_recall_query(content, getattr(session, "record", []) or [])

        async def _recall() -> Mapping[str, Any] | None:
            if not await self._authorize(session, binding, foreground=True):
                return original
            if self.running_providers().get(binding.provider_id) is not provider:
                return original
            return await recall_into_model_context(
                provider=provider,
                binding=binding,
                query=query,
                model_context=model_context,
                exclude_ids=exclude_ids,
                first_effective=first_effective,
            )

        try:
            recalled = await asyncio.wait_for(
                _recall(),
                timeout=binding.policy.recall_timeout_seconds,
            )
        except Exception:
            logger.warning("memory recall failed open", exc_info=True)
            return original
        if (
            self.running_providers().get(binding.provider_id) is not provider
            or not self.effective_runtime_policy(provider).auto_recall_enabled
        ):
            return original
        self._remember_recall_scope(session, binding)
        return recalled

    async def record_completed_invocation(
        self,
        *,
        session: Any,
        content: str,
        source: str,
        append_input: bool,
        invocation_context: Mapping[str, str] | None,
        model_context: Mapping[str, Any] | None,
    ) -> None:
        if getattr(session, "pending_tool_resolutions", None):
            return
        status = str(getattr(session, "status", "") or "")
        if status in {"error", "cancelled", "awaiting_tool_resolution"}:
            return
        skip = skip_reason_for_turn(
            content=content,
            source=source,
            append_input=append_input,
            model_context=model_context,
        )
        binding = await self._binding_for_session(
            session,
            invocation_context=invocation_context,
            require_scope=False,
            providers=self.configured_providers(),
        )
        if binding is None:
            return
        if not self.owner_is_configured(binding.provider_id):
            return
        if not await self._authorize(session, binding, foreground=True):
            return
        snapshot_skip = None if skip == SKIP_RESUME else skip
        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id:
            return

        def mutator(ledger: dict[str, Any]) -> dict[str, Any]:
            known = {
                str(item) for item in ledger.get("seen_turn_ids") or [] if str(item)
            }
            known.update(
                str(item.get("turn_id") or "") for item in ledger.get("turns") or []
            )
            turn = latest_complete_turn(
                getattr(session, "record", []) or [],
                known_turn_ids=known,
                session_id=session_id,
                skip_reason=snapshot_skip,
                started_at=utc_now_iso(),
                memory_scope=binding.memory_scope,
                bank_id=binding.bank_id,
            )
            if turn is None:
                ledger["activity_at"] = utc_now_iso()
                return ledger
            ledger = append_turn(ledger, turn)
            recall_state = dict(ledger.get("recall") or {})
            if snapshot_skip is None:
                recall_state["effective_turns"] = (
                    int(recall_state.get("effective_turns") or 0) + 1
                )
            ledger["recall"] = recall_state
            ledger["external_ref"] = str(
                getattr(session, "external_ref", "") or ledger.get("external_ref") or ""
            )
            ledger["resource_owner"] = str(
                getattr(session, "resource_owner", "")
                or ledger.get("resource_owner")
                or ""
            )
            return ledger

        self._store.mutate(
            session_id,
            mutator,
            factory=lambda: self._empty_ledger(session, binding),
        )

    async def mark_session_closed(self, session: Any) -> None:
        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id:
            return

        def mutator(ledger: dict[str, Any]) -> dict[str, Any]:
            ledger["closed"] = True
            ledger["activity_at"] = utc_now_iso()
            return ledger

        try:
            self._store.mutate(session_id, mutator)
        except Exception:
            logger.debug("memory ledger close failed", exc_info=True)

    async def read_graph(
        self,
        *,
        resource_owner: str,
        external_ref: str,
        memory_scope: str,
        agent_type: str,
        limit: int = GRAPH_DEFAULT_LIMIT,
    ) -> MemoryGraph:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("memory graph limit must be an integer")
        if limit < GRAPH_LIMIT_MIN or limit > GRAPH_LIMIT_MAX:
            raise ValueError("memory graph limit must be 1..300")
        owner = str(resource_owner or "").strip()
        ref = str(external_ref or "").strip()
        scope = str(memory_scope or "").strip().lower()
        agent = str(agent_type or "").strip()
        if not owner or not ref or not agent:
            raise MemoryUnavailableError("memory graph unavailable")
        session = _SessionView(
            {
                "agent_type": agent,
                "resource_owner": owner,
                "external_ref": ref,
                "session_type": "sub",
                "lifecycle_profile": "detached_conversation",
            }
        )
        providers = self.running_providers()
        if not providers:
            raise MemoryUnavailableError("memory provider unavailable")
        binding = await self._binding_for_session(
            session,
            invocation_context={"memory_scope": scope} if scope else {},
            require_scope=True,
            providers=providers,
        )
        if binding is None or not binding.bank_id:
            raise MemoryUnavailableError("memory binding unavailable")
        provider = providers.get(binding.provider_id)
        graph_fn = getattr(provider, "graph", None) if provider is not None else None
        if provider is None or not callable(graph_fn):
            raise MemoryUnavailableError("memory graph unavailable")
        timeout = float(binding.policy.recall_timeout_seconds)

        async def _read() -> MemoryGraph:
            if not await self._authorize(session, binding, foreground=True):
                raise MemoryUnavailableError(
                    "memory scope unauthorized",
                    code="memory_unauthorized",
                )
            live = self.running_providers().get(binding.provider_id)
            live_graph = getattr(live, "graph", None) if live is not None else None
            if live is not provider or not callable(live_graph):
                raise MemoryUnavailableError("memory graph unavailable")
            raw = await live_graph(
                MemoryGraphRequest(bank_id=binding.bank_id, limit=limit)
            )
            if not await self._authorize(session, binding, foreground=True):
                raise MemoryUnavailableError(
                    "memory scope unauthorized",
                    code="memory_unauthorized",
                )
            if self.running_providers().get(binding.provider_id) is not live:
                raise MemoryUnavailableError("memory provider unavailable")
            return project_memory_graph(raw, limit=limit)

        try:
            return await asyncio.wait_for(_read(), timeout=timeout)
        except MemoryUnavailableError:
            raise
        except asyncio.TimeoutError as exc:
            raise MemoryUnavailableError("memory graph timed out") from exc
        except Exception as exc:
            logger.warning("memory graph failed", exc_info=True)
            raise MemoryUnavailableError("memory graph unavailable") from exc

    async def tool_recall(
        self,
        query: str,
        *,
        budget: str = "mid",
        types: tuple[str, ...] | list[str] = (),
        max_tokens: int = 2048,
    ) -> list[dict[str, object]]:
        binding, provider, _session = await self._tool_binding()
        results = await provider.recall(
            MemoryRecallRequest(
                query=query,
                bank_id=binding.bank_id,
                budget=budget,
                types=tuple(item for item in types if item),
                max_tokens=max_tokens,
            )
        )
        return [
            {
                "id": item.id,
                "text": item.text,
                "type": item.type,
                "provenance": getattr(item, "provenance", "") or "",
            }
            for item in results
        ]

    async def tool_reflect(self, query: str, *, budget: str = "mid") -> str:
        binding, provider, _session = await self._tool_binding()
        return await provider.reflect(
            MemoryReflectRequest(
                query=query,
                bank_id=binding.bank_id,
                budget=budget,
            )
        )

    async def tool_retain(
        self,
        content: str,
        *,
        tags: tuple[str, ...] | list[str] = (),
    ) -> MemoryRetainResult:
        binding, provider, session = await self._tool_binding()
        document_id = f"dfm-tool-{uuid.uuid4().hex}"
        return await provider.retain(
            MemoryRetainRequest(
                content=content,
                bank_id=binding.bank_id,
                document_id=document_id,
                timestamp=utc_now_iso(),
                metadata={
                    "session_id": str(getattr(session, "session_id", "") or ""),
                    "source": "tool",
                },
                tags=tuple(tags),
                context="agent retain tool",
                retain_async=False,
            )
        )

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.process_due_jobs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("memory extract tick failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=15)
            except asyncio.TimeoutError:
                continue

    def _empty_ledger(self, session: Any, binding: MemoryBinding) -> dict[str, Any]:
        from src.memory.store import empty_ledger

        return empty_ledger(
            session_id=str(getattr(session, "session_id", "") or ""),
            provider_id=binding.provider_id,
            resource_owner=str(getattr(session, "resource_owner", "") or ""),
            external_ref=str(getattr(session, "external_ref", "") or ""),
            agent_type=str(getattr(session, "agent_type", "") or ""),
        )

    def _remember_recall_scope(self, session: Any, binding: MemoryBinding) -> None:
        session_id = str(getattr(session, "session_id", "") or "")
        if not session_id:
            return

        def mutator(ledger: dict[str, Any]) -> dict[str, Any]:
            recall_state = dict(ledger.get("recall") or {})
            recall_state["last_bank_id"] = binding.bank_id
            recall_state["last_memory_scope"] = binding.memory_scope
            ledger["recall"] = recall_state
            return ledger

        self._store.mutate(session_id, mutator)

    def _extract_agent_type(self, provider_id: str, provider: MemoryProvider) -> str:
        local_id = provider.extract_agent_local_id()
        if not local_id:
            raise RuntimeError("memory extract Agent local id 为空")
        if self._resolve_resource is None:
            return local_id
        return self._resolve_resource(provider_id, "agents", local_id)

    async def _binding_for_session(
        self,
        session: Any,
        *,
        invocation_context: Mapping[str, str] | None,
        require_scope: bool,
        providers: Mapping[str, MemoryProvider] | None = None,
    ) -> MemoryBinding | None:
        available = dict(
            providers if providers is not None else self.running_providers()
        )
        if not available:
            return None
        from src.agent.definition import get_agent_definition

        agent_def = get_agent_definition(getattr(session, "agent_type", "") or "")
        memory_scope = invocation_memory_scope(invocation_context)
        binding = resolve_memory_binding(
            session=session,
            agent_definition=agent_def,
            providers=available,
            memory_scope=memory_scope,
        )
        if binding is None:
            return None
        if binding.scope == SCOPE_USER:
            if require_scope and not is_valid_memory_scope(binding.memory_scope):
                return None
        settings = self.persisted_memory_settings()
        if settings is not None:
            binding = replace(
                binding,
                policy=overlay_memory_policy(binding.policy, settings),
            )
        return binding

    async def _authorize(
        self,
        session: Any,
        binding: MemoryBinding,
        *,
        foreground: bool,
    ) -> bool:
        if binding.scope != SCOPE_USER:
            return True
        owner = str(getattr(session, "resource_owner", "") or "")
        external_ref = str(getattr(session, "external_ref", "") or "")
        return await self._authorize_values(
            resource_owner=owner,
            external_ref=external_ref,
            memory_scope=binding.memory_scope,
            foreground=foreground,
        )

    async def _authorize_ledger(
        self,
        ledger: Mapping[str, Any],
        binding: MemoryBinding,
    ) -> bool:
        if binding.scope != SCOPE_USER:
            return True
        return await self._authorize_values(
            resource_owner=str(ledger.get("resource_owner") or ""),
            external_ref=str(ledger.get("external_ref") or ""),
            memory_scope=binding.memory_scope,
            foreground=False,
        )

    async def _authorize_values(
        self,
        *,
        resource_owner: str,
        external_ref: str,
        memory_scope: str,
        foreground: bool,
    ) -> bool:
        del foreground
        if not is_valid_memory_scope(memory_scope) or not external_ref:
            return False
        authorizer = self._authorizers.get(resource_owner)
        if authorizer is None or not self.owner_is_running(resource_owner):
            return False
        try:
            return bool(
                await asyncio.wait_for(
                    authorizer.authorize(
                        external_ref=external_ref,
                        memory_scope=memory_scope,
                    ),
                    timeout=8,
                )
            )
        except Exception:
            logger.warning("memory scope authorize failed", exc_info=True)
            return False

    async def _tool_binding(self) -> tuple[MemoryBinding, MemoryProvider, Any]:
        context = get_session_context() or {}
        session = _SessionView(context)
        invocation_context = context.get("invocation_context") or {}
        if not isinstance(invocation_context, Mapping):
            invocation_context = {}
        if not self.running_providers():
            raise MemoryUnavailableError("memory provider unavailable")
        binding = await self._binding_for_session(
            session,
            invocation_context=invocation_context,
            require_scope=True,
            providers=self.running_providers(),
        )
        if binding is None:
            raise MemoryUnavailableError("memory binding unavailable")
        if not await self._authorize(session, binding, foreground=True):
            raise MemoryUnavailableError("memory scope unauthorized")
        provider = self.running_providers().get(binding.provider_id)
        if provider is None:
            raise MemoryUnavailableError("memory provider unavailable")
        return binding, provider, session


class _SessionView:
    def __init__(self, context: Mapping[str, Any]):
        self.session_id = str(context.get("session_id") or "")
        self.agent_type = str(context.get("agent_type") or "")
        self.session_type = str(context.get("session_type") or "") or (
            "sub" if context.get("resource_owner") else "main"
        )
        self.resource_owner = str(context.get("resource_owner") or "")
        self.external_ref = str(context.get("external_ref") or "")
        self.lifecycle_profile = str(context.get("lifecycle_profile") or "")
        self.record: list[Any] = []
        self.lc_messages: list[Any] = []
        self.pending_tool_resolutions = {}
        self.status = "running"
