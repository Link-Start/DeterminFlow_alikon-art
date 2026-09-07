from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from src.account.portal import AccountPortalClient, AccountRequestError
from src.account.service import CoreAccountService


@pytest.fixture
def anyio_backend():
    return "asyncio"


def token(subject="user-a", name=None):
    claims = {"sub": subject, "iss": "https://accounts.determinflow.com"}
    if name is not None:
        claims["name"] = name
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


@pytest.mark.anyio
async def test_profile_http_uses_only_bearer_and_public_fields():
    def respond(request):
        assert request.method == "GET"
        assert request.url.path == "/api/desktop-auth/profile"
        assert request.headers["authorization"] == "Bearer access"
        assert not request.content
        return httpx.Response(200, json={"sub": "user-a", "name": " 新笔名 ", "email": "private"})
    portal = AccountPortalClient("https://determinflow.com", app_version="test", transport=httpx.MockTransport(respond))
    assert await portal.profile("access") == {"sub": "user-a", "name": "新笔名"}


@pytest.mark.anyio
async def test_latest_profile_fills_missing_claim_and_caches(tmp_path):
    calls = []
    async def profile(access):
        calls.append(access)
        return {"sub": "user-a", "name": "最新笔名"}
    portal = AccountPortalClient("https://determinflow.com", app_version="test")
    portal.profile = profile
    service = CoreAccountService(data_dir=tmp_path, portal=portal)
    service._replace_session({"access_token": token(), "refresh_token": "refresh"})
    assert service.public_name() is None
    await asyncio.gather(service.refresh_public_name(), service.refresh_public_name())
    assert service.public_name() == "最新笔名"
    assert len(calls) == 1
    service._profile_retry_after = 0
    async def empty(_access):
        return {"sub": "user-a", "name": None}
    portal.profile = empty
    await service.refresh_public_name()
    assert service.public_name() is None


@pytest.mark.anyio
async def test_profile_failure_is_bounded_retried_later_and_keeps_claim(tmp_path):
    calls = []
    async def profile(_access):
        calls.append(1)
        raise AccountRequestError("service_unavailable", "temporary", status_code=503)
    portal = AccountPortalClient("https://determinflow.com", app_version="test")
    portal.profile = profile
    service = CoreAccountService(data_dir=tmp_path, portal=portal)
    service._replace_session({"access_token": token(name="原笔名"), "refresh_token": "refresh"})
    await service.refresh_public_name()
    await service.refresh_public_name()
    assert service.public_name() == "原笔名"
    assert service.status()["signed_in"] is True
    assert len(calls) == 1


@pytest.mark.anyio
async def test_late_profile_cannot_cross_logout_or_account_change(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    async def profile(_access):
        started.set()
        await release.wait()
        return {"sub": "user-a", "name": "A 的笔名"}
    portal = AccountPortalClient("https://determinflow.com", app_version="test")
    portal.profile = profile
    service = CoreAccountService(data_dir=tmp_path, portal=portal)
    service._replace_session({"access_token": token(), "refresh_token": "refresh"})
    task = asyncio.create_task(service.refresh_public_name())
    await started.wait()
    service._replace_session({"access_token": token("user-b", "B 的笔名"), "refresh_token": "refresh-b"})
    release.set()
    await task
    assert service.public_name() == "B 的笔名"
    assert not service._profile_loaded


@pytest.mark.anyio
async def test_profile_rejects_mismatched_subject(tmp_path):
    async def profile(_access):
        return {"sub": "different-user", "name": "错误笔名"}
    portal = AccountPortalClient("https://determinflow.com", app_version="test")
    portal.profile = profile
    service = CoreAccountService(data_dir=tmp_path, portal=portal)
    service._replace_session({"access_token": token(), "refresh_token": "refresh"})
    await service.refresh_public_name()
    assert service.public_name() is None
    assert not service._profile_loaded


@pytest.mark.anyio
async def test_profile_refreshes_expired_access_once(tmp_path):
    old = token(name="旧笔名")
    fresh = token(name="新笔名")
    calls = []
    async def profile(access):
        calls.append(access)
        if access == old:
            raise AccountRequestError("authentication_failed", "expired", status_code=401)
        return {"sub": "user-a", "name": "最新笔名"}
    async def refresh(_refresh):
        return {"access_token": fresh, "refresh_token": "rotated"}
    portal = AccountPortalClient("https://determinflow.com", app_version="test")
    portal.profile, portal.refresh = profile, refresh
    service = CoreAccountService(data_dir=tmp_path, portal=portal)
    service._replace_session({"access_token": old, "refresh_token": "refresh"})
    await service.refresh_public_name()
    assert calls == [old, fresh]
    assert service.public_name() == "最新笔名"


@pytest.mark.anyio
async def test_status_wait_timeout_does_not_cancel_token_rotation(tmp_path, monkeypatch):
    import src.account.service as account_module
    monkeypatch.setattr(account_module, "_PROFILE_WAIT_SECONDS", 0.01)
    started, release = asyncio.Event(), asyncio.Event()
    old, fresh = token(), token(name="更新笔名")
    async def profile(access):
        if access == old:
            raise AccountRequestError("authentication_failed", "expired", status_code=401)
        return {"sub": "user-a", "name": "更新笔名"}
    async def refresh(_refresh):
        started.set()
        await release.wait()
        return {"access_token": fresh, "refresh_token": "rotated"}
    portal = AccountPortalClient("https://determinflow.com", app_version="test")
    portal.profile, portal.refresh = profile, refresh
    service = CoreAccountService(data_dir=tmp_path, portal=portal)
    service._replace_session({"access_token": old, "refresh_token": "refresh"})
    await service.refresh_public_name()
    assert started.is_set()
    assert not service._profile_task.done()
    release.set()
    await service._profile_task
    assert service.access_token() == fresh
    assert service.public_name() == "更新笔名"
