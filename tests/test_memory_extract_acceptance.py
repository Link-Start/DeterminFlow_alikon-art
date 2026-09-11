"""Damaged output must not silently discard a batch as an empty success."""
import pytest
from src.memory.contracts import ExtractParseError
from src.memory.extract import parse_extract_facts


@pytest.mark.parametrize('payload', [
    '{"facts":[]} {"facts":[',
    '{"broken": true, "nested": {"facts":[]}',
    '<think>{"facts":[]}',
    '<think><think>inner</think>{"facts":[]}</think>',
    '{"facts": [], "facts": []}',
    '{"facts":[],}',
    'The result: {"facts":[]} {"broken": nope}',
])
def test_damaged_or_ambiguous_response_never_counts_as_empty_success(payload):
    with pytest.raises(ExtractParseError):
        parse_extract_facts(payload, turns=[])



def test_provider_reported_truncation_is_not_success_even_with_valid_json():
    from types import SimpleNamespace
    from src.memory.extract_output import extract_response_payload
    with pytest.raises(ExtractParseError, match="truncated"):
        extract_response_payload(SimpleNamespace(content='{"facts":[]}', response_metadata={"finish_reason": "length"}))


def test_wrapping_never_changes_quoted_fact_content():
    import json
    from src.memory.extract_output import parse_extract_json_object
    doc = {"facts": [{"text": "literal <think>quoted words</think> and ,} stay"}]}
    assert parse_extract_json_object(json.dumps(doc)) == doc
    assert parse_extract_json_object("Result:\n```json\n" + json.dumps(doc) + "\n```") == doc


def test_non_string_fact_is_not_coerced_into_memory():
    from tests.test_memory_extract import _turn
    with pytest.raises(ExtractParseError, match="not a string"):
        parse_extract_facts({"facts": [{"text": {"wrong": "shape"}, "source_message_ids": ["msg_00001"]}]}, turns=[_turn()])
