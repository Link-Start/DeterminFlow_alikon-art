"""Parse memory extract model output without treating invalid JSON as success."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from json import JSONDecodeError
from typing import Any

from src.memory.contracts import ExtractParseError

JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}
FORMAT_CORRECTION_LIMIT = 1
_VISIBLE_BLOCK_TYPES = frozenset({"text", "text_delta", "output_text"})
_REASONING_BLOCK_TYPES = frozenset({"thinking", "thinking_delta", "reasoning"})
_FORMAT_ERROR_MARKERS = (
    "extract output is empty",
    "extract output is not JSON",
    "extract output is truncated",
    "extract output is ambiguous",
    "extract JSON is not an object",
    "extract JSON missing facts",
    "extract facts is not a list",
)


def merge_extract_model_params(model_params: Mapping[str, Any] | None) -> dict[str, Any]:
    params = dict(model_params or {})
    if "response_format" not in params:
        params["response_format"] = dict(JSON_OBJECT_RESPONSE_FORMAT)
    return params


def extract_response_payload(response: object) -> object:
    metadata = getattr(response, "response_metadata", None) or {}
    if isinstance(metadata, Mapping) and (
        metadata.get("finish_reason") in {"length", "max_tokens"}
        or metadata.get("stop_reason") == "max_tokens"
    ):
        raise ExtractParseError("extract output is truncated")
    if isinstance(response, Mapping):
        return dict(response)
    content = getattr(response, "content", response)
    if isinstance(content, Mapping):
        return dict(content)
    return visible_content_text(content)


def visible_content_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        block_type, text = _block_fields(block)
        if block_type in _REASONING_BLOCK_TYPES:
            continue
        if block_type in _VISIBLE_BLOCK_TYPES and isinstance(text, str):
            parts.append(text)
    return "".join(parts)


def parse_extract_json_object(payload: object) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    text = visible_content_text(payload).strip()
    if not text:
        raise ExtractParseError("extract output is empty")
    return _load_extract_document(text)


def is_extract_format_error(error: BaseException) -> bool:
    message = str(error)
    return isinstance(error, ExtractParseError) and any(
        marker in message for marker in _FORMAT_ERROR_MARKERS
    )


def build_extract_format_correction_prompt(error: BaseException | str) -> str:
    return (
        "你的上一次输出不是合法的提炼 JSON。\n\n"
        f"错误：{error}\n\n"
        '请只返回一个 JSON 对象，格式必须是 {"facts": [...]}。\n'
        '没有可保留事实时返回 {"facts":[]}。\n'
        "不得输出 Markdown、思考过程、解释或额外文字。"
    )


def _block_fields(block: object) -> tuple[str, object]:
    if isinstance(block, Mapping):
        return str(block.get("type") or ""), block.get("text")
    return str(getattr(block, "type", "") or ""), getattr(block, "text", None)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExtractParseError("extract output is ambiguous: duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ExtractParseError("extract output is not JSON")


def _load_extract_document(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder(object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    try:
        loaded = decoder.decode(text)
    except JSONDecodeError:
        loaded = None
    else:
        if not isinstance(loaded, Mapping):
            raise ExtractParseError("extract JSON is not an object")
        return dict(loaded)

    # Strip only leading, closed reasoning blocks. Never edit tags or commas
    # inside a JSON string, or search inside a malformed outer JSON document.
    stripped = text.strip()
    while re.match(r"<(think|thinking|reasoning|thought)\b", stripped, re.IGNORECASE):
        match = re.match(
            r"<(think|thinking|reasoning|thought)\b[^>]*>.*?</\1>",
            stripped, flags=re.DOTALL | re.IGNORECASE,
        )
        if match is None:
            raise ExtractParseError("extract output is truncated")
        stripped = stripped[match.end():].strip()
    if not stripped:
        raise ExtractParseError("extract output is empty")
    opening = re.search(r"[\[{]", stripped)
    if opening is None:
        raise ExtractParseError("extract output is not JSON")
    start = opening.start()
    try:
        loaded, end = decoder.raw_decode(stripped, start)
    except JSONDecodeError as exc:
        kind = "truncated" if exc.pos >= len(stripped) - 1 or "Unterminated" in exc.msg else "not JSON"
        raise ExtractParseError(f"extract output is {kind}") from exc
    suffix = stripped[end:]
    if re.search(r"</?(think|thinking|reasoning|thought)\b", stripped[:start] + suffix, re.IGNORECASE):
        raise ExtractParseError("extract output is ambiguous")
    if re.search(r"[{}\[\]]", suffix):
        raise ExtractParseError("extract output is ambiguous")
    # Fences are allowed as wrappers, but an unfinished fence is not completion.
    if (stripped[:start].count("```") + suffix.count("```")) % 2:
        raise ExtractParseError("extract output is truncated")
    if not isinstance(loaded, Mapping):
        raise ExtractParseError("extract JSON is not an object")
    return dict(loaded)
