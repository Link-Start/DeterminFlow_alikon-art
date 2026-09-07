"""Safe validation feedback and turn-local recovery for tool calls."""

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolInvocationError
from pydantic import ValidationError


def tool_error_content(code: str, message: str, **details: Any) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message, **details}},
        ensure_ascii=False,
    )


def _validation_error_details(
    error: ValidationError | ToolInvocationError,
) -> list[dict[str, Any]]:
    if isinstance(error, ToolInvocationError):
        if error.filtered_errors is not None:
            return list(error.filtered_errors)
        source = error.source
        if isinstance(source, ValidationError):
            return list(source.errors())
        raise TypeError("ToolInvocationError source is not a ValidationError")
    if isinstance(error, ValidationError):
        return list(error.errors())
    raise TypeError("validation feedback requires a validation error")


def validation_error_content(error: ValidationError | ToolInvocationError) -> str:
    """Never echo input values, custom validator messages, or injected arguments."""
    fields = []
    for detail in _validation_error_details(error)[:12]:
        field = ".".join(str(part) for part in detail.get("loc", ()))[:120]
        item = {"field": field, "rule": detail.get("type", "invalid")}
        # Pydantic's numeric constraints are safe and actionable; other ctx may
        # contain user input or an arbitrary exception from a custom validator.
        for key in ("ge", "gt", "le", "lt", "multiple_of", "min_length", "max_length"):
            value = (detail.get("ctx") or {}).get(key)
            if type(value) in (int, float):
                item[key] = value
        fields.append(item)
    return tool_error_content(
        "tool_arguments_invalid",
        "工具参数未通过校验。请按字段规则修正参数后重试；不要重复相同的无效调用。",
        fields=fields,
        retryable=True,
    )


def handle_tool_validation_error(error: Exception) -> str:
    """Return field-safe validation feedback; re-raise runtime and control errors.

    LangGraph's awrap_tool_call wrapper catch-all delivers any execute()
    exception to this handler. Only invocation validation becomes model
    feedback; runtime errors keep their original propagate / safe-fail
    semantics and must not be classified as argument validation.
    """
    if isinstance(error, ToolInvocationError):
        return validation_error_content(error)
    raise error


def repeats_invalid_call(messages: list, calls: list[dict]) -> bool:
    """Recognize only this turn's failed validation, never earlier/business errors."""
    previous_calls: dict[str, dict] = {}
    failed: list[dict] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            previous_calls.clear()
            failed.clear()
        elif isinstance(message, AIMessage):
            previous_calls.update({call["id"]: call for call in message.tool_calls})
        elif isinstance(message, ToolMessage) and message.status == "error":
            try:
                payload = json.loads(message.content)
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            error = payload.get("error")
            if isinstance(error, dict) and error.get("code") == "tool_arguments_invalid":
                call = previous_calls.get(message.tool_call_id)
                if call:
                    failed.append(call)
    def signature(call: dict) -> tuple[str, str]:
        return call.get("name", ""), json.dumps(call.get("args"), sort_keys=True)

    failed_signatures = {signature(call) for call in failed}
    return any(signature(call) in failed_signatures for call in calls)


def repeated_invalid_tool_result(messages: list, call: dict) -> ToolMessage | None:
    """Reject only the repeated call; independent calls keep their normal lifecycle."""
    if not repeats_invalid_call(messages, [call]):
        return None
    return ToolMessage(
        content=tool_error_content(
            "tool_arguments_repeated",
            "该调用重复使用了未通过校验的参数，未再次执行。"
            "不要重复相同参数；其他独立调用仍按各自结果处理。根据已有结果回答，明确未完成的部分。",
            retryable=False,
        ),
        tool_call_id=call["id"], name=call["name"], status="error",
    )


def last_batch_repeated_invalid(messages: list) -> bool:
    """An entirely blocked batch gets one answer-only round instead of spinning."""
    results: dict[str, ToolMessage] = {}
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            results[message.tool_call_id] = message
            continue
        if not isinstance(message, AIMessage) or not message.tool_calls:
            return False
        if {call["id"] for call in message.tool_calls} != set(results):
            return False
        for result in results.values():
            if result.status != "error":
                return False
            try:
                payload = json.loads(result.content)
            except (TypeError, ValueError):
                return False
            if not isinstance(payload, dict):
                return False
            error = payload.get("error")
            if not isinstance(error, dict) or error.get("code") != "tool_arguments_repeated":
                return False
        return True
    return False


def stopped_tool_response(response: AIMessage, code: str) -> list:
    """Preserve the model call and pair every skipped call with a truthful result."""
    reason = (
        "连续出现相同参数错误，后续操作未执行。已完成的结果保留。"
        if code == "tool_recovery_stopped"
        else "本轮工具调用已达上限，后续查询或操作未执行。您可以继续发送消息。"
    )
    return [
        response,
        *[
            ToolMessage(
                content=tool_error_content(code, reason, retryable=False),
                tool_call_id=call["id"], name=call["name"], status="error",
            )
            for call in response.tool_calls
        ],
        AIMessage(content=reason),
    ]
