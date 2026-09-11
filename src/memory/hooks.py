"""Small session integration points. Keep AgentSession free of memory logic."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from src.memory.service import get_memory_runtime

logger = logging.getLogger(__name__)


async def prepare_turn_model_context(
    *,
    session: Any,
    content: str,
    source: str,
    invocation_context: Mapping[str, str] | None,
    model_context: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    runtime = get_memory_runtime()
    if runtime is None:
        return model_context
    try:
        return await runtime.prepare_turn_model_context(
            session=session,
            content=content,
            source=source,
            invocation_context=invocation_context,
            model_context=model_context,
        )
    except Exception:
        logger.debug("memory recall hook failed open", exc_info=True)
        return model_context


async def record_completed_invocation(
    *,
    session: Any,
    content: str,
    source: str,
    append_input: bool,
    invocation_context: Mapping[str, str] | None,
    model_context: Mapping[str, Any] | None,
) -> None:
    runtime = get_memory_runtime()
    if runtime is None:
        return
    try:
        await runtime.record_completed_invocation(
            session=session,
            content=content,
            source=source,
            append_input=append_input,
            invocation_context=invocation_context,
            model_context=model_context,
        )
    except Exception:
        logger.debug("memory snapshot hook failed open", exc_info=True)


async def note_session_end(session: Any) -> None:
    runtime = get_memory_runtime()
    if runtime is None:
        return
    try:
        await runtime.mark_session_closed(session)
    except Exception:
        logger.debug("memory session-end hook failed open", exc_info=True)
