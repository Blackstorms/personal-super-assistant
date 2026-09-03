"""MCP API。"""

from __future__ import annotations

import asyncio
import json
import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_token
from app.db.deps import db_dep
from app.mcp.import_config import parse_mcp_import
from app.mcp.manager import mcp_manager
from app.mcp.config_file import export_mcp_config, mcp_config_path, sync_mcp_config, write_config_mirror
from app.mcp.presets import preset_json_template, preset_meta

router = APIRouter(dependencies=[Depends(require_token)])
logger = logging.getLogger(__name__)

FEISHU_PRESET_ID = "preset-mcp-feishu"


async def _load_server_env(db: aiosqlite.Connection, server_id: str) -> tuple[dict, dict]:
    cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "not_found", "message": "server not found"})
    data = dict(row)
    env = json.loads(data.get("env_json") or "{}")
    if not isinstance(env, dict):
        env = {}
    return data, env


async def _save_server_env(db: aiosqlite.Connection, server_id: str, env: dict) -> None:
    from app.db.database import utc_now

    await db.execute(
        "UPDATE mcp_servers SET env_json=?, updated_at=? WHERE id=?",
        (json.dumps(env, ensure_ascii=False), utc_now(), server_id),
    )
    await db.commit()


class McpIn(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    url: str | None = None
    headers: dict | None = None
    tools_policy: dict | None = None
    timeout: int | None = None
    connect_timeout: int | None = None
    supports_parallel: bool = False
    auth_type: str | None = None
    enabled: bool = True


class McpPatch(BaseModel):
    name: str | None = None
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict | None = None
    url: str | None = None
    headers: dict | None = None
    tools_policy: dict | None = None
    timeout: int | None = None
    connect_timeout: int | None = None
    supports_parallel: bool | None = None
    auth_type: str | None = None
    enabled: bool | None = None


class McpImportBody(BaseModel):
    """支持 mcpServers 对象、单条配置或数组。"""
    config: dict | list | str


def _row_to_item(r: dict) -> dict:
    item = {
        "id": r["id"],
        "name": r["name"],
        "transport": r["transport"],
        "command": r["command"],
        "args": json.loads(r["args_json"] or "[]"),
        "env": json.loads(r["env_json"] or "{}"),
        "url": r["url"],
        "headers": json.loads(r["headers_json"] or "{}") if r.get("headers_json") is not None else {},
        "tools_policy": json.loads(r["tools_policy_json"] or "{}") if r.get("tools_policy_json") is not None else {},
        "timeout": r.get("timeout"),
        "connect_timeout": r.get("connect_timeout"),
        "supports_parallel": bool(r.get("supports_parallel") or 0),
        "auth_type": r.get("auth_type"),
        "enabled": bool(r["enabled"]),
        "is_preset": str(r["id"]).startswith("preset-mcp-"),
    }
    meta = preset_meta(str(r["id"]))
    if meta:
        item.update(meta)
    else:
        item.setdefault("description", "")
        item.setdefault("category", "个人")
        item.setdefault("badge", None)
        item.setdefault("icon", "default")
    return item


class McpConfigBody(BaseModel):
    config: dict


@router.get("/config")
async def get_mcp_config(db: aiosqlite.Connection = Depends(db_dep)):
    """导出全部 MCP 为 mcpServers JSON，并返回配置文件路径。"""
    rows = await mcp_manager.list_servers(db)
    config = export_mcp_config([dict(r) for r in rows])
    await write_config_mirror(config)
    return {"path": str(mcp_config_path()), "config": config}


@router.put("/config")
async def put_mcp_config(body: McpConfigBody, db: aiosqlite.Connection = Depends(db_dep)):
    """从完整 mcpServers JSON 同步到数据库。"""
    try:
        count = await sync_mcp_config(db, body.config, mcp_manager)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, detail={"code": "invalid_json", "message": str(e)}) from e
    await _maybe_reload_hermes(db)
    return {"ok": True, "changes": count, "path": str(mcp_config_path())}


@router.get("/presets/template")
async def get_preset_template():
    """返回预置 MCP 的 JSON 配置模板（Cursor/Claude mcpServers 格式）。"""
    return preset_json_template()


@router.get("/servers")
async def list_servers(db: aiosqlite.Connection = Depends(db_dep)):
    rows = await mcp_manager.list_servers(db)
    return {"items": [_row_to_item(dict(r)) for r in rows]}


@router.get("/servers/{server_id}")
async def get_server(server_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
    row = await cur.fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "not_found", "message": "server not found"})
    return _row_to_item(dict(row))


async def _maybe_reload_hermes(db: aiosqlite.Connection) -> None:
    try:
        from app.hermes_bridge.lifecycle import hermes_available, reload_mcp_from_db

        if hermes_available():
            await reload_mcp_from_db(db)
    except Exception:  # noqa: BLE001
        pass


def _reload_hermes_in_background() -> None:
    """OAuth 回调里不要阻塞浏览器/轮询：MCP 冷启动放到后台。"""

    async def _run() -> None:
        from app.db.database import get_db

        db_conn = await get_db()
        try:
            await _maybe_reload_hermes(db_conn)
        except Exception:  # noqa: BLE001
            logger.debug("feishu oauth background hermes reload failed", exc_info=True)
        finally:
            await db_conn.close()

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        logger.debug("no running loop for hermes reload")


@router.post("/servers")
async def create_server(body: McpIn, db: aiosqlite.Connection = Depends(db_dep)):
    data = await mcp_manager.create_server(db, body.model_dump())
    await _maybe_reload_hermes(db)
    cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (data["id"],))
    row = await cur.fetchone()
    return _row_to_item(dict(row))


@router.post("/servers/import")
async def import_servers(body: McpImportBody, db: aiosqlite.Connection = Depends(db_dep)):
    try:
        entries = parse_mcp_import(body.config)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, detail={"code": "invalid_json", "message": str(e)}) from e
    created = []
    for entry in entries:
        data = await mcp_manager.create_server(db, entry)
        cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (data["id"],))
        row = await cur.fetchone()
        if row:
            created.append(_row_to_item(dict(row)))
    await _maybe_reload_hermes(db)
    return {"items": created, "count": len(created)}


@router.patch("/servers/{server_id}")
async def patch_server(server_id: str, body: McpPatch, db: aiosqlite.Connection = Depends(db_dep)):
    data = await mcp_manager.update_server(db, server_id, body.model_dump(exclude_unset=True))
    if not data:
        raise HTTPException(404, detail={"code": "not_found", "message": "server not found"})
    await _maybe_reload_hermes(db)
    return _row_to_item(data)


@router.delete("/servers/{server_id}")
async def delete_server(server_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    await mcp_manager.delete_server(db, server_id)
    await _maybe_reload_hermes(db)
    return {"ok": True}


@router.post("/servers/{server_id}/test")
async def test_server(server_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    return await mcp_manager.test_server(db, server_id)


@router.post("/servers/{server_id}/discover")
async def discover_server(server_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    tools = await mcp_manager.discover(db, server_id)
    return {"tools": tools}


class ToolsPolicyBody(BaseModel):
    tools_policy: dict


@router.put("/servers/{server_id}/tools-policy")
async def put_tools_policy(
    server_id: str,
    body: ToolsPolicyBody,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """持久化 per-server include/exclude/resources/prompts。"""
    data = await mcp_manager.update_server(db, server_id, {"tools_policy": body.tools_policy})
    if not data:
        raise HTTPException(404, detail={"code": "not_found", "message": "server not found"})
    return _row_to_item(data)


@router.post("/reload")
async def reload_mcp(db: aiosqlite.Connection = Depends(db_dep)):
    """重新向 Hermes 注册全部 MCP。"""
    from app.hermes_bridge.lifecycle import get_bridge_status, reload_mcp_from_db

    names = await reload_mcp_from_db(db)
    return {"ok": True, "tools": names, "hermes": get_bridge_status()}


@router.get("/hermes-status")
async def mcp_hermes_status():
    from app.hermes_bridge.lifecycle import get_bridge_status

    return get_bridge_status()


class FeishuOAuthStartBody(BaseModel):
    scopes: str | None = None
    app_id: str | None = None
    app_secret: str | None = None


@router.post("/servers/{server_id}/feishu-oauth/start")
async def feishu_oauth_start(
    server_id: str,
    body: FeishuOAuthStartBody | None = None,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """发起飞书 OAuth（浏览器授权，localhost 临时回调，与 lark-mcp login 一致）。"""
    if server_id != FEISHU_PRESET_ID and "feishu" not in server_id.lower():
        raise HTTPException(400, detail={"code": "not_feishu", "message": "仅飞书连接器支持 OAuth"})
    _, env = await _load_server_env(db, server_id)
    from app.integrations.feishu_oauth import set_feishu_oauth_success_handler, start_feishu_oauth

    body = body or FeishuOAuthStartBody()
    app_id = str(body.app_id or env.get("APP_ID") or env.get("FEISHU_APP_ID") or "").strip()
    app_secret = str(body.app_secret or env.get("APP_SECRET") or env.get("FEISHU_APP_SECRET") or "").strip()
    # 只写 env，不要走 PATCH/update_server：那会 shutdown + 重注册全部 MCP，授权页要等十几秒。
    env_changed = False
    if app_id and env.get("APP_ID") != app_id:
        env["APP_ID"] = app_id
        env_changed = True
    if app_secret and env.get("APP_SECRET") != app_secret:
        env["APP_SECRET"] = app_secret
        env_changed = True
    if env_changed:
        await _save_server_env(db, server_id, env)

    async def _persist(pending) -> None:
        from app.db.database import get_db

        db_conn = await get_db()
        try:
            _, cur_env = await _load_server_env(db_conn, pending.server_id)
            cur_env["USER_ACCESS_TOKEN"] = pending.access_token
            if pending.refresh_token:
                cur_env["REFRESH_USER_ACCESS_TOKEN"] = pending.refresh_token
            await _save_server_env(db_conn, pending.server_id, cur_env)
            pending.saved_to_db = True
            pending.message = "授权成功，已写入连接器"
        finally:
            await db_conn.close()
        _reload_hermes_in_background()

    set_feishu_oauth_success_handler(_persist)
    try:
        return await start_feishu_oauth(
            server_id=server_id,
            app_id=app_id,
            app_secret=app_secret,
            scopes=body.scopes,
        )
    except ValueError as e:
        raise HTTPException(400, detail={"code": "invalid_config", "message": str(e)}) from e
    except RuntimeError as e:
        raise HTTPException(503, detail={"code": "oauth_port_busy", "message": str(e)}) from e


@router.get("/servers/{server_id}/feishu-oauth/status")
async def feishu_oauth_status(server_id: str, state: str):
    from app.integrations.feishu_oauth import get_feishu_oauth_status

    data = get_feishu_oauth_status(state)
    return {"server_id": server_id, **data}


@router.post("/servers/{server_id}/feishu-oauth/apply")
async def feishu_oauth_apply(
    server_id: str,
    state: str,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """授权成功后，将 token 写入连接器 env。"""
    from app.integrations.feishu_oauth import get_feishu_oauth_status, pop_oauth_tokens

    status = get_feishu_oauth_status(state)
    if status.get("status") != "success":
        raise HTTPException(
            400,
            detail={"code": "not_ready", "message": status.get("message") or "授权尚未完成"},
        )
    tokens = pop_oauth_tokens(state)
    if not tokens:
        raise HTTPException(400, detail={"code": "no_token", "message": "未找到授权 token"})
    _, env = await _load_server_env(db, server_id)
    env.update({k: v for k, v in tokens.items() if v})
    await _save_server_env(db, server_id, env)
    await _maybe_reload_hermes(db)
    masked = tokens.get("USER_ACCESS_TOKEN", "")
    if len(masked) > 8:
        masked = masked[:4] + "…" + masked[-4:]
    return {"ok": True, "token_preview": masked, "has_refresh": bool(tokens.get("REFRESH_USER_ACCESS_TOKEN"))}
