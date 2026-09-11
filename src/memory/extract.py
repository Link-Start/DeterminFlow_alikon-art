"""Freeze extracted facts, then retain; only confirmed writes move the watermark."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from src.memory.contracts import (
    RETAIN_CONFIRMED,
    ExtractParseError,
    MemoryExtractRequest,
    MemoryFact,
    MemoryProvider,
    MemoryRetainRequest,
    MemoryRetainResult,
    MemoryUnavailableError,
)
from src.memory.extract_output import (
    FORMAT_CORRECTION_LIMIT,
    build_extract_format_correction_prompt,
    extract_response_payload,
    is_extract_format_error,
    merge_extract_model_params,
    parse_extract_json_object,
)
from src.memory.store import utc_now_iso
from src.memory.turns import bound_extract_turns

logger = logging.getLogger(__name__)
LlmFactory = Callable[[str, dict | None], Any]


def fact_document_id(
    *,
    partition: str,
    session_id: str,
    turn_id: str,
    index: int,
    text: str,
) -> str:
    digest = hashlib.sha256(
        f"{partition}\n{session_id}\n{turn_id}\n{index}\n{text}".encode("utf-8")
    ).hexdigest()
    return f"dfm-{digest}"


def parse_extract_facts(
    payload: object,
    *,
    turns: Sequence[Mapping[str, Any]],
) -> list[MemoryFact]:
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 128_000:
        raise ExtractParseError("extract output exceeds byte budget")
    document = _parse_json_object(payload)
    if "facts" not in document:
        raise ExtractParseError("extract JSON missing facts")
    raw_facts = document.get("facts")
    if not isinstance(raw_facts, list):
        raise ExtractParseError("extract facts is not a list")
    if len(raw_facts) > 64:
        raise ExtractParseError("extract output exceeds fact budget")
    if not raw_facts:
        return []
    known_ids: set[str] = set()
    message_to_turn: dict[str, str] = {}
    turn_by_id: dict[str, Mapping[str, Any]] = {}
    for turn in turns:
        turn_id = str(turn.get("turn_id") or "")
        if turn_id:
            turn_by_id[turn_id] = turn
        for message in turn.get("messages") or []:
            if not isinstance(message, Mapping):
                continue
            message_id = str(message.get("id") or "").strip()
            if not message_id:
                continue
            known_ids.add(message_id)
            if turn_id:
                message_to_turn[message_id] = turn_id
    facts: list[MemoryFact] = []
    seen: set[str] = set()
    for item in raw_facts:
        if not isinstance(item, Mapping):
            raise ExtractParseError("extract fact is not an object")
        kind = str(item.get("kind") or "fact").strip() or "fact"
        if kind == "preference":
            continue
        raw_text = item.get("text")
        if not isinstance(raw_text, str):
            raise ExtractParseError("extract fact text is not a string")
        text = raw_text.strip()
        if not text:
            raise ExtractParseError("extract fact text is empty")
        if text in seen:
            continue
        raw_ids = item.get("source_message_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ExtractParseError("extract fact source_message_ids missing")
        source_ids: list[str] = []
        for raw_id in raw_ids:
            source_id = str(raw_id).strip()
            if not source_id or source_id not in known_ids:
                raise ExtractParseError("extract fact source_message_ids are unknown")
            source_ids.append(source_id)
        expected_turns = {
            message_to_turn.get(source_id, "") for source_id in source_ids
        }
        expected_turns.discard("")
        if len(expected_turns) != 1:
            raise ExtractParseError("extract fact sources do not map to one turn")
        expected_turn_id = expected_turns.pop()
        turn_id = str(item.get("turn_id") or "").strip()
        if turn_id and turn_id != expected_turn_id:
            raise ExtractParseError("extract fact turn_id does not match sources")
        turn_id = expected_turn_id
        source_turn = turn_by_id.get(turn_id) or {}
        timestamp = str(source_turn.get("started_at") or "").strip()
        if not timestamp:
            raise ExtractParseError("extract source turn timestamp missing")
        facts.append(
            MemoryFact(
                text=text,
                source_message_ids=tuple(source_ids),
                source_timestamp=timestamp,
                turn_id=turn_id,
                kind=kind,
            )
        )
        seen.add(text)
    return facts


def validate_extracted_facts(
    facts: Sequence[MemoryFact],
    turns: Sequence[Mapping[str, Any]],
) -> list[MemoryFact]:
    if not facts:
        return []
    payload = {
        "facts": [
            {
                "text": fact.text,
                "source_message_ids": list(fact.source_message_ids),
                "source_timestamp": fact.source_timestamp,
                "turn_id": fact.turn_id,
                "kind": fact.kind,
            }
            for fact in facts
        ]
    }
    return parse_extract_facts(payload, turns=turns)


def serialize_facts(facts: Sequence[MemoryFact]) -> list[dict[str, object]]:
    return [
        {
            "text": fact.text,
            "source_message_ids": list(fact.source_message_ids),
            "source_timestamp": fact.source_timestamp,
            "turn_id": fact.turn_id,
            "kind": fact.kind,
        }
        for fact in facts
    ]


def facts_from_frozen(raw: object) -> list[MemoryFact]:
    if not isinstance(raw, list):
        return []
    facts: list[MemoryFact] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        text = str(item.get("text") or "").strip()
        turn_id = str(item.get("turn_id") or "").strip()
        if not text or not turn_id:
            continue
        source_ids = tuple(
            str(message_id)
            for message_id in (item.get("source_message_ids") or [])
            if str(message_id).strip()
        )
        facts.append(
            MemoryFact(
                text=text,
                source_message_ids=source_ids,
                source_timestamp=str(item.get("source_timestamp") or utc_now_iso()),
                turn_id=turn_id,
                kind=str(item.get("kind") or "fact"),
            )
        )
    return facts


def _parse_json_object(payload: object) -> dict[str, Any]:
    return parse_extract_json_object(payload)


def _timestamp(value: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExtractParseError("extract source timestamp is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def retain_frozen_facts(
    *,
    provider: MemoryProvider,
    session_id: str,
    partition: str,
    bank_id: str,
    facts: Sequence[MemoryFact],
    before_retain: Callable[[], Awaitable[None]] | None = None,
    timeout_seconds: float = 60,
) -> list[MemoryRetainResult]:
    results: list[MemoryRetainResult] = []
    for index, fact in enumerate(facts):
        document_id = fact_document_id(
            partition=partition,
            session_id=session_id,
            turn_id=fact.turn_id,
            index=index,
            text=fact.text,
        )
        metadata = {
            "session_id": session_id,
            "turn_id": fact.turn_id,
            "source_message_ids": ",".join(fact.source_message_ids),
            "kind": fact.kind,
        }
        if before_retain is not None:
            await before_retain()
        result = await asyncio.wait_for(
            provider.retain(
                MemoryRetainRequest(
                    content=fact.text,
                    bank_id=bank_id,
                    document_id=document_id,
                    timestamp=_timestamp(fact.source_timestamp).isoformat(),
                    metadata=metadata,
                    tags=("session_extract", fact.kind),
                    context="frozen session extract",
                    update_mode="append",
                    retain_async=False,
                )
            ),
            timeout=timeout_seconds,
        )
        results.append(result)
    return results


def all_confirmed(results: Sequence[MemoryRetainResult]) -> bool:
    return bool(results) and all(item.status == RETAIN_CONFIRMED for item in results)


class DefaultExtractRunner:
    """One-shot extract using the host PromptBuilder and Core LLM client."""

    def __init__(
        self,
        *,
        prompt_builder: Any | None = None,
        llm_factory: LlmFactory | None = None,
    ):
        self._prompt_builder = prompt_builder
        self._llm_factory = llm_factory

    async def extract(self, request: MemoryExtractRequest) -> Sequence[MemoryFact]:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        from src.agent.definition import get_agent_definition

        if self._prompt_builder is None:
            raise MemoryUnavailableError("memory extract PromptBuilder 未注入")
        agent_def = get_agent_definition(request.extract_agent_type)
        if agent_def is None:
            raise RuntimeError(
                f"memory extract Agent 不存在: {request.extract_agent_type}"
            )
        system_prompt = self._prompt_builder.build(
            request.extract_agent_type,
            include_skills=False,
            include_rules=False,
        )
        bounded_turns = bound_extract_turns(
            request.turns,
            max_turns=max(len(request.turns), 1),
        )
        user_payload = json.dumps(
            {
                "session_id": request.session_id,
                "turns": bounded_turns,
            },
            ensure_ascii=False,
        )
        llm_factory = self._llm_factory or _core_llm_factory
        model_params = merge_extract_model_params(
            getattr(agent_def, "model_params", None)
        )
        # The Core provider adapter decides which protocol supports response_format.
        llm = llm_factory(request.model_override or agent_def.model or "", model_params)
        messages: list[Any] = [
            SystemMessage(content=system_prompt + "\n\n输出约束：只输出一个 JSON 对象，"
                          "顶层 facts 必须为数组；无可保留事实时输出 {\"facts\":[]}。"
                          "不要输出思考独白、Markdown 或额外文字。"),
            HumanMessage(content=user_payload),
        ]
        deadline = asyncio.get_running_loop().time() + request.timeout_seconds
        payload = await self._invoke_llm(llm, messages, deadline)
        last_error: ExtractParseError | None = None
        for attempt in range(FORMAT_CORRECTION_LIMIT + 1):
            try:
                return parse_extract_facts(payload, turns=bounded_turns)
            except ExtractParseError as exc:
                last_error = exc
                if (
                    not is_extract_format_error(exc)
                    or attempt >= FORMAT_CORRECTION_LIMIT
                ):
                    raise
                previous = (
                    payload
                    if isinstance(payload, str)
                    else json.dumps(payload, ensure_ascii=False)
                )
                messages = [
                    *messages,
                    AIMessage(content=previous),
                    HumanMessage(content=build_extract_format_correction_prompt(exc)),
                ]
                payload = await self._invoke_llm(
                    llm, messages, deadline
                )
        raise last_error or ExtractParseError("extract output is not JSON")

    async def _invoke_llm(
        self,
        llm: Any,
        messages: Sequence[Any],
        deadline: float,
    ) -> object:
        response = await asyncio.wait_for(
            llm.ainvoke(list(messages)),
            timeout=max(deadline - asyncio.get_running_loop().time(), 0),
        )
        return extract_response_payload(response)


def _core_llm_factory(model_override: str, model_params: dict | None) -> Any:
    from src.core.llm_client import create_startup_llm

    return create_startup_llm(
        model_override=model_override or None,
        streaming=False,
        model_params=model_params,
    )
