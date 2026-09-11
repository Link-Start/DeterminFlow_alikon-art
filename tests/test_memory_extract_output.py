from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.memory.contracts import ExtractParseError
from src.memory.extract_output import (
    JSON_OBJECT_RESPONSE_FORMAT,
    extract_response_payload,
    is_extract_format_error,
    merge_extract_model_params,
    parse_extract_json_object,
    visible_content_text,
)


def test_merge_extract_model_params_sets_json_object_without_clobbering() -> None:
    merged = merge_extract_model_params({"temperature": 0.1})
    assert merged["temperature"] == 0.1
    assert merged["response_format"] == JSON_OBJECT_RESPONSE_FORMAT
    explicit = merge_extract_model_params(
        {"response_format": {"type": "json_schema"}}
    )
    assert explicit["response_format"] == {"type": "json_schema"}


def test_core_adapter_owns_json_protocol_selection() -> None:
    from src.core.provider_adapters import build_provider_request
    params = merge_extract_model_params({"temperature": 0.1})
    assert build_provider_request("openai", params, {})["model_kwargs"]["response_format"] == JSON_OBJECT_RESPONSE_FORMAT
    assert "response_format" not in str(build_provider_request("anthropic", params, {}))
    assert merge_extract_model_params({"response_format": None})["response_format"] is None


def test_visible_content_text_skips_reasoning_blocks() -> None:
    content = [
        {"type": "thinking", "text": '{"facts": [{"text": "思考"}]}'},
        {"type": "reasoning", "text": "chain"},
        {"type": "output_text", "text": '{"facts": []}'},
    ]
    assert visible_content_text(content) == '{"facts": []}'
    assert extract_response_payload(SimpleNamespace(content=content)) == '{"facts": []}'


def test_parse_extract_json_object_accepts_empty_facts_and_wrappers() -> None:
    assert parse_extract_json_object({"facts": []}) == {"facts": []}
    with pytest.raises(ExtractParseError):
        parse_extract_json_object('{"facts": [],}')
    wrapped = (
        "<thinking>use {braces}</thinking>\n"
        "结果如下：\n"
        '```json\n{"facts": []}\n```'
    )
    assert parse_extract_json_object(wrapped) == {"facts": []}


def test_parse_extract_json_object_rejects_invalid_truncated_and_ambiguous() -> None:
    with pytest.raises(ExtractParseError, match="empty"):
        parse_extract_json_object("   ")
    with pytest.raises(ExtractParseError, match="not JSON"):
        parse_extract_json_object("没有可保留的事实")
    with pytest.raises(ExtractParseError, match="truncated"):
        parse_extract_json_object('{"facts": [{"text": "截断"')
    with pytest.raises(ExtractParseError, match="ambiguous"):
        parse_extract_json_object('{"facts": []}\n{"facts": [{"text": "x"}]}')
    with pytest.raises(ExtractParseError, match="not an object"):
        parse_extract_json_object("[1, 2]")
    with pytest.raises(ExtractParseError, match="empty"):
        parse_extract_json_object("<think>only reasoning { }</think>")


def test_parse_extract_json_object_rejects_multiple_objects() -> None:
    raw = '{"debug": true}\n{"facts": [{"text": "only"}]}'
    with pytest.raises(ExtractParseError, match="ambiguous"):
        parse_extract_json_object(raw)


def test_parse_extract_json_object_rejects_unmatched_outer_brace() -> None:
    raw = 'note { unfinished commentary\n{"facts": []}'
    with pytest.raises(ExtractParseError):
        parse_extract_json_object(raw)


def test_parse_extract_json_object_does_not_repair_truncated_facts_into_empty() -> None:
    with pytest.raises(ExtractParseError, match="truncated"):
        parse_extract_json_object('{"facts": [{"text": "almost"')


def test_is_extract_format_error_does_not_cover_source_validation() -> None:
    assert is_extract_format_error(ExtractParseError("extract output is not JSON"))
    assert is_extract_format_error(ExtractParseError("extract JSON missing facts"))
    assert not is_extract_format_error(
        ExtractParseError("extract fact source_message_ids are unknown")
    )
    assert not is_extract_format_error(ValueError("extract output is not JSON"))
