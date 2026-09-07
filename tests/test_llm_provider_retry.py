from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import Request, Response
from openai import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)

from src.core.llm_client import _wrap_llm_with_retry
from src.core.provider_errors import classify_provider_error_code


def _openai_status_error(
    cls,
    status_code: int,
    *,
    code: str | None = None,
    message: str = "upstream",
):
    request = Request("POST", "https://example.com/v1/chat/completions")
    body: dict[str, Any] = {"error": {"message": message}}
    if code is not None:
        body["error"]["code"] = code
    response = Response(status_code, request=request, json=body)
    return cls(
        f"Error code: {status_code} - {body}",
        response=response,
        body=body,
    )


class FakeRetryLlm:
    def __init__(self, error: Exception):
        self.error = error
        self.ainvoke_calls = 0
        self.astream_calls = 0

    async def ainvoke(self, _input, *args, **kwargs):
        self.ainvoke_calls += 1
        raise self.error

    async def astream(self, _input, *args, **kwargs):
        self.astream_calls += 1
        if False:  # pragma: no cover - keeps this an async generator
            yield None
        raise self.error


class FakePartialStreamLlm:
    def __init__(self, error: Exception):
        self.error = error
        self.ainvoke_calls = 0
        self.astream_calls = 0

    async def ainvoke(self, _input, *args, **kwargs):
        self.ainvoke_calls += 1
        config = args[0] if args else kwargs.get("config", {})
        for callback in config.get("callbacks", []):
            callback.on_llm_new_token("partial")
        raise self.error

    async def astream(self, _input, *args, **kwargs):
        self.astream_calls += 1
        yield "partial"
        raise self.error


_PERMANENT_CASES = [
    (
        _openai_status_error(
            PermissionDeniedError,
            403,
            code="insufficient_user_quota",
            message="quota secret-key-123",
        ),
        "provider_quota_exhausted",
    ),
    (
        _openai_status_error(AuthenticationError, 401, code="invalid_api_key"),
        "provider_auth_failed",
    ),
    (
        _openai_status_error(PermissionDeniedError, 403, code="forbidden"),
        "provider_permission_denied",
    ),
    (
        _openai_status_error(BadRequestError, 400, code="invalid_request_error"),
        "provider_bad_request",
    ),
]

_TRANSIENT_CASES = [
    _openai_status_error(RateLimitError, 429, code="rate_limit_exceeded"),
    _openai_status_error(InternalServerError, 503, code="internal_server_error"),
    APIConnectionError(request=Request("POST", "https://example.com/v1/chat/completions")),
]


@pytest.mark.parametrize(("error", "expected_code"), _PERMANENT_CASES)
def test_ainvoke_does_not_retry_permanent_provider_errors(error, expected_code, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("src.core.llm_client.asyncio.sleep", fake_sleep)

    async def invoke():
        llm = FakeRetryLlm(error)
        wrapped = _wrap_llm_with_retry(llm, {"max_retries": 3, "delays": [5, 15, 30]})
        with pytest.raises(type(error)) as exc:
            await wrapped.ainvoke("input")
        return llm.ainvoke_calls, exc.value

    calls, raised = asyncio.run(invoke())

    assert calls == 1
    assert sleeps == []
    assert classify_provider_error_code(raised) == expected_code
    assert getattr(raised, "provider_error_code", None) == expected_code
    assert "secret-key-123" not in expected_code


@pytest.mark.parametrize(("error", "expected_code"), _PERMANENT_CASES)
def test_astream_does_not_retry_permanent_provider_errors(error, expected_code, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("src.core.llm_client.asyncio.sleep", fake_sleep)

    async def collect():
        llm = FakeRetryLlm(error)
        wrapped = _wrap_llm_with_retry(llm, {"max_retries": 3, "delays": [5, 15, 30]})
        with pytest.raises(type(error)) as exc:
            async for _chunk in wrapped.astream("input"):
                pass
        return llm.astream_calls, exc.value

    calls, raised = asyncio.run(collect())

    assert calls == 1
    assert sleeps == []
    assert classify_provider_error_code(raised) == expected_code


@pytest.mark.parametrize("error", _TRANSIENT_CASES)
def test_ainvoke_retries_transient_provider_errors(error, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("src.core.llm_client.asyncio.sleep", fake_sleep)

    async def invoke():
        llm = FakeRetryLlm(error)
        wrapped = _wrap_llm_with_retry(llm, {"max_retries": 3, "delays": [5, 15, 30]})
        with pytest.raises(type(error)):
            await wrapped.ainvoke("input")
        return llm.ainvoke_calls

    assert asyncio.run(invoke()) == 4
    assert sleeps == [5, 15, 30]


@pytest.mark.parametrize("error", _TRANSIENT_CASES)
def test_astream_retries_transient_provider_errors(error, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("src.core.llm_client.asyncio.sleep", fake_sleep)

    async def collect():
        llm = FakeRetryLlm(error)
        wrapped = _wrap_llm_with_retry(llm, {"max_retries": 3, "delays": [5, 15, 30]})
        with pytest.raises(type(error)):
            async for _chunk in wrapped.astream("input"):
                pass
        return llm.astream_calls

    assert asyncio.run(collect()) == 4
    assert sleeps == [5, 15, 30]


def test_ainvoke_still_does_not_retry_after_partial_stream(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("src.core.llm_client.asyncio.sleep", fake_sleep)
    error = _openai_status_error(InternalServerError, 503, code="internal_server_error")

    async def invoke():
        llm = FakePartialStreamLlm(error)
        wrapped = _wrap_llm_with_retry(llm, {"max_retries": 3, "delays": [5, 15, 30]})
        with pytest.raises(InternalServerError):
            await wrapped.ainvoke("input")
        return llm.ainvoke_calls

    assert asyncio.run(invoke()) == 1
    assert sleeps == []


def test_astream_still_does_not_retry_after_partial_stream(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("src.core.llm_client.asyncio.sleep", fake_sleep)
    error = _openai_status_error(RateLimitError, 429, code="rate_limit_exceeded")

    async def collect():
        llm = FakePartialStreamLlm(error)
        wrapped = _wrap_llm_with_retry(llm, {"max_retries": 3, "delays": [5, 15, 30]})
        chunks = []
        with pytest.raises(RateLimitError):
            async for chunk in wrapped.astream("input"):
                chunks.append(chunk)
        return llm.astream_calls, chunks

    calls, chunks = asyncio.run(collect())
    assert calls == 1
    assert chunks == ["partial"]
    assert sleeps == []
