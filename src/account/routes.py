"""Desktop-local routes for the Core account session."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .portal import AccountRequestError
from .service import CoreAccountService

router = APIRouter(prefix="/api/account", tags=["account"])


class LoginAttempt(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def account_service(request: Request) -> CoreAccountService:
    if os.getenv("DETERMINFLOW_DESKTOP") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    origin = request.headers.get("origin")
    try:
        local_peer = (
            request.client is not None
            and ipaddress.ip_address(request.client.host).is_loopback
        )
        local_host = _loopback_host(request.url.hostname)
        local_origin = not origin or (
            urlsplit(origin).scheme in {"http", "https"}
            and _loopback_host(urlsplit(origin).hostname)
        )
    except ValueError:
        local_peer = local_host = local_origin = False
    if not (local_peer and local_host and local_origin):
        raise HTTPException(status_code=403, detail="账号桌面接口仅允许本机访问")
    service = getattr(request.app.state, "account_service", None)
    if not isinstance(service, CoreAccountService):
        raise HTTPException(status_code=503, detail="账号服务尚未初始化")
    return service


def _loopback_host(host: str | None) -> bool:
    if host == "localhost":
        return True
    if host is None:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def raise_account_error(exc: AccountRequestError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


@router.get("/status")
async def status(request: Request):
    service = account_service(request)
    await service.refresh_public_name()
    return service.status()


@router.post("/login")
async def login(request: Request, attempt: LoginAttempt | None = None):
    try:
        return await account_service(request).login(attempt.attempt_id if attempt else None)
    except AccountRequestError as exc:
        raise_account_error(exc)


@router.post("/login/cancel")
async def cancel_login(request: Request, attempt: LoginAttempt):
    return await account_service(request).cancel_login(attempt.attempt_id)


@router.post("/logout")
async def logout(request: Request):
    try:
        return await account_service(request).logout()
    except AccountRequestError as exc:
        raise_account_error(exc)
