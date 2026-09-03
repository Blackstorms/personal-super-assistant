"""飞书用户 OAuth（与 lark-mcp login 同源：localhost 临时回调 → user_access_token）。"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

FEISHU_DOMAIN = "https://open.feishu.cn"
AUTHORIZE_URL = f"{FEISHU_DOMAIN}/open-apis/authen/v1/authorize"
TOKEN_URL = "https://accounts.feishu.cn/oauth/v3/token"
REFRESH_URL = TOKEN_URL

DEFAULT_SCOPES = (
    "offline_access contact:user:search task:task:write task:task:writeonly"
)

_OAUTH_TTL_SEC = 600
_SUCCESS_HTML = (
    "<html><body style='font-family:sans-serif;padding:2rem'>"
    "<h3>✅ 飞书授权成功</h3>"
    "<p>USER_ACCESS_TOKEN 已写入连接器配置，可关闭此页并回到「个人超级助理」。</p>"
    "</body></html>"
)
_ERROR_HTML = (
    "<html><body style='font-family:sans-serif;padding:2rem'>"
    "<h3>飞书授权失败</h3><p>{msg}</p>"
    "<p>请确认已在开放平台配置重定向 URL，且 APP_ID/SECRET 正确。</p>"
    "</body></html>"
)


@dataclass
class FeishuOAuthPending:
    state: str
    server_id: str
    app_id: str
    app_secret: str
    redirect_uri: str
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending | success | error
    message: str = ""
    saved_to_db: bool = False
    access_token: str = ""
    refresh_token: str = ""
    expires_in: int | None = None


_pending: dict[str, FeishuOAuthPending] = {}
_callback_server: asyncio.AbstractServer | None = None
_callback_port: int | None = None
_on_success: Callable[[FeishuOAuthPending], Awaitable[None]] | None = None


def feishu_oauth_callback_url(port: int | None = None) -> str:
    """飞书开放平台重定向 URL（与 lark-mcp 一致：localhost 环回，非 API 端口）。"""
    p = port or settings.feishu_oauth_port
    return f"http://{settings.feishu_oauth_host}:{p}{settings.feishu_oauth_path}"


def set_feishu_oauth_success_handler(
    handler: Callable[[FeishuOAuthPending], Awaitable[None]] | None,
) -> None:
    global _on_success
    _on_success = handler


def _prune_expired() -> None:
    now = time.time()
    dead = [k for k, v in _pending.items() if now - v.created_at > _OAUTH_TTL_SEC]
    for k in dead:
        _pending.pop(k, None)


def _http_response(status: int, body: str, content_type: str = "text/html; charset=utf-8") -> bytes:
    body_bytes = body.encode("utf-8")
    head = (
        f"HTTP/1.1 {status} OK\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n\r\n"
    )
    return head.encode("utf-8") + body_bytes


async def _handle_oauth_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        raw = await reader.read(8192)
        first = raw.decode("utf-8", errors="ignore").split("\r\n", 1)[0]
        parts = first.split(" ")
        path = parts[1] if len(parts) > 1 else "/"
        parsed = urlparse(path)
        if parsed.path != settings.feishu_oauth_path:
            writer.write(_http_response(404, "<html><body>Not Found</body></html>"))
            await writer.drain()
            return

        qs = parse_qs(parsed.query)
        state = (qs.get("state") or [""])[0]
        code = (qs.get("code") or [""])[0]
        err = (qs.get("error") or [""])[0]

        if err:
            pending = _pending.get(state)
            if pending:
                pending.status = "error"
                pending.message = err
            writer.write(_http_response(400, _ERROR_HTML.format(msg=err)))
            await writer.drain()
            return
        if not code or not state:
            writer.write(_http_response(400, _ERROR_HTML.format(msg="缺少 code 或 state")))
            await writer.drain()
            return

        try:
            pending = await exchange_feishu_code(state, code)
            if _on_success:
                await _on_success(pending)
            writer.write(_http_response(200, _SUCCESS_HTML))
        except Exception as e:  # noqa: BLE001
            logger.warning("feishu oauth callback failed: %s", e)
            writer.write(_http_response(400, _ERROR_HTML.format(msg=str(e))))
        await writer.drain()
    except Exception as e:  # noqa: BLE001
        logger.warning("feishu oauth http handler error: %s", e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        await _maybe_stop_callback_server()


async def _ensure_callback_server(port: int) -> int:
    global _callback_server, _callback_port
    if _callback_server is not None and _callback_port == port:
        return port
    if _callback_server is not None:
        await _stop_callback_server()
    _callback_server = await asyncio.start_server(
        _handle_oauth_http,
        host=settings.feishu_oauth_host,
        port=port,
    )
    _callback_port = port
    logger.info("feishu oauth callback listening on %s", feishu_oauth_callback_url(port))
    return port


async def _stop_callback_server() -> None:
    global _callback_server, _callback_port
    if _callback_server is None:
        return
    _callback_server.close()
    await _callback_server.wait_closed()
    _callback_server = None
    _callback_port = None


async def _maybe_stop_callback_server() -> None:
    _prune_expired()
    active = [p for p in _pending.values() if p.status == "pending"]
    if not active:
        await _stop_callback_server()


async def _pick_callback_port() -> int:
    base = settings.feishu_oauth_port
    last_err: OSError | None = None
    for offset in range(10):
        port = base + offset
        try:
            await _ensure_callback_server(port)
            return port
        except OSError as e:
            last_err = e
            await _stop_callback_server()
    raise RuntimeError(f"无法绑定 OAuth 回调端口 {base}-{base + 9}: {last_err}")


async def start_feishu_oauth(
    *,
    server_id: str,
    app_id: str,
    app_secret: str,
    scopes: str | None = None,
) -> dict[str, Any]:
    """创建 OAuth 会话、启动 localhost 临时回调，并返回浏览器授权 URL。"""
    app_id = (app_id or "").strip()
    app_secret = (app_secret or "").strip()
    if not app_id or not app_secret:
        raise ValueError("请先填写 APP_ID 与 APP_SECRET")

    _prune_expired()
    port = await _pick_callback_port()
    state = secrets.token_urlsafe(24)
    redirect_uri = feishu_oauth_callback_url(port)
    pending = FeishuOAuthPending(
        state=state,
        server_id=server_id,
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
    )
    _pending[state] = pending

    scope = (scopes or DEFAULT_SCOPES).strip()
    params = {
        "client_id": app_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scope,
    }
    authorize_url = f"{AUTHORIZE_URL}?{urlencode(params)}"
    port_note = ""
    if port != settings.feishu_oauth_port:
        port_note = (
            f"默认 {feishu_oauth_callback_url()} 已被占用，当前实际回调为 {redirect_uri}，"
            "请把该地址加入开放平台重定向 URL。"
        )
    return {
        "state": state,
        "authorize_url": authorize_url,
        "redirect_uri": redirect_uri,
        "expires_in_sec": _OAUTH_TTL_SEC,
        "hint": (
            "已用系统浏览器打开授权页。请在飞书开放平台 → 安全设置 → 重定向 URL 添加 "
            f"{redirect_uri}（localhost 环回，与 lark-mcp 一致）；并开启「刷新 user_access_token」。"
            + (port_note and f" {port_note}")
        ),
    }


def get_feishu_oauth_status(state: str) -> dict[str, Any]:
    _prune_expired()
    pending = _pending.get(state)
    if not pending:
        return {"status": "missing", "message": "授权会话不存在或已过期，请重新发起"}
    return {
        "status": pending.status,
        "message": pending.message,
        "has_access_token": bool(pending.access_token),
        "saved_to_db": pending.saved_to_db,
        "expires_in": pending.expires_in,
    }


async def exchange_feishu_code(state: str, code: str) -> FeishuOAuthPending:
    pending = _pending.get(state)
    if not pending:
        raise ValueError("授权会话不存在或已过期")
    if pending.status == "success":
        return pending

    body = {
        "grant_type": "authorization_code",
        "client_id": pending.app_id,
        "client_secret": pending.app_secret,
        "code": code,
        "redirect_uri": pending.redirect_uri,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(TOKEN_URL, json=body)
        data = r.json() if r.content else {}

    if isinstance(data, dict) and data.get("code") not in (0, None) and "access_token" not in data:
        msg = str(data.get("msg") or data.get("error_description") or r.text or r.reason_phrase)
        pending.status = "error"
        pending.message = msg
        raise ValueError(msg)

    token_payload = data
    if isinstance(data, dict) and isinstance(data.get("data"), dict) and "access_token" not in data:
        token_payload = data["data"]
    access = str(
        token_payload.get("access_token")
        or token_payload.get("user_access_token")
        or ""
    ).strip()
    if not access:
        pending.status = "error"
        pending.message = "未返回 access_token"
        raise ValueError(pending.message)

    refresh = str(token_payload.get("refresh_token") or "").strip()
    expires_in = token_payload.get("expires_in")
    try:
        pending.expires_in = int(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        pending.expires_in = None

    pending.access_token = access
    pending.refresh_token = refresh
    pending.status = "success"
    pending.message = "授权成功"
    return pending


async def refresh_feishu_user_token(
    *,
    app_id: str,
    app_secret: str,
    refresh_token: str,
) -> dict[str, str]:
    body = {
        "grant_type": "refresh_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(REFRESH_URL, json=body)
        data = r.json() if r.content else {}
    if r.status_code >= 400 or data.get("code") not in (0, None):
        msg = str(data.get("msg") or data.get("error_description") or r.text or r.reason_phrase)
        raise ValueError(msg)
    token_payload = data.get("data") if isinstance(data.get("data"), dict) else data
    access = str(
        token_payload.get("access_token")
        or token_payload.get("user_access_token")
        or ""
    ).strip()
    refresh = str(token_payload.get("refresh_token") or refresh_token).strip()
    if not access:
        raise ValueError("refresh 未返回 access_token")
    return {"access_token": access, "refresh_token": refresh}


def pop_oauth_tokens(state: str) -> dict[str, str] | None:
    pending = _pending.get(state)
    if not pending or pending.status != "success" or not pending.access_token:
        return None
    out = {
        "USER_ACCESS_TOKEN": pending.access_token,
        "REFRESH_USER_ACCESS_TOKEN": pending.refresh_token,
    }
    _pending.pop(state, None)
    return out
