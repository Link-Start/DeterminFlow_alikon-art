"""Durable accepted-batch contract for external tool result resume."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

PHASE_FILLED = "filled"
PHASE_COMPLETED = "completed"
PHASE_AWAITING = "awaiting"
PHASE_UNSAFE = "unsafe"
_VALID_PHASES = {PHASE_FILLED, PHASE_COMPLETED, PHASE_AWAITING, PHASE_UNSAFE}

_EXACT_SET_ERROR = "工具结果必须与全部待解析 tool_call_id 精确匹配"
_CONTENT_ERROR = "工具结果内容与已接受批次不一致"
_UNSAFE_ERROR = "已出现无法证明安全的工具副作用，不能恢复本批外部工具结果"


@dataclass(frozen=True)
class ResumeDecision:
    action: str
    contents: dict[str, str]
    remaining_rounds: int | None = None
    final_result: str | None = None
    error: Exception | None = None


def canonical_resolution_content(value: Any) -> str:
    """Stable JSON for exact resolution matching. Does not keep call grants."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def canonical_resolution_map(resolutions: Mapping[str, Any]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for raw_id, value in resolutions.items():
        tool_call_id = str(raw_id or "")
        if not tool_call_id:
            raise ValueError(_EXACT_SET_ERROR)
        contents[tool_call_id] = canonical_resolution_content(value)
    return contents


def contents_match(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return json.loads(left) == json.loads(right)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def parse_accepted_tool_resume(raw: Any) -> dict[str, Any] | None:
    """Restore a persisted accepted batch, or None if the payload is unusable."""
    if not isinstance(raw, dict):
        return None
    raw_ids = raw.get("tool_call_ids")
    raw_contents = raw.get("contents")
    phase = raw.get("phase")
    if (
        not isinstance(raw_ids, list)
        or not raw_ids
        or not isinstance(raw_contents, dict)
        or phase not in _VALID_PHASES
    ):
        return None
    tool_call_ids: list[str] = []
    for item in raw_ids:
        if not isinstance(item, str) or not item:
            return None
        tool_call_ids.append(item)
    if len(set(tool_call_ids)) != len(tool_call_ids):
        return None
    contents: dict[str, str] = {}
    for tool_call_id in tool_call_ids:
        value = raw_contents.get(tool_call_id)
        if not isinstance(value, str):
            return None
        contents[tool_call_id] = value
    if set(raw_contents) != set(tool_call_ids):
        return None
    remaining = raw.get("remaining_rounds")
    if remaining is not None and not isinstance(remaining, int):
        return None
    names = _string_map(raw.get("names"), tool_call_ids)
    run_ids = _string_map(raw.get("run_ids"), tool_call_ids)
    if names is None or run_ids is None:
        return None
    parsed: dict[str, Any] = {
        "tool_call_ids": tool_call_ids,
        "contents": contents,
        "names": names,
        "run_ids": run_ids,
        "remaining_rounds": remaining,
        "phase": phase,
    }
    final_result = raw.get("final_result")
    if isinstance(final_result, str):
        parsed["final_result"] = final_result
    return parsed


def build_accepted_tool_resume(
    *,
    contents: Mapping[str, str],
    names: Mapping[str, str],
    run_ids: Mapping[str, str],
    remaining_rounds: int | None,
    phase: str = PHASE_FILLED,
    final_result: str | None = None,
) -> dict[str, Any]:
    tool_call_ids = sorted(contents)
    payload: dict[str, Any] = {
        "tool_call_ids": tool_call_ids,
        "contents": {tool_call_id: contents[tool_call_id] for tool_call_id in tool_call_ids},
        "names": {
            tool_call_id: str(names.get(tool_call_id) or "unknown")
            for tool_call_id in tool_call_ids
        },
        "run_ids": {
            tool_call_id: str(run_ids.get(tool_call_id) or tool_call_id)
            for tool_call_id in tool_call_ids
        },
        "remaining_rounds": remaining_rounds,
        "phase": phase,
    }
    if final_result is not None:
        payload["final_result"] = final_result
    return payload


def existing_tool_contents(session: Any) -> dict[str, str]:
    contents: dict[str, str] = {}
    for message in getattr(session, "record", None) or []:
        if not isinstance(message, dict) or message.get("type") != "tool":
            continue
        tool_call_id = str(message.get("tool_call_id") or "")
        if tool_call_id:
            contents[tool_call_id] = str(message.get("content") or "")
    for message in getattr(session, "lc_messages", None) or []:
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        if not tool_call_id or type(message).__name__ != "ToolMessage":
            continue
        content = getattr(message, "content", "")
        contents[tool_call_id] = content if isinstance(content, str) else str(content)
    return contents


def is_recoverable_accepted_resume(session: Any) -> bool:
    accepted = parse_accepted_tool_resume(getattr(session, "accepted_tool_resume", None))
    return accepted is not None and accepted.get("phase") != PHASE_UNSAFE


def blocks_new_user_message(session: Any) -> bool:
    if getattr(session, "pending_tool_resolutions", None):
        return True
    accepted = parse_accepted_tool_resume(getattr(session, "accepted_tool_resume", None))
    return accepted is not None and accepted.get("phase") != PHASE_COMPLETED


def classify_resume_request(
    *,
    pending_ids: set[str],
    accepted: Mapping[str, Any] | None,
    existing_contents: Mapping[str, str],
    resolutions: Mapping[str, Any],
) -> ResumeDecision:
    try:
        contents = canonical_resolution_map(resolutions)
    except (TypeError, ValueError) as error:
        return ResumeDecision(
            action="reject",
            contents={},
            error=error if isinstance(error, ValueError) else ValueError(_EXACT_SET_ERROR),
        )
    incoming_ids = set(contents)

    if accepted is not None and accepted.get("phase") == PHASE_UNSAFE:
        return _reject(_UNSAFE_ERROR, contents, error_type=RuntimeError)

    if (
        pending_ids
        and accepted is not None
        and accepted.get("phase") == PHASE_AWAITING
        and incoming_ids == set(accepted.get("tool_call_ids") or [])
    ):
        if not _contents_equal(accepted.get("contents") or {}, contents):
            return _reject(_CONTENT_ERROR, contents)
        return ResumeDecision(action="replay_pending", contents=contents)

    if pending_ids:
        if incoming_ids != pending_ids:
            return _reject(_EXACT_SET_ERROR, contents)
        if accepted is not None and set(accepted.get("tool_call_ids") or []) == incoming_ids:
            if not _contents_equal(accepted.get("contents") or {}, contents):
                return _reject(_CONTENT_ERROR, contents)
        for tool_call_id, content in contents.items():
            existing = existing_contents.get(tool_call_id)
            if existing is not None and not contents_match(existing, content):
                return _reject(_CONTENT_ERROR, contents)
        remaining = accepted.get("remaining_rounds") if accepted is not None else None
        return ResumeDecision(
            action="apply",
            contents=contents,
            remaining_rounds=remaining if isinstance(remaining, int) else None,
        )

    if accepted is None:
        return _reject(_EXACT_SET_ERROR, contents)

    accepted_ids = set(accepted.get("tool_call_ids") or [])
    if incoming_ids != accepted_ids:
        return _reject(_EXACT_SET_ERROR, contents)
    if not _contents_equal(accepted.get("contents") or {}, contents):
        return _reject(_CONTENT_ERROR, contents)

    phase = accepted.get("phase")
    if phase == PHASE_UNSAFE:
        return _reject(_UNSAFE_ERROR, contents, error_type=RuntimeError)
    if phase == PHASE_COMPLETED:
        final_result = accepted.get("final_result")
        if isinstance(final_result, str):
            return ResumeDecision(
                action="replay",
                contents=contents,
                remaining_rounds=accepted.get("remaining_rounds")
                if isinstance(accepted.get("remaining_rounds"), int)
                else None,
                final_result=final_result,
            )
        return _reject(_UNSAFE_ERROR, contents, error_type=RuntimeError)
    if phase == PHASE_FILLED:
        return ResumeDecision(
            action="continue",
            contents=contents,
            remaining_rounds=accepted.get("remaining_rounds")
            if isinstance(accepted.get("remaining_rounds"), int)
            else None,
        )
    return _reject(_UNSAFE_ERROR, contents, error_type=RuntimeError)


def _contents_equal(left: Mapping[str, Any], right: Mapping[str, str]) -> bool:
    if set(left) != set(right):
        return False
    return all(
        isinstance(left[key], str) and contents_match(left[key], right[key])
        for key in right
    )


def _string_map(raw: Any, tool_call_ids: list[str]) -> dict[str, str] | None:
    if raw is None:
        return {tool_call_id: tool_call_id for tool_call_id in tool_call_ids}
    if not isinstance(raw, dict):
        return None
    mapped: dict[str, str] = {}
    for tool_call_id in tool_call_ids:
        value = raw.get(tool_call_id)
        mapped[tool_call_id] = str(value) if isinstance(value, str) and value else tool_call_id
    return mapped


def _reject(
    message: str,
    contents: dict[str, str],
    *,
    error_type: type[Exception] = ValueError,
) -> ResumeDecision:
    return ResumeDecision(action="reject", contents=contents, error=error_type(message))
