"""Structured product context for user turns.

The persisted message content remains the display-authoritative user text.  The
model-only context is stored separately and composed only when a HumanMessage
is built for inference.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

MAX_MODEL_CONTEXT_BYTES = 64 * 1024


def normalize_model_context(
    context: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return an immutable JSON snapshot while preserving explicit nulls."""
    if context is None:
        return None
    if not isinstance(context, Mapping):
        raise ValueError("model_context 必须是 JSON 对象")
    try:
        encoded = json.dumps(
            dict(context),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("model_context 必须可序列化为 JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_MODEL_CONTEXT_BYTES:
        raise ValueError("model_context 超过 64 KiB 上限")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError("model_context 必须是 JSON 对象")
    return decoded


def compose_user_model_content(
    content: str,
    *,
    model_context: Mapping[str, Any] | None = None,
    injection_meta: list[dict[str, Any]] | None = None,
) -> str:
    """Compose model input without changing the display-authoritative content."""
    normalized_context = normalize_model_context(model_context)
    # Routing markers stay in persisted metadata for scope-change cleanup.
    # They are not part of the reference material sent to the model.
    if normalized_context is not None:
        memory = normalized_context.get("long_term_memory")
        if isinstance(memory, dict):
            memory.pop("bank_id", None)
            memory.pop("memory_scope", None)
        workspace = normalized_context.get("workspace")
        if isinstance(workspace, dict):
            workspace.pop("_binding", None)
    injections = [
        str(item.get("content", ""))
        for item in (injection_meta or [])
        if str(item.get("content", ""))
    ]
    if not injections and normalized_context is None:
        return content

    sections: list[str] = []
    if injections:
        sections.append(
            "<SYSTEM_INJECTION>\n"
            + "\n".join(injections)
            + "\n</SYSTEM_INJECTION>"
        )
    if normalized_context is not None:
        sections.append(
            "<PRODUCT_CONTEXT>\n"
            + json.dumps(
                normalized_context,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            )
            + "\n</PRODUCT_CONTEXT>"
        )
    sections.append(f"<USER_MESSAGE>\n{content}\n</USER_MESSAGE>")
    return "\n".join(sections)
