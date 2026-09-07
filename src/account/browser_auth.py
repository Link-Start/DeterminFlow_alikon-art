"""External-browser PKCE authorization for the Core account."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import webbrowser
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

from .portal import AccountPortalClient, AccountRequestError

_CALLBACK_TIMEOUT_SECONDS = 180
_MAX_REQUEST_HEAD_BYTES = 8192


def _discard_closing_result(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


async def _close_callback_server(server: asyncio.AbstractServer) -> None:
    server.close()
    closing = asyncio.ensure_future(server.wait_closed())
    try:
        await asyncio.shield(closing)
    except asyncio.CancelledError:
        closing.add_done_callback(_discard_closing_result)
        raise


class AccountBrowserAuthorizationFlow:
    def __init__(
        self,
        *,
        opener: Callable[[str], bool] | None = None,
        callback_timeout_seconds: float = _CALLBACK_TIMEOUT_SECONDS,
    ) -> None:
        self._opener = opener or (lambda url: webbrowser.open(url, new=2))
        self._callback_timeout_seconds = callback_timeout_seconds

    async def authorize(
        self,
        portal: AccountPortalClient,
        installation_id: str,
    ) -> dict[str, str]:
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        loop = asyncio.get_running_loop()
        result: asyncio.Future[dict[str, str]] = loop.create_future()

        async def handle_callback(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            success = False
            completion: dict[str, str] | None = None
            completion_error: AccountRequestError | None = None
            should_finish = False
            try:
                request_head = await asyncio.wait_for(
                    reader.readuntil(b"\r\n\r\n"),
                    timeout=5,
                )
                if len(request_head) > _MAX_REQUEST_HEAD_BYTES:
                    raise ValueError("request too large")
                request_line = request_head.split(b"\r\n", 1)[0].decode("ascii")
                method, target, _version = request_line.split(" ", 2)
                parsed = urlsplit(target)
                query = parse_qs(parsed.query)
                if method != "GET" or parsed.path != "/callback":
                    raise ValueError("invalid callback path")
                callback_state = query.get("state", [""])[0]
                if not secrets.compare_digest(callback_state, state):
                    raise ValueError("invalid callback state")
                error = query.get("error", [""])[0]
                code = query.get("code", [""])[0]
                if error:
                    unavailable = error in {"temporarily_unavailable", "server_error"}
                    completion_error = AccountRequestError(
                        "service_unavailable" if unavailable else "authorization_denied",
                        "笔枢账户服务暂不可用，请稍后重试" if unavailable else "账号登录已取消",
                        status_code=503 if unavailable else 400,
                    )
                    should_finish = True
                    raise ValueError("authorization denied")
                if not code:
                    raise ValueError("missing authorization code")
                try:
                    completion = await portal.exchange_authorization_code(
                        code=code,
                        code_verifier=verifier,
                        redirect_uri=redirect_uri,
                    )
                except AccountRequestError as exc:
                    completion_error = exc
                should_finish = True
                success = completion is not None and not result.done()
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
                success = False

            body = self._callback_page(success)
            status_line = (
                "200 OK"
                if success
                else (
                    "503 Service Unavailable"
                    if completion_error is not None and completion_error.status_code == 503
                    else "400 Bad Request"
                )
            )
            response = (
                f"HTTP/1.1 {status_line}\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                "Cache-Control: no-store\r\n"
                "Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'\r\n"
                "Referrer-Policy: no-referrer\r\n"
                "X-Content-Type-Options: nosniff\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii") + body
            try:
                writer.write(response)
                await writer.drain()
            except OSError:
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
            if should_finish and not result.done():
                if completion_error is not None:
                    result.set_exception(completion_error)
                elif completion is not None:
                    result.set_result(completion)

        server = await asyncio.start_server(
            handle_callback,
            "127.0.0.1",
            0,
            limit=_MAX_REQUEST_HEAD_BYTES,
        )
        try:
            socket = next(iter(server.sockets or []), None)
            if socket is None:
                raise AccountRequestError(
                    "callback_unavailable",
                    "无法启动账号登录回调",
                )
            port = int(socket.getsockname()[1])
            redirect_uri = f"http://127.0.0.1:{port}/callback"
            authorization_url = portal.authorization_url(
                installation_id=installation_id,
                redirect_uri=redirect_uri,
                code_challenge=challenge,
                state=state,
            )
            opened = await asyncio.to_thread(self._opener, authorization_url)
            if not opened:
                raise AccountRequestError("browser_unavailable", "无法打开系统浏览器")
            try:
                return await asyncio.wait_for(
                    result,
                    timeout=self._callback_timeout_seconds,
                )
            except TimeoutError as exc:
                raise AccountRequestError(
                    "authorization_timeout",
                    "账号登录已超时，请重试",
                ) from exc
        finally:
            await _close_callback_server(server)

    @staticmethod
    def _callback_page(success: bool) -> bytes:
        title = "登录成功" if success else "登录未完成"
        message = (
            "DeterminFlow 已连接到你的笔枢账户。"
            if success
            else "请返回 DeterminFlow 后重新登录。"
        )
        actions = (
            '<div class="actions">'
            '<a class="secondary" href="https://bishuxiezuo.cn/" rel="noreferrer">留在笔枢</a>'
            '<a class="primary" href="determinflow://auth/complete">返回 DeterminFlow</a>'
            "</div>"
            '<p class="hint">若未能唤起，请手动返回 DeterminFlow。</p>'
            if success
            else (
                '<div class="actions single">'
                '<a class="primary" href="determinflow://auth/complete">返回 DeterminFlow</a>'
                "</div>"
            )
        )
        return f"""<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>{title} · 笔枢</title>
  <style>
    :root {{
      color-scheme: light;
      --paper: #f8f4eb;
      --card: #ffffff;
      --ink: #221d16;
      --muted: #6f6558;
      --line: rgba(34, 29, 22, 0.12);
      --gold: #9a6a20;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      background: var(--paper);
      color: var(--ink);
      font-family: "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
    }}
    main {{
      width: min(460px, 100%);
      padding: 30px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--card);
      box-shadow: 0 22px 70px rgba(34, 29, 22, 0.12);
    }}
    .brand {{
      display: flex;
      align-items: baseline;
      gap: 9px;
      margin-bottom: 28px;
    }}
    .brand strong {{
      font-family: "Songti SC", serif;
      font-size: 22px;
      letter-spacing: 0.06em;
    }}
    .brand span {{
      color: var(--gold);
      font-family: Georgia, serif;
      font-size: 12px;
      font-style: italic;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-family: "Songti SC", serif;
      font-size: 27px;
      font-weight: 600;
    }}
    .lead {{
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.65;
    }}
    .actions {{
      display: grid;
      grid-template-columns: 1fr 1.6fr;
      gap: 10px;
      margin-top: 24px;
    }}
    .actions.single {{ grid-template-columns: 1fr; }}
    a {{
      min-height: 44px;
      display: grid;
      place-items: center;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      text-decoration: none;
    }}
    a.secondary {{
      border: 1px solid var(--line);
      color: var(--muted);
    }}
    a.primary {{
      border: 1px solid var(--ink);
      background: var(--ink);
      color: var(--paper);
    }}
    a.primary:hover {{
      border-color: var(--gold);
      background: var(--gold);
    }}
    a:focus-visible {{ outline: 2px solid var(--gold); outline-offset: 3px; }}
    .hint {{
      margin: 14px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
      text-align: center;
    }}
    @media (max-width: 460px) {{
      main {{ padding: 24px; }}
      .actions {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="brand"><strong>笔枢</strong><span>Novelbuilt</span></div>
    <h1>{title}</h1>
    <p class="lead">{message}</p>
    {actions}
  </main>
</body>
</html>""".encode()
