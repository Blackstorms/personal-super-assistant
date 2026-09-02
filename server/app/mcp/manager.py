"""
MCP 客户端管理（stdio 优先，可选 http/sse）。

对齐 deer-flow MCP 边界（自写，不用 langchain-mcp-adapters）：
- 配置持久化在 mcp_servers 表
- Discover 结果缓存到 mcp_tools_cache
- 工具名 mcp__{sid8}__{name}，进程内维护 sid8 → 完整 UUID
- stdio 会话池复用 ClientSession
- call_tool 真实执行；输出受字符预算截断
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import AsyncExitStack
from typing import Any

import aiosqlite

from app.agent.budget import truncate_tool_result
from app.db.database import utc_now


def short_server_id(server_id: str) -> str:
    """OpenAI function 名用的短 hash（去横线前 8 位）。"""
    return server_id.replace("-", "")[:8]


class MCPManager:
    """轻量 MCP 管理器：会话池 + Discover + 真实 call_tool。"""

    def __init__(self) -> None:
        # sid8 -> full UUID（openai_tools / 过滤 / 执行共用）
        self._sid8_to_full: dict[str, str] = {}
        # server_id -> 持久会话状态
        self._sessions: dict[str, dict[str, Any]] = {}

    def resolve_server_id(self, sid_or_short: str) -> str:
        """把短 hash 或完整 UUID 解析为完整 server id。"""
        if sid_or_short in self._sid8_to_full:
            return self._sid8_to_full[sid_or_short]
        # 完整 UUID 直接返回；同时登记映射
        if len(sid_or_short) > 8:
            self._sid8_to_full[short_server_id(sid_or_short)] = sid_or_short
            return sid_or_short
        # 反查：可能还未登记，遍历已知映射
        for s8, full in self._sid8_to_full.items():
            if s8 == sid_or_short:
                return full
        return sid_or_short

    def register_server_id(self, server_id: str) -> str:
        s8 = short_server_id(server_id)
        self._sid8_to_full[s8] = server_id
        return s8

    async def list_servers(self, db: aiosqlite.Connection) -> list[dict]:
        cur = await db.execute("SELECT * FROM mcp_servers ORDER BY created_at")
        rows = await cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            self.register_server_id(d["id"])
            out.append(d)
        return out

    async def create_server(
        self,
        db: aiosqlite.Connection,
        payload: dict,
        *,
        server_id: str | None = None,
    ) -> dict:
        sid = server_id or str(uuid.uuid4())
        now = utc_now()
        await db.execute(
            """
            INSERT INTO mcp_servers(
              id, name, transport, command, args_json, env_json, url,
              headers_json, tools_policy_json, timeout, connect_timeout,
              supports_parallel, auth_type,
              enabled, created_at, updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sid,
                payload["name"],
                payload.get("transport", "stdio"),
                payload.get("command"),
                json.dumps(payload.get("args") or [], ensure_ascii=False),
                json.dumps(payload.get("env") or {}, ensure_ascii=False),
                payload.get("url"),
                json.dumps(payload.get("headers") or {}, ensure_ascii=False),
                json.dumps(payload.get("tools_policy") or payload.get("tools") or {}, ensure_ascii=False),
                payload.get("timeout"),
                payload.get("connect_timeout"),
                1 if payload.get("supports_parallel") else 0,
                payload.get("auth_type"),
                1 if payload.get("enabled", True) else 0,
                now,
                now,
            ),
        )
        await db.commit()
        self.register_server_id(sid)
        return {"id": sid, **payload, "enabled": payload.get("enabled", True)}

    async def update_server(self, db: aiosqlite.Connection, server_id: str, patch: dict) -> dict | None:
        cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        for k in ("name", "transport", "command", "url", "auth_type"):
            if k in patch:
                data[k] = patch[k]
        if "args" in patch:
            data["args_json"] = json.dumps(patch["args"], ensure_ascii=False)
        if "env" in patch:
            data["env_json"] = json.dumps(patch["env"], ensure_ascii=False)
        if "headers" in patch:
            data["headers_json"] = json.dumps(patch["headers"], ensure_ascii=False)
        if "tools_policy" in patch or "tools" in patch:
            data["tools_policy_json"] = json.dumps(
                patch.get("tools_policy") or patch.get("tools") or {},
                ensure_ascii=False,
            )
        if "timeout" in patch:
            data["timeout"] = patch["timeout"]
        if "connect_timeout" in patch:
            data["connect_timeout"] = patch["connect_timeout"]
        if "supports_parallel" in patch:
            data["supports_parallel"] = 1 if patch["supports_parallel"] else 0
        if "enabled" in patch:
            data["enabled"] = 1 if patch["enabled"] else 0
            if not patch["enabled"]:
                await self.close_session(server_id)
        await db.execute(
            """
            UPDATE mcp_servers SET
              name=?, transport=?, command=?, args_json=?, env_json=?, url=?,
              headers_json=?, tools_policy_json=?, timeout=?, connect_timeout=?,
              supports_parallel=?, auth_type=?,
              enabled=?, updated_at=?
            WHERE id=?
            """,
            (
                data["name"],
                data["transport"],
                data["command"],
                data["args_json"],
                data["env_json"],
                data["url"],
                data.get("headers_json"),
                data.get("tools_policy_json"),
                data.get("timeout"),
                data.get("connect_timeout"),
                data.get("supports_parallel") or 0,
                data.get("auth_type"),
                data["enabled"],
                utc_now(),
                server_id,
            ),
        )
        await db.commit()
        await self.close_session(server_id)
        self.register_server_id(server_id)
        # 配置变更后让 Hermes 重载
        try:
            from app.hermes_bridge.lifecycle import reload_mcp_from_db

            await reload_mcp_from_db(db)
        except Exception:  # noqa: BLE001
            pass
        return data

    async def delete_server(self, db: aiosqlite.Connection, server_id: str) -> bool:
        await self.close_session(server_id)
        await db.execute("DELETE FROM mcp_servers WHERE id=?", (server_id,))
        await db.commit()
        s8 = short_server_id(server_id)
        self._sid8_to_full.pop(s8, None)
        return True

    async def close_session(self, server_id: str) -> None:
        state = self._sessions.pop(server_id, None)
        if not state:
            return
        stack: AsyncExitStack | None = state.get("stack")
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def close_all(self) -> None:
        for sid in list(self._sessions.keys()):
            await self.close_session(sid)

    async def _load_row(self, db: aiosqlite.Connection, server_id: str) -> dict | None:
        cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def _ensure_session(self, db: aiosqlite.Connection, server_id: str) -> Any:
        """
        获取或创建 ClientSession。
        返回 session；失败抛异常（调用方转成可读错误）。
        """
        full_id = self.resolve_server_id(server_id)
        if full_id in self._sessions and self._sessions[full_id].get("session") is not None:
            return self._sessions[full_id]["session"]

        row = await self._load_row(db, full_id)
        if not row:
            raise ValueError(f"mcp server not found: {server_id}")

        from mcp import ClientSession, StdioServerParameters  # type: ignore

        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            transport = row["transport"]
            if transport == "stdio":
                from mcp.client.stdio import stdio_client  # type: ignore

                if not row["command"]:
                    raise ValueError("stdio requires command")
                args = json.loads(row["args_json"] or "[]")
                env = json.loads(row["env_json"] or "{}")
                params = StdioServerParameters(
                    command=row["command"],
                    args=args,
                    env=env or None,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif transport in ("sse", "http"):
                if not row["url"]:
                    raise ValueError(f"{transport} requires url")
                if transport == "sse":
                    from mcp.client.sse import sse_client  # type: ignore

                    read, write = await stack.enter_async_context(sse_client(row["url"]))
                else:
                    from mcp.client.streamable_http import streamablehttp_client  # type: ignore

                    # streamablehttp_client 返回 (read, write, get_session_id)
                    trio = await stack.enter_async_context(streamablehttp_client(row["url"]))
                    read, write = trio[0], trio[1]
            else:
                raise ValueError(f"unsupported transport: {transport}")

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[full_id] = {"session": session, "stack": stack}
            self.register_server_id(full_id)
            return session
        except Exception:
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._sessions.pop(full_id, None)
            raise

    async def test_server(self, db: aiosqlite.Connection, server_id: str) -> dict:
        """优先走 Hermes 重载探测；失败回退自研会话。"""
        t0 = time.perf_counter()
        try:
            from app.hermes_bridge.lifecycle import hermes_available, reload_mcp_from_db

            if hermes_available():
                names = await reload_mcp_from_db(db)
                from app.hermes_bridge.config_mapper import hermes_server_key

                cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
                row = await cur.fetchone()
                if not row:
                    return {"ok": False, "message": "not found", "latency_ms": 0}
                key = hermes_server_key(dict(row))
                matched = [n for n in names if n.startswith(f"mcp__{key}__") or f"__{key}__" in n]
                latency = int((time.perf_counter() - t0) * 1000)
                if bool(row["enabled"]):
                    return {
                        "ok": True,
                        "message": f"hermes registered tools={len(matched) or len(names)}",
                        "latency_ms": latency,
                        "via": "hermes",
                    }
                return {"ok": False, "message": "disabled", "latency_ms": latency}
        except Exception:  # noqa: BLE001
            pass

        cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
        row = await cur.fetchone()
        if not row:
            return {"ok": False, "message": "not found", "latency_ms": 0}
        if row["transport"] == "stdio" and not row["command"]:
            return {"ok": False, "message": "stdio requires command", "latency_ms": 0}
        if row["transport"] in ("sse", "http") and not row["url"]:
            return {"ok": False, "message": "url required", "latency_ms": 0}

        t0 = time.perf_counter()
        try:
            await self.close_session(server_id)
            session = await self._ensure_session(db, server_id)
            await session.list_tools()
            latency = int((time.perf_counter() - t0) * 1000)
            return {"ok": True, "message": "connected", "latency_ms": latency, "via": "legacy"}
        except ImportError as e:
            return {
                "ok": False,
                "message": f"mcp SDK not installed: {e}",
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "message": str(e),
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            }

    async def discover(self, db: aiosqlite.Connection, server_id: str) -> list[dict]:
        """优先 Hermes discover；失败回退自研 list_tools。"""
        try:
            from app.hermes_bridge.lifecycle import discover_one_server, hermes_available

            if hermes_available():
                tools = await discover_one_server(db, server_id)
                if tools:
                    return tools
        except Exception:  # noqa: BLE001
            pass

        cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,))
        row = await cur.fetchone()
        if not row:
            return []
        tools: list[dict] = []
        try:
            session = await self._ensure_session(db, server_id)
            listed = await session.list_tools()
            for t in listed.tools:
                tools.append(
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": getattr(t, "inputSchema", None) or {},
                    }
                )
        except Exception:  # noqa: BLE001
            tools = []

        await db.execute("DELETE FROM mcp_tools_cache WHERE server_id=?", (server_id,))
        for t in tools:
            await db.execute(
                """
                INSERT INTO mcp_tools_cache(id, server_id, name, description, input_schema_json, discovered_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    server_id,
                    t["name"],
                    t.get("description"),
                    json.dumps(t.get("input_schema") or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )
        await db.commit()
        self.register_server_id(server_id)
        return tools

    async def openai_tools(
        self, db: aiosqlite.Connection, *, prefer_hermes: bool = True
    ) -> list[dict]:
        """prefer_hermes=True 时可读 Hermes tool_surface；对话热路径应传 False，由 bridge 独占。"""
        if prefer_hermes:
            try:
                from app.hermes_bridge.lifecycle import hermes_available
                from app.hermes_bridge.tool_surface import get_openai_tools

                if hermes_available():
                    tools = await get_openai_tools(include_skills=False, include_mcp=True)
                    mcp_only = [
                        t
                        for t in tools
                        if ((t.get("function") or {}).get("name") or "").startswith("mcp__")
                    ]
                    if mcp_only:
                        return mcp_only
            except Exception:  # noqa: BLE001
                pass

        cur = await db.execute(
            """
            SELECT s.id as server_id, c.name, c.description, c.input_schema_json,
                   s.tools_policy_json
            FROM mcp_tools_cache c
            JOIN mcp_servers s ON s.id = c.server_id
            WHERE s.enabled = 1
            """
        )
        rows = await cur.fetchall()
        out = []
        for r in rows:
            safe_sid = self.register_server_id(r["server_id"])
            fname = f"mcp__{safe_sid}__{r['name']}"
            schema = json.loads(r["input_schema_json"] or "{}")
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": fname,
                        "description": r["description"] or r["name"],
                        "parameters": schema if schema else {"type": "object", "properties": {}},
                    },
                }
            )
        from app.hermes_bridge.config_mapper import filter_tools_policy

        by_server: dict[str, list] = {}
        for r, tool in zip(rows, out):
            by_server.setdefault(r["server_id"], []).append((r, tool))
        filtered: list[dict] = []
        for _sid, pairs in by_server.items():
            policy = json.loads((pairs[0][0]["tools_policy_json"] or "{}") if pairs else "{}")
            tools = [p[1] for p in pairs]
            filtered.extend(filter_tools_policy(tools, policy))
        return filtered if filtered else out

    def filter_openai_tools(self, tools: list[dict], mcp_ids: list[str] | None) -> list[dict]:
        """按完整 UUID / sid8 / Hermes server key 过滤 mcp__*。"""
        if mcp_ids is None:
            return tools
        if len(mcp_ids) == 0:
            return [t for t in tools if not ((t.get("function") or {}).get("name") or "").startswith("mcp__")]
        allowed: set[str] = set()
        for mid in mcp_ids:
            full = self.resolve_server_id(mid)
            allowed.add(short_server_id(full))
            allowed.add(mid)
            self.register_server_id(full)
        out = []
        for t in tools:
            name = (t.get("function") or {}).get("name") or ""
            if not name.startswith("mcp__"):
                out.append(t)
                continue
            parts = name.split("__", 2)
            if len(parts) < 2:
                continue
            server_part = parts[1]
            if server_part in allowed:
                out.append(t)
                continue
            for ak in allowed:
                if server_part.endswith(ak) or ak in server_part:
                    out.append(t)
                    break
        return out

    async def call_tool(
        self,
        db: aiosqlite.Connection,
        server_id: str,
        tool_name: str,
        arguments: dict,
        *,
        prefer_hermes: bool = True,
    ) -> Any:
        """prefer_hermes=True 时优先 Hermes；降级路径传 False 只用官方 SDK。"""
        full_id = self.resolve_server_id(server_id)
        if prefer_hermes:
            try:
                from app.hermes_bridge.config_mapper import hermes_server_key
                from app.hermes_bridge.dispatch import dispatch_hermes_tool
                from app.hermes_bridge.lifecycle import hermes_available

                if hermes_available():
                    cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (full_id,))
                    row = await cur.fetchone()
                    if row:
                        key = hermes_server_key(dict(row))
                        fname = (
                            tool_name
                            if tool_name.startswith("mcp__")
                            else f"mcp__{key}__{tool_name}"
                        )
                        return await dispatch_hermes_tool(fname, arguments or {})
            except Exception:  # noqa: BLE001
                pass

        try:
            session = await self._ensure_session(db, full_id)
            result = await session.call_tool(tool_name, arguments or {})
            content_out: list[Any] = []
            for block in getattr(result, "content", None) or []:
                btype = getattr(block, "type", None) or "text"
                if btype == "text":
                    content_out.append({"type": "text", "text": getattr(block, "text", str(block))})
                else:
                    content_out.append({"type": btype, "data": str(block)})
            payload = {
                "content": content_out,
                "isError": bool(getattr(result, "isError", False)),
            }
            return truncate_tool_result(payload)
        except ImportError as e:
            return {"error": f"mcp SDK not installed: {e}", "server_id": full_id, "tool": tool_name}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e), "server_id": full_id, "tool": tool_name, "arguments": arguments}


mcp_manager = MCPManager()
