"""HTTP boundary for the DeterminFlow Account desktop OAuth flow."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

DEFAULT_ACCOUNT_URL = "https://determinflow.com"
CORE_ACCOUNT_CLIENT_ID = "determinflow-core"


class AccountRequestError(RuntimeError):
    """An account failure that is safe to return to the desktop UI."""

    def __init__(self, code: str, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def is_allowed_account_url(value: str, *, allow_loopback_http: bool = False) -> bool:
    parsed = urlparse(value)
    if (
        not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if parsed.scheme == "https":
        return True
    if not allow_loopback_http or parsed.scheme != "http" or not parsed.hostname:
        return False
    if parsed.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


class AccountPortalClient:
    """Typed client for the website desktop-auth proxy."""

    client_id = CORE_ACCOUNT_CLIENT_ID

    def __init__(
        self,
        base_url: str,
        *,
        app_version: str,
        allow_loopback_http: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not is_allowed_account_url(
            normalized,
            allow_loopback_http=allow_loopback_http,
        ):
            raise ValueError("账号服务地址必须是 HTTPS 或显式允许的本机 HTTP 地址")
        self.base_url = normalized
        self.app_version = app_version.strip() or "unknown"
        self.transport = transport

    def authorization_url(
        self,
        *,
        installation_id: str,
        redirect_uri: str,
        code_challenge: str,
        state: str,
    ) -> str:
        query = urlencode({
            "client_id": self.client_id,
            "installation_id": installation_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        })
        return f"{self.base_url}/desktop-authorize.html?{query}"

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, str]:
        body = await self._request_json(
            "/api/desktop-auth/token",
            {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": redirect_uri,
            },
        )
        return self._tokens(body)

    async def refresh(self, refresh_token: str) -> dict[str, str]:
        body = await self._request_json(
            "/api/desktop-auth/refresh",
            {"client_id": self.client_id, "refresh_token": refresh_token},
        )
        return self._tokens(body)

    async def logout(self, refresh_token: str) -> None:
        await self._request_json(
            "/api/desktop-auth/logout",
            {"client_id": self.client_id, "refresh_token": refresh_token},
        )

    async def profile(self, access_token: str) -> dict[str, Any]:
        body = await self._request_json("/api/desktop-auth/profile", access_token=access_token)
        subject, name = body.get("sub"), body.get("name")
        if (
            not isinstance(subject, str) or not subject.strip() or len(subject) > 128
            or (name is not None and (not isinstance(name, str) or len(name) > 80))
        ):
            raise AccountRequestError("invalid_response", "账号资料响应无效")
        return {"sub": subject, "name": name.strip() or None if isinstance(name, str) else None}

    async def _request_json(
        self, path: str, payload: dict[str, Any] | None = None, *, access_token: str | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                # Account gateway allows 10 seconds for its upstream request.
                timeout=httpx.Timeout(15.0, connect=3.0),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    "GET" if access_token is not None else "POST",
                    path,
                    json=payload,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": f"DeterminFlow-Core/{self.app_version}",
                        **({"Authorization": f"Bearer {access_token}"} if access_token is not None else {}),
                    },
                )
        except httpx.RequestError as exc:
            raise AccountRequestError(
                "network_unavailable",
                "暂时无法连接 DeterminFlow 账号服务",
            ) from exc
        if response.status_code == 401:
            raise AccountRequestError(
                "authentication_failed",
                "账号登录状态已失效",
                status_code=401,
            )
        if response.status_code in {404, 502, 503, 504}:
            raise AccountRequestError(
                "service_unavailable",
                "DeterminFlow 账号服务暂不可用",
                status_code=503,
            )
        if response.status_code >= 400:
            raise AccountRequestError(
                "request_failed",
                "DeterminFlow 账号请求失败",
                status_code=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise AccountRequestError(
                "invalid_response",
                "DeterminFlow 账号服务返回了无效响应",
            ) from exc
        if not isinstance(body, dict):
            raise AccountRequestError(
                "invalid_response",
                "DeterminFlow 账号服务返回了无效响应",
            )
        return body

    @staticmethod
    def _tokens(body: dict[str, Any]) -> dict[str, str]:
        access_token = body.get("access_token")
        refresh_token = body.get("refresh_token")
        if not isinstance(access_token, str) or not access_token:
            raise AccountRequestError("invalid_response", "账号响应缺少访问令牌")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise AccountRequestError("invalid_response", "账号响应缺少续期令牌")
        return {"access_token": access_token, "refresh_token": refresh_token}
