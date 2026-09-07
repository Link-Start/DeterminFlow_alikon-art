from __future__ import annotations

import asyncio
import base64
import json
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.account.browser_auth import AccountBrowserAuthorizationFlow
from src.account.portal import (
    CORE_ACCOUNT_CLIENT_ID,
    AccountPortalClient,
    AccountRequestError,
    is_allowed_account_url,
)
from src.account.routes import router
from src.account.service import CoreAccountService


class Browser:
    def __init__(self, result: dict[str, str] | Exception) -> None:
        self.result = result

    async def authorize(self, *_args):
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result)


class Portal:
    def __init__(self) -> None:
        self.logged_out: list[str] = []
        self.refresh_count = 0
        self.refresh_result: dict[str, str] | Exception = {
            "access_token": "renewed",
            "refresh_token": "rotated",
        }

    async def logout(self, refresh_token: str) -> None:
        self.logged_out.append(refresh_token)

    async def refresh(self, _refresh_token: str) -> dict[str, str]:
        self.refresh_count += 1
        if isinstance(self.refresh_result, Exception):
            raise self.refresh_result
        return dict(self.refresh_result)


class GateBrowser:
    def __init__(
        self,
        result: dict[str, str] | Exception | None = None,
    ) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.result: dict[str, str] | Exception = result or {
            "access_token": "access",
            "refresh_token": "refresh",
        }

    def reset_gate(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def authorize(self, *_args):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result)


class HostileBrowser:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()

    async def authorize(self, *_args):
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {"access_token": "late", "refresh_token": "late"}


class DelayedRefreshPortal(Portal):
    def __init__(self) -> None:
        super().__init__()
        self.refresh_started = asyncio.Event()
        self.refresh_release = asyncio.Event()

    async def refresh(self, refresh_token: str) -> dict[str, str]:
        self.refresh_started.set()
        await self.refresh_release.wait()
        return await super().refresh(refresh_token)


class CallbackPortal:
    def __init__(self) -> None:
        self.exchanged: list[dict[str, str]] = []

    def authorization_url(
        self,
        *,
        installation_id: str,
        redirect_uri: str,
        code_challenge: str,
        state: str,
    ) -> str:
        return "https://determinflow.com/desktop-authorize.html?" + urlencode({
            "installation_id": installation_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "state": state,
        })

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, str]:
        self.exchanged.append({
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        })
        return {"access_token": "access", "refresh_token": "refresh"}


async def _yield_to_waiters(task: asyncio.Task, turns: int = 8) -> None:
    for _ in range(turns):
        if task.done():
            return
        await asyncio.sleep(0)


def _redirect_parts(authorization_url: str) -> tuple[str, str, int]:
    query = parse_qs(urlsplit(authorization_url).query)
    redirect_uri = query["redirect_uri"][0]
    state = query["state"][0]
    port = urlsplit(redirect_uri).port
    assert port is not None
    return redirect_uri, state, port


async def _assert_port_closed(port: int, attempts: int = 40) -> None:
    for _ in range(attempts):
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            return
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.02)
    raise AssertionError(f"callback port {port} still accepting connections")


async def _http_get(redirect_uri: str, query: str) -> bytes:
    parsed = urlsplit(redirect_uri)
    assert parsed.hostname is not None
    assert parsed.port is not None
    reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
    writer.write(
        f"GET {parsed.path}?{query} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Connection: close\r\n\r\n".encode()
    )
    await writer.drain()
    payload = await reader.read()
    writer.close()
    await writer.wait_closed()
    return payload


def _service(
    tmp_path: Path,
    *,
    portal: Portal | None = None,
    browser: Browser | None = None,
) -> CoreAccountService:
    return CoreAccountService(
        data_dir=tmp_path,
        portal=portal or Portal(),  # type: ignore[arg-type]
        browser_auth=browser or Browser({
            "access_token": "access",
            "refresh_token": "refresh",
        }),  # type: ignore[arg-type]
    )


def test_account_url_allows_https_and_explicit_loopback_only() -> None:
    assert is_allowed_account_url("https://determinflow.com")
    assert not is_allowed_account_url("http://determinflow.com")
    assert not is_allowed_account_url("http://127.0.0.1:8787")
    assert is_allowed_account_url(
        "http://127.0.0.1:8787",
        allow_loopback_http=True,
    )
    assert not is_allowed_account_url("https://user:pass@determinflow.com")


def test_core_account_client_uses_one_oauth_identity_for_all_capabilities() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.extensions["timeout"]["read"] > 10.0
        assert request.extensions["timeout"]["connect"] == 3.0
        if request.url.path == "/api/desktop-auth/logout":
            return httpx.Response(200, json={"revoked": True})
        return httpx.Response(200, json={
            "access_token": "access",
            "refresh_token": "refresh",
        })

    portal = AccountPortalClient(
        "https://determinflow.com",
        app_version="1.2.3",
        transport=httpx.MockTransport(handler),
    )
    authorization_url = portal.authorization_url(
        installation_id="desktop:one",
        redirect_uri="http://127.0.0.1:1234/callback",
        code_challenge="challenge",
        state="state",
    )
    assert CORE_ACCOUNT_CLIENT_ID == "determinflow-core"
    assert "client_id=determinflow-core" in authorization_url

    async def exercise():
        await portal.exchange_authorization_code(
            code="code",
            code_verifier="verifier",
            redirect_uri="http://127.0.0.1:1234/callback",
        )
        await portal.refresh("refresh")
        await portal.logout("refresh")

    asyncio.run(exercise())
    payloads = [json.loads(request.content) for request in requests]
    assert [payload["client_id"] for payload in payloads] == [
        CORE_ACCOUNT_CLIENT_ID,
        CORE_ACCOUNT_CLIENT_ID,
        CORE_ACCOUNT_CLIENT_ID,
    ]


def test_account_session_is_private_and_survives_restart(tmp_path: Path) -> None:
    service = _service(tmp_path)
    installation_id = service.installation_id
    asyncio.run(service.login())

    assert stat.S_IMODE(service.state_path.stat().st_mode) == 0o600
    reloaded = _service(tmp_path)
    assert reloaded.installation_id == installation_id
    assert reloaded.access_token() == "access"


def test_account_session_reads_public_name_from_jwt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    encoded = base64.urlsafe_b64encode(
        json.dumps({"name": " 北辰 "}, ensure_ascii=False).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    service._replace_session({
        "access_token": f"header.{encoded}.signature",
        "refresh_token": "refresh",
    })

    assert service.public_name() == "北辰"


def test_account_session_reads_stable_identity_not_display_name(tmp_path: Path) -> None:
    service = _service(tmp_path)
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            {
                "iss": "https://accounts.determinflow.com",
                "sub": "acct_alice",
                "name": "北辰",
            },
            ensure_ascii=False,
        ).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    service._replace_session({
        "access_token": f"header.{encoded}.signature",
        "refresh_token": "refresh",
    })

    assert service.local_identity_claims() == (
        "https://accounts.determinflow.com",
        "acct_alice",
    )

    opaque = _service(tmp_path / "opaque")
    opaque._replace_session({
        "access_token": "not-a-jwt",
        "refresh_token": "refresh",
    })
    assert opaque.local_identity_claims() is None


def test_cancelled_relogin_preserves_current_session(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service._replace_session({
        "access_token": "current",
        "refresh_token": "current-refresh",
    })
    service.browser_auth = Browser(AccountRequestError(
        "authorization_denied",
        "账号登录已取消",
        status_code=400,
    ))  # type: ignore[assignment]

    with pytest.raises(AccountRequestError, match="已取消"):
        asyncio.run(service.login())
    assert service.access_token() == "current"


def test_logout_clears_local_session_when_portal_is_not_configured(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service._replace_session({
        "access_token": "current",
        "refresh_token": "current-refresh",
    })
    service.portal = None

    status = asyncio.run(service.logout())

    assert status == {"configured": False, "signed_in": False}
    assert service.access_token() is None


def test_invalid_refresh_clears_only_the_matching_session(tmp_path: Path) -> None:
    portal = Portal()
    portal.refresh_result = AccountRequestError(
        "authentication_failed",
        "登录失效",
        status_code=401,
    )
    service = _service(tmp_path, portal=portal)
    service._replace_session({
        "access_token": "expired",
        "refresh_token": "refresh",
    })

    assert asyncio.run(service.refresh_access_token("expired")) is None
    assert service.access_token() is None


@pytest.mark.parametrize(
    ("host", "peer", "origin", "expected"),
    [
        ("127.0.0.1", "127.0.0.1", None, 200),
        ("rebind.example", "127.0.0.1", None, 403),
        ("127.0.0.1", "192.168.1.2", None, 403),
        ("127.0.0.1", "127.0.0.1", "https://untrusted.example", 403),
    ],
)
def test_account_routes_are_desktop_local_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host: str,
    peer: str,
    origin: str | None,
    expected: int,
) -> None:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    app = FastAPI()
    app.state.account_service = _service(tmp_path)
    app.include_router(router)
    headers = {"Origin": origin} if origin else {}
    with TestClient(app, base_url=f"http://{host}", client=(peer, 50000)) as client:
        assert client.get("/api/account/status", headers=headers).status_code == expected

    monkeypatch.delenv("DETERMINFLOW_DESKTOP", raising=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/account/status").status_code == 404


def test_concurrent_logins_share_one_authorization(tmp_path: Path) -> None:
    async def run() -> None:
        browser = GateBrowser()
        service = _service(tmp_path, browser=browser)
        first = asyncio.create_task(service.login())
        await browser.started.wait()
        second = asyncio.create_task(service.login())
        await _yield_to_waiters(second)
        assert browser.calls == 1
        browser.release.set()
        assert await asyncio.gather(first, second) == [
            {"configured": True, "signed_in": True},
            {"configured": True, "signed_in": True},
        ]
        assert browser.calls == 1
        assert service.access_token() == "access"

    asyncio.run(run())


def test_login_after_success_starts_a_new_authorization(tmp_path: Path) -> None:
    async def run() -> None:
        browser = GateBrowser()
        service = _service(tmp_path, browser=browser)
        browser.release.set()
        assert await service.login() == {"configured": True, "signed_in": True}
        assert browser.calls == 1

        browser.reset_gate()
        browser.result = {"access_token": "next", "refresh_token": "next-refresh"}
        retry = asyncio.create_task(service.login())
        await browser.started.wait()
        assert browser.calls == 2
        browser.release.set()
        assert await retry == {"configured": True, "signed_in": True}
        assert service.access_token() == "next"

    asyncio.run(run())


def test_login_can_retry_after_timeout(tmp_path: Path) -> None:
    async def run() -> None:
        browser = GateBrowser(AccountRequestError(
            "authorization_timeout",
            "账号登录已超时，请重试",
        ))
        service = _service(tmp_path, browser=browser)
        first = asyncio.create_task(service.login())
        await browser.started.wait()
        browser.release.set()
        with pytest.raises(AccountRequestError, match="超时"):
            await first
        assert service.access_token() is None

        browser.reset_gate()
        browser.result = {"access_token": "access", "refresh_token": "refresh"}
        second = asyncio.create_task(service.login())
        await browser.started.wait()
        assert browser.calls == 2
        browser.release.set()
        assert await second == {"configured": True, "signed_in": True}
        assert service.access_token() == "access"

    asyncio.run(run())


def test_cancelled_login_waiter_does_not_abort_shared_authorization(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        browser = GateBrowser()
        service = _service(tmp_path, browser=browser)
        first = asyncio.create_task(service.login())
        await browser.started.wait()
        second = asyncio.create_task(service.login())
        await _yield_to_waiters(second)
        assert browser.calls == 1
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        assert not first.done()
        browser.release.set()
        assert await first == {"configured": True, "signed_in": True}
        assert browser.calls == 1
        assert service.access_token() == "access"

    asyncio.run(run())


def test_logout_is_not_blocked_by_in_flight_login_and_invalidates_it(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        portal = Portal()
        browser = GateBrowser()
        service = _service(tmp_path, portal=portal, browser=browser)
        service._replace_session({
            "access_token": "current",
            "refresh_token": "current-refresh",
        })
        login_task = asyncio.create_task(service.login())
        await browser.started.wait()
        status = await asyncio.wait_for(service.logout(), timeout=0.2)
        assert status == {"configured": True, "signed_in": False}
        assert portal.logged_out == ["current-refresh"]
        with pytest.raises(AccountRequestError, match="已取消"):
            await asyncio.wait_for(login_task, timeout=1)
        assert service.access_token() is None
        assert browser.calls == 1

    asyncio.run(run())


def test_late_authorization_after_logout_cannot_sign_in(tmp_path: Path) -> None:
    async def run() -> None:
        browser = HostileBrowser()
        service = _service(tmp_path, browser=browser)
        login_task = asyncio.create_task(service.login())
        await browser.started.wait()
        await service.logout()
        with pytest.raises(AccountRequestError, match="已取消"):
            await asyncio.wait_for(login_task, timeout=1)
        assert service.access_token() is None
        assert service.status() == {"configured": True, "signed_in": False}

    asyncio.run(run())


@pytest.mark.parametrize("refresh_fails", [False, True])
def test_in_flight_refresh_cannot_overwrite_or_clear_new_login(
    tmp_path: Path,
    refresh_fails: bool,
) -> None:
    async def run() -> None:
        portal = DelayedRefreshPortal()
        if refresh_fails:
            portal.refresh_result = AccountRequestError(
                "authentication_failed",
                "登录失效",
                status_code=401,
            )
        service = _service(
            tmp_path,
            portal=portal,
            browser=Browser({
                "access_token": "new-user",
                "refresh_token": "new-user-refresh",
            }),
        )
        service._replace_session({
            "access_token": "expired",
            "refresh_token": "refresh",
        })
        refresh_task = asyncio.create_task(service.refresh_access_token("expired"))
        await portal.refresh_started.wait()
        assert await service.login() == {"configured": True, "signed_in": True}
        portal.refresh_release.set()
        assert await refresh_task is None
        assert service.access_token() == "new-user"

    asyncio.run(run())


def test_in_flight_refresh_cannot_undo_logout(tmp_path: Path) -> None:
    async def run() -> None:
        portal = DelayedRefreshPortal()
        service = _service(tmp_path, portal=portal)
        service._replace_session({
            "access_token": "expired",
            "refresh_token": "refresh",
        })
        refresh_task = asyncio.create_task(service.refresh_access_token("expired"))
        await portal.refresh_started.wait()
        assert await service.logout() == {"configured": True, "signed_in": False}
        portal.refresh_release.set()
        assert await refresh_task is None
        assert service.access_token() is None

    asyncio.run(run())


def test_browser_auth_cancel_closes_callback_listener() -> None:
    async def run() -> None:
        opened = asyncio.Event()
        captured: dict[str, str] = {}

        def opener(url: str) -> bool:
            captured["url"] = url
            opened.set()
            return True

        flow = AccountBrowserAuthorizationFlow(
            opener=opener,
            callback_timeout_seconds=5,
        )
        task = asyncio.create_task(flow.authorize(CallbackPortal(), "desktop:test"))
        await opened.wait()
        _redirect_uri, _state, port = _redirect_parts(captured["url"])
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.close()
        await writer.wait_closed()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await _assert_port_closed(port)

    asyncio.run(run())


def test_browser_auth_timeout_closes_callback_listener() -> None:
    async def run() -> None:
        captured: dict[str, str] = {}

        def opener(url: str) -> bool:
            captured["url"] = url
            return True

        flow = AccountBrowserAuthorizationFlow(
            opener=opener,
            callback_timeout_seconds=0.05,
        )
        with pytest.raises(AccountRequestError, match="超时"):
            await flow.authorize(CallbackPortal(), "desktop:test")
        _redirect_uri, _state, port = _redirect_parts(captured["url"])
        await _assert_port_closed(port)

    asyncio.run(run())


def test_browser_auth_callback_exchanges_code_without_opening_a_browser() -> None:
    async def run() -> None:
        opened = asyncio.Event()
        captured: dict[str, str] = {}

        def opener(url: str) -> bool:
            captured["url"] = url
            opened.set()
            return True

        portal = CallbackPortal()
        flow = AccountBrowserAuthorizationFlow(
            opener=opener,
            callback_timeout_seconds=5,
        )
        task = asyncio.create_task(flow.authorize(portal, "desktop:test"))
        await opened.wait()
        redirect_uri, state, port = _redirect_parts(captured["url"])
        response = await _http_get(
            redirect_uri,
            urlencode({"code": "pkce-code", "state": state}),
        )
        assert b"200" in response.split(b"\r\n", 1)[0]
        tokens = await task
        assert tokens == {"access_token": "access", "refresh_token": "refresh"}
        assert portal.exchanged[0]["code"] == "pkce-code"
        await _assert_port_closed(port)

    asyncio.run(run())


def test_browser_auth_success_page_offers_bishu_and_determinflow_destinations() -> None:
    page = AccountBrowserAuthorizationFlow._callback_page(True).decode()

    assert "登录成功" in page
    assert 'href="https://bishuxiezuo.cn/"' in page
    assert ">留在笔枢<" in page
    assert 'href="determinflow://auth/complete"' in page
    assert ">返回 DeterminFlow<" in page
    assert "access_token" not in page
    assert "refresh_token" not in page


def test_browser_auth_does_not_show_success_when_token_exchange_fails() -> None:
    class FailingCallbackPortal(CallbackPortal):
        async def exchange_authorization_code(self, **_kwargs) -> dict[str, str]:
            raise AccountRequestError(
                "service_unavailable",
                "DeterminFlow 账号服务暂不可用",
                status_code=503,
            )

    async def run() -> None:
        opened = asyncio.Event()
        captured: dict[str, str] = {}

        def opener(url: str) -> bool:
            captured["url"] = url
            opened.set()
            return True

        flow = AccountBrowserAuthorizationFlow(
            opener=opener,
            callback_timeout_seconds=5,
        )
        task = asyncio.create_task(flow.authorize(FailingCallbackPortal(), "desktop:test"))
        await opened.wait()
        redirect_uri, state, _port = _redirect_parts(captured["url"])
        response = await _http_get(
            redirect_uri,
            urlencode({"code": "pkce-code", "state": state}),
        )

        assert b"503 Service Unavailable" in response.split(b"\r\n", 1)[0]
        assert "登录未完成".encode() in response
        assert "登录成功".encode() not in response
        with pytest.raises(AccountRequestError) as caught:
            await task
        assert caught.value.code == "service_unavailable"

    asyncio.run(run())


def test_browser_auth_failure_page_has_only_the_recovery_destination() -> None:
    page = AccountBrowserAuthorizationFlow._callback_page(False).decode()

    assert "登录未完成" in page
    assert 'href="determinflow://auth/complete"' in page
    assert "https://bishuxiezuo.cn/" not in page


def test_cancel_login_preserves_session_and_allows_immediate_retry(tmp_path: Path) -> None:
    async def run() -> None:
        browser = HostileBrowser()
        service = _service(tmp_path, browser=browser)
        service._replace_session({"access_token": "current", "refresh_token": "current-refresh"})
        first = asyncio.create_task(service.login("first"))
        await browser.started.wait()
        assert await service.cancel_login("first") == {"configured": True, "signed_in": True}
        with pytest.raises(AccountRequestError, match="已取消"):
            await first
        assert service.access_token() == "current"

        next_browser = GateBrowser()
        service.browser_auth = next_browser
        retry = asyncio.create_task(service.login("retry"))
        await next_browser.started.wait()
        await service.cancel_login("first")  # A late cancellation cannot kill the retry.
        assert not retry.done()
        next_browser.release.set()
        await retry
        assert service.access_token() == "access"

    asyncio.run(run())


def test_cancel_before_login_prevents_delayed_request_from_opening_browser(tmp_path: Path) -> None:
    async def run() -> None:
        browser = GateBrowser()
        service = _service(tmp_path, browser=browser)
        await service.cancel_login("cancelled-before-arrival")
        with pytest.raises(AccountRequestError, match="已取消"):
            await service.login("cancelled-before-arrival")
        assert browser.calls == 0
        for index in range(150):
            await service.cancel_login(f"old-{index}")
        assert len(service._cancelled_attempts) == 128

    asyncio.run(run())


def test_total_login_deadline_rejects_late_success_and_releases_shared_flight(tmp_path: Path) -> None:
    async def run() -> None:
        service = CoreAccountService(
            data_dir=tmp_path, portal=Portal(), browser_auth=HostileBrowser(),
            login_timeout_seconds=0.01,
        )
        with pytest.raises(AccountRequestError, match="超时"):
            await service.login("timeout")
        await asyncio.sleep(0)
        assert service.access_token() is None
        assert service._login_flight is None
        service.browser_auth = Browser({"access_token": "retry", "refresh_token": "retry-refresh"})
        await service.login("retry")
        assert service.access_token() == "retry"

    asyncio.run(run())


@pytest.mark.parametrize("error", ["temporarily_unavailable", "server_error"])
def test_gateway_failure_callback_ends_login_without_token_exchange(error: str) -> None:
    async def run() -> None:
        captured: dict[str, str] = {}
        opened = asyncio.Event()

        def opener(url: str) -> bool:
            captured["url"] = url
            opened.set()
            return True

        portal = CallbackPortal()
        flow = AccountBrowserAuthorizationFlow(opener=opener, callback_timeout_seconds=5)
        task = asyncio.create_task(flow.authorize(portal, "desktop:test"))
        await opened.wait()
        redirect_uri, state, port = _redirect_parts(captured["url"])
        await _http_get(redirect_uri, urlencode({"error": error, "state": "invalid"}))
        assert not task.done()
        await _http_get(redirect_uri, urlencode({"error": error, "state": state}))
        with pytest.raises(AccountRequestError) as caught:
            await task
        assert caught.value.code == "service_unavailable"
        assert caught.value.status_code == 503
        assert portal.exchanged == []
        await _assert_port_closed(port)

    asyncio.run(run())


def test_refresh_after_other_account_login_does_not_return_new_token(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        portal = Portal()
        service = _service(tmp_path, portal=portal)
        service._replace_session({
            "access_token": "user-a",
            "refresh_token": "refresh-a",
        })
        await service.logout()
        service.browser_auth = Browser({
            "access_token": "user-b",
            "refresh_token": "refresh-b",
        })
        assert await service.login() == {"configured": True, "signed_in": True}
        assert await service.refresh_access_token("user-a") is None
        assert service.access_token() == "user-b"
        assert portal.refresh_count == 0

    asyncio.run(run())


def test_refresh_after_same_account_relogin_is_cancelled(tmp_path: Path) -> None:
    async def run() -> None:
        portal = Portal()
        service = _service(
            tmp_path,
            portal=portal,
            browser=Browser({
                "access_token": "next-session",
                "refresh_token": "next-refresh",
            }),
        )
        service._replace_session({
            "access_token": "old-session",
            "refresh_token": "old-refresh",
        })
        assert await service.login() == {"configured": True, "signed_in": True}
        assert await service.refresh_access_token("old-session") is None
        assert service.access_token() == "next-session"
        assert portal.refresh_count == 0

    asyncio.run(run())


def test_same_session_rotation_still_returns_current_token(tmp_path: Path) -> None:
    async def run() -> None:
        portal = Portal()
        service = _service(tmp_path, portal=portal)
        service._replace_session({
            "access_token": "expired",
            "refresh_token": "refresh",
        })
        assert await service.refresh_access_token("expired") == "renewed"
        assert await service.refresh_access_token("expired") == "renewed"
        assert service.access_token() == "renewed"
        assert portal.refresh_count == 1

    asyncio.run(run())


def test_concurrent_same_session_refresh_shares_one_rotation(tmp_path: Path) -> None:
    async def run() -> None:
        portal = DelayedRefreshPortal()
        service = _service(tmp_path, portal=portal)
        service._replace_session({
            "access_token": "expired",
            "refresh_token": "refresh",
        })
        first = asyncio.create_task(service.refresh_access_token("expired"))
        await portal.refresh_started.wait()
        second = asyncio.create_task(service.refresh_access_token("expired"))
        await _yield_to_waiters(second)
        portal.refresh_release.set()
        assert await asyncio.gather(first, second) == ["renewed", "renewed"]
        assert service.access_token() == "renewed"
        assert portal.refresh_count == 1

    asyncio.run(run())


def test_cancel_login_route_is_local_and_validates_attempt_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DETERMINFLOW_DESKTOP", "1")
    app = FastAPI()
    app.state.account_service = _service(tmp_path)
    app.include_router(router)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.post("/api/account/login/cancel", json={"attempt_id": "safe"}, headers={"origin": "https://untrusted.example"}).status_code == 403
        assert client.post("/api/account/login/cancel", json={"attempt_id": ""}).status_code == 422
        assert client.post("/api/account/login/cancel", json={"attempt_id": "safe"}).status_code == 200
        result = client.post("/api/account/login", json={"attempt_id": "safe"})
        assert result.status_code == 400
        assert result.json()["detail"]["code"] == "authorization_denied"
