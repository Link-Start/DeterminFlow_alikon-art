"""Complete-turn snapshots and skip rules for memory extract/recall."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.memory.contracts import (
    SKIP_CONFIRMATION,
    SKIP_NON_HUMAN,
    SKIP_OBSERVATION,
    SKIP_RESUME,
)

_CONFIRMATION = re.compile(
    r"^(好的?|好|确认|是的?|对|嗯+|行|可以|收到|继续|ok|okay|yes|yep|yeah|sure|got it)"
    r"[。.!！]?$",
    re.IGNORECASE,
)
_EXTRACT_ROLES = frozenset({"user", "assistant", "tool"})
MAX_EXTRACT_BATCH_BYTES = 128_000


def is_pure_confirmation(content: str) -> bool:
    text = str(content or "").strip()
    if not text or len(text) > 16:
        return False
    return _CONFIRMATION.fullmatch(text) is not None


def is_action_observation(model_context: Mapping[str, Any] | None) -> bool:
    if not isinstance(model_context, Mapping):
        return False
    turn_kind = str(model_context.get("turn_kind") or "").strip()
    if turn_kind == "action_observation":
        return True
    observation = model_context.get("confirmed_action_observation")
    return bool(observation)


def skip_reason_for_turn(
    *,
    content: str,
    source: str,
    append_input: bool,
    model_context: Mapping[str, Any] | None,
) -> str | None:
    if not append_input:
        return SKIP_RESUME
    if source != "human":
        return SKIP_NON_HUMAN
    if is_action_observation(model_context):
        return SKIP_OBSERVATION
    if is_pure_confirmation(content):
        return SKIP_CONFIRMATION
    return None


def _message_id(message: Mapping[str, Any]) -> str:
    return str(message.get("id") or "").strip()


def _is_human_user(message: Mapping[str, Any]) -> bool:
    if str(message.get("type") or "") != "user":
        return False
    source = str(message.get("source") or "human")
    return source == "human"


def tool_pairs_complete(messages: Sequence[Mapping[str, Any]]) -> bool:
    pending: set[str] = set()
    for message in messages:
        role = str(message.get("type") or "")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                if not isinstance(call, Mapping):
                    continue
                call_id = str(call.get("id") or "").strip()
                if call_id:
                    pending.add(call_id)
        elif role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "").strip()
            pending.discard(tool_call_id)
    return not pending


def sanitize_extract_messages(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cleaned = []
    for message in messages:
        role = str(message.get("type") or "")
        if role not in _EXTRACT_ROLES:
            continue
        item = {
            "id": _message_id(message),
            "type": role,
            "content": str(message.get("content") or ""),
        }
        if message.get("name"):
            item["name"] = message["name"]
        if role == "user":
            item["source"] = str(message.get("source") or "human")
        if role == "assistant" and message.get("tool_calls"):
            item["tool_calls"] = message["tool_calls"]
        if role == "tool" and message.get("tool_call_id"):
            item["tool_call_id"] = message["tool_call_id"]
        cleaned.append(item)
    return cleaned


def select_extract_batch(
    turns, *, max_turns: int, max_bytes: int = MAX_EXTRACT_BATCH_BYTES
):
    selected = []
    for turn in list(turns)[: max(1, int(max_turns))]:
        candidate = [*selected, dict(turn)]
        size = len(json.dumps(candidate, ensure_ascii=False).encode("utf-8"))
        if selected and size > max_bytes:
            break
        selected = candidate
    return selected


def bound_extract_turns(
    turns, *, max_turns: int, max_bytes: int = MAX_EXTRACT_BATCH_BYTES
):
    from src.memory.contracts import ExtractParseError

    bounded = [
        dict(turn, messages=sanitize_extract_messages(turn.get("messages") or []))
        for turn in list(turns)[: max(1, int(max_turns))]
    ]
    if len(json.dumps(bounded, ensure_ascii=False).encode("utf-8")) > max_bytes:
        raise ExtractParseError(
            "complete memory turn exceeds extract input budget; progress retained"
        )
    return bounded


def turn_token_count(messages: Sequence[Mapping[str, Any]]) -> int:
    from src.core.utils import estimate_tokens

    total = 0
    for message in messages:
        total += estimate_tokens(str(message.get("content") or ""))
        if message.get("tool_calls"):
            total += estimate_tokens(json.dumps(message["tool_calls"], ensure_ascii=False))
    return total


def snapshot_token_count(turn: Mapping[str, Any]) -> int:
    stored = turn.get("estimated_tokens")
    if isinstance(stored, int) and not isinstance(stored, bool) and stored >= 0:
        return stored
    # Old snapshots still contain full messages; never convert char_count by ratio.
    return turn_token_count(turn.get("messages") or [])


def build_turn_id(session_id: str, first_id: str, last_id: str) -> str:
    digest = hashlib.sha256(
        f"{session_id}:{first_id}:{last_id}".encode("utf-8")
    ).hexdigest()
    return digest[:32]


def partition_key(memory_scope: str, bank_id: str) -> str:
    scope = str(memory_scope or "").strip()
    if scope:
        return scope
    return f"local:{bank_id}"


def turn_partition(turn: Mapping[str, Any]) -> str:
    stored = str(turn.get("partition") or "").strip()
    if stored:
        return stored
    return partition_key(
        str(turn.get("memory_scope") or ""),
        str(turn.get("bank_id") or ""),
    )


def latest_complete_turn(
    record: Sequence[Mapping[str, Any]],
    *,
    known_turn_ids: set[str],
    session_id: str,
    skip_reason: str | None,
    started_at: str,
    memory_scope: str,
    bank_id: str,
) -> dict[str, Any] | None:
    """Return the newest complete human turn that is not already snapshotted."""

    if not record:
        return None
    last_user_index = None
    for index in range(len(record) - 1, -1, -1):
        message = record[index]
        if isinstance(message, Mapping) and _is_human_user(message):
            last_user_index = index
            break
    if last_user_index is None:
        return None
    slice_messages = [
        message for message in record[last_user_index:] if isinstance(message, Mapping)
    ]
    if not tool_pairs_complete(slice_messages):
        return None
    first_id = _message_id(slice_messages[0])
    last_id = _message_id(slice_messages[-1])
    if not first_id or not last_id:
        return None
    turn_id = build_turn_id(session_id, first_id, last_id)
    if turn_id in known_turn_ids:
        return None
    extract_messages = sanitize_extract_messages(slice_messages)
    stored_skip = None if skip_reason == SKIP_RESUME else skip_reason
    return {
        "turn_id": turn_id,
        "first_message_id": first_id,
        "last_message_id": last_id,
        "started_at": started_at,
        "skip_reason": stored_skip,
        "memory_scope": memory_scope,
        "bank_id": bank_id,
        "partition": partition_key(memory_scope, bank_id),
        "estimated_tokens": turn_token_count(extract_messages),
        "messages": extract_messages,
    }


def extractable_turns(
    turns: Sequence[Mapping[str, Any]],
    *,
    watermark_turn_id: str,
    partition: str,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    matching = [
        dict(turn)
        for turn in turns
        if isinstance(turn, Mapping) and turn_partition(turn) == partition
    ]
    if not watermark_turn_id:
        return matching
    past_watermark = False
    found = False
    for turn in matching:
        turn_id = str(turn.get("turn_id") or "")
        if not past_watermark:
            if turn_id == watermark_turn_id:
                past_watermark = True
                found = True
            continue
        selected.append(turn)
    if watermark_turn_id and not found:
        return matching
    return selected


def encode_snapshot(turns: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps(list(turns), ensure_ascii=False, separators=(",", ":"))


def recent_raw_user_texts(
    record: Sequence[Mapping[str, Any]],
    *,
    exclude_text: str = "",
    max_turns: int = 3,
) -> list[str]:
    current = str(exclude_text or "").strip()
    collected: list[str] = []
    for message in reversed(list(record or [])):
        if not isinstance(message, Mapping) or not _is_human_user(message):
            continue
        text = str(message.get("content") or "").strip()
        if not text or text == current:
            continue
        collected.append(text)
        if len(collected) >= max(int(max_turns), 0):
            break
    collected.reverse()
    return collected
