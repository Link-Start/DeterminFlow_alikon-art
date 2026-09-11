"""Resolve whether a session/agent may use a registered memory provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.memory.contracts import (
    SCOPE_LOCAL,
    SCOPE_USER,
    MemoryBinding,
    MemoryProvider,
    MemoryRuntimePolicy,
)

_TRUE = frozenset({"1", "true", "yes", "on"})


def is_valid_memory_scope(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _option_flag(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _agent_options(
    agent_definition: Any,
    provider_id: str,
) -> Mapping[str, Any] | None:
    raw_options = getattr(agent_definition, "extension_options", None)
    options = _mapping(raw_options)
    if options is None:
        return None
    return _mapping(options.get(provider_id))


def _declared_scope(options: Mapping[str, Any]) -> str:
    scope = str(options.get("scope") or "").strip().lower()
    if scope in {SCOPE_LOCAL, SCOPE_USER}:
        return scope
    return ""


def _enabled(options: Mapping[str, Any]) -> bool | None:
    if "enabled" in options:
        return _option_flag(options.get("enabled"))
    nested = _mapping(options.get("recall"))
    if nested is not None and "enabled" in nested:
        return _option_flag(nested.get("enabled"))
    return None


def _is_local_main(session: Any) -> bool:
    session_type = str(getattr(session, "session_type", "") or "")
    resource_owner = str(getattr(session, "resource_owner", "") or "").strip()
    profile = str(getattr(session, "lifecycle_profile", "") or "")
    return (
        session_type == "main"
        and not resource_owner
        and profile != "detached_conversation"
    )


def _bank_id(provider: MemoryProvider, scope: str, memory_scope: str) -> str:
    bank_id = str(
        provider.bank_id_for(scope=scope, memory_scope=memory_scope) or ""
    ).strip()
    return bank_id


def resolve_memory_binding(
    *,
    session: Any,
    agent_definition: Any,
    providers: Mapping[str, MemoryProvider],
    memory_scope: str = "",
) -> MemoryBinding | None:
    """Return the single applicable provider binding, or None when memory is off."""

    if not providers:
        return None
    agent_type = str(
        getattr(agent_definition, "agent_type", None)
        or getattr(session, "agent_type", "")
        or ""
    )
    local_main = _is_local_main(session)
    matches: list[MemoryBinding] = []
    for provider_id, provider in providers.items():
        agent_policy = getattr(provider, "runtime_policy_for_agent", None)
        policy = (
            agent_policy(agent_type)
            if callable(agent_policy)
            else provider.runtime_policy()
        )
        if not isinstance(policy, MemoryRuntimePolicy):
            continue
        options = _agent_options(agent_definition, provider_id)
        if options is not None:
            enabled = _enabled(options)
            if enabled is not True:
                continue
            scope = _declared_scope(options)
            if not scope:
                continue
            if scope == SCOPE_LOCAL and not local_main:
                continue
        elif local_main and policy.local_main_enabled and agent_type == "main":
            scope = SCOPE_LOCAL
        else:
            continue
        scope_value = memory_scope.strip().lower() if scope == SCOPE_USER else ""
        if scope == SCOPE_USER and not is_valid_memory_scope(scope_value):
            continue
        bank_id = _bank_id(provider, scope, scope_value)
        if not bank_id:
            continue
        matches.append(
            MemoryBinding(
                provider_id=provider_id,
                scope=scope,  # type: ignore[arg-type]
                bank_id=bank_id,
                memory_scope=scope_value,
                policy=policy,
            )
        )
    if len(matches) != 1:
        return None
    return matches[0]


def invocation_memory_scope(invocation_context: Mapping[str, str] | None) -> str:
    if not invocation_context:
        return ""
    raw = invocation_context.get("memory_scope")
    text = str(raw or "").strip().lower()
    return text if is_valid_memory_scope(text) else ""
