"""
Hermes 生命周期：启动注册 MCP、关闭 teardown；对外状态查询。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_state: dict[str, Any] = {
    "available": False,
    "root": None,
    "home": None,
    "mcp_tools": [],
    "mcp_tools_count": 0,
    "error": None,
    "model_tools_loaded": False,
    "missing_deps": [],
}


def hermes_available() -> bool:
    return bool(_state.get("available"))


def get_bridge_status() -> dict[str, Any]:
    out = dict(_state)
    out["mcp_tools_count"] = len(out.get("mcp_tools") or [])
    return out


async def _persist_last_error(db: Any | None, error: str | None) -> None:
    if db is None:
        return
    try:
        from app.db.database import save_setting

        await save_setting(
            db,
            "hermes_last_error",
            {"error": error, "available": bool(_state.get("available"))},
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("persist hermes_last_error failed: %s", e)


async def startup_hermes(db: Any | None = None) -> dict[str, Any]:
    """
    应用启动：sys.path + 试导入 model_tools + 从 DB 注册 MCP。
    db 可为 aiosqlite 连接；失败不抛，仅写状态。
    """
    from app.hermes_bridge.paths import (
        diagnose_missing_deps,
        ensure_hermes_on_syspath,
        hermes_home,
        hermes_root,
    )

    root = hermes_root()
    _state["root"] = str(root) if root else None
    _state["home"] = str(hermes_home())
    _state["error"] = None
    _state["missing_deps"] = []
    _state["mcp_tools"] = []
    _state["mcp_tools_count"] = 0

    if not ensure_hermes_on_syspath():
        _state["available"] = False
        _state["missing_deps"] = ["vendored_hermes"]
        _state["error"] = (
            f"vendored Hermes missing: {root}. "
            "Expect third_party/hermes-agent (model_tools.py + tools/) inside the project."
        )
        logger.warning(_state["error"])
        await _persist_last_error(db, _state["error"])
        return get_bridge_status()

    missing = await asyncio.to_thread(diagnose_missing_deps)
    missing = [m for m in missing if m != "vendored_hermes"]
    _state["missing_deps"] = missing

    def _boot_imports() -> None:
        import model_tools  # noqa: F401  # type: ignore

    try:
        await asyncio.to_thread(_boot_imports)
        _state["model_tools_loaded"] = True
        _state["available"] = True
    except Exception as e:  # noqa: BLE001
        _state["available"] = False
        _state["model_tools_loaded"] = False
        _state["error"] = f"import model_tools failed: {e}"
        if missing:
            _state["error"] += f"; missing_deps={missing}"
        logger.warning(_state["error"])
        await _persist_last_error(db, _state["error"])
        return get_bridge_status()

    if db is not None:
        try:
            await reload_mcp_from_db(db)
        except Exception as e:  # noqa: BLE001
            logger.warning("MCP register on startup failed: %s", e)
            _state["error"] = f"mcp register: {e}"

    await _persist_last_error(db, _state.get("error"))
    return get_bridge_status()


async def reload_mcp_from_db(db: Any) -> list[str]:
    """shutdown 后按 DB 重新 register_mcp_servers。"""
    from app.hermes_bridge.config_mapper import load_mcp_servers_dict
    from app.hermes_bridge.paths import ensure_hermes_on_syspath

    if not ensure_hermes_on_syspath() or not _state.get("model_tools_loaded"):
        return []

    servers = await load_mcp_servers_dict(db)
    clean = {}
    for k, v in servers.items():
        cfg = {kk: vv for kk, vv in v.items() if not str(kk).startswith("_")}
        clean[k] = cfg

    def _register() -> list[str]:
        try:
            from tools.mcp_tool import register_mcp_servers, shutdown_mcp_servers  # type: ignore

            shutdown_mcp_servers()
            return list(register_mcp_servers(clean) or [])
        except Exception as e:  # noqa: BLE001
            logger.warning("register_mcp_servers failed: %s", e)
            return []

    names = await asyncio.to_thread(_register)
    _state["mcp_tools"] = names
    _state["mcp_tools_count"] = len(names)
    try:
        await _sync_tools_cache(db, names)
    except Exception as e:  # noqa: BLE001
        logger.debug("sync tools cache failed: %s", e)
    return names


def _registry_tool_schema(full_name: str) -> tuple[str, dict]:
    """从 Hermes registry 取 description + input schema。"""
    try:
        from tools.registry import registry  # type: ignore

        defs = []
        if hasattr(registry, "get_definitions"):
            defs = registry.get_definitions({full_name}, quiet=True) or []
        if defs:
            fn = (defs[0].get("function") or {})
            return str(fn.get("description") or full_name), dict(fn.get("parameters") or {})
        tools = getattr(registry, "tools", None) or {}
        meta = tools.get(full_name) or {}
        if isinstance(meta, dict):
            return str(meta.get("description") or full_name), dict(meta.get("parameters") or meta.get("schema") or {})
    except Exception as e:  # noqa: BLE001
        logger.debug("registry schema for %s: %s", full_name, e)
    return full_name, {}


async def _sync_tools_cache(db: Any, tool_names: list[str]) -> None:
    """将 Hermes 已注册 mcp__ 工具写入 mcp_tools_cache（含完整 schema）。"""
    from app.db.database import utc_now
    from app.hermes_bridge.config_mapper import hermes_server_key

    cur = await db.execute("SELECT * FROM mcp_servers")
    rows = [dict(r) for r in await cur.fetchall()]
    key_to_id = {hermes_server_key(r): r["id"] for r in rows}

    await db.execute("DELETE FROM mcp_tools_cache")
    for full_name in tool_names:
        if not full_name.startswith("mcp__"):
            continue
        parts = full_name.split("__", 2)
        if len(parts) < 3:
            continue
        server_key, tool_name = parts[1], parts[2]
        sid = key_to_id.get(server_key)
        if not sid:
            for k, vid in key_to_id.items():
                if k.endswith(server_key) or server_key.endswith(k.split("_")[-1]):
                    sid = vid
                    break
        if not sid:
            continue
        desc, schema = await asyncio.to_thread(_registry_tool_schema, full_name)
        await db.execute(
            """
            INSERT INTO mcp_tools_cache(id, server_id, name, description, input_schema_json, discovered_at)
            VALUES(?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4()),
                sid,
                tool_name,
                desc or full_name,
                json.dumps(schema or {}, ensure_ascii=False),
                utc_now(),
            ),
        )
    await db.commit()


async def discover_one_server(db: Any, server_id: str) -> list[dict]:
    """重新注册全部 MCP 后返回指定 server 的工具列表（含完整 schema）。"""
    await reload_mcp_from_db(db)
    cur = await db.execute(
        "SELECT name, description, input_schema_json FROM mcp_tools_cache WHERE server_id=?",
        (server_id,),
    )
    rows = await cur.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "name": r["name"],
                "description": r["description"] or "",
                "input_schema": json.loads(r["input_schema_json"] or "{}"),
            }
        )
    return out


async def shutdown_hermes() -> None:
    if not _state.get("available"):
        return

    def _shutdown() -> None:
        try:
            from tools.mcp_tool import shutdown_mcp_servers  # type: ignore

            shutdown_mcp_servers()
        except Exception as e:  # noqa: BLE001
            logger.debug("shutdown_mcp_servers: %s", e)

    try:
        await asyncio.to_thread(_shutdown)
    except Exception:  # noqa: BLE001
        pass
    _state["mcp_tools"] = []
    _state["mcp_tools_count"] = 0
