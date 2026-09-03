"""
将 SQLite mcp_servers / 设置 翻译为 Hermes 期望的 mcp_servers dict。

Hermes 键为逻辑 server 名；本项目用 UUID id。映射：
- Hermes key = sanitize(name) 或 sid8，保证唯一
- 额外维护 name_key ↔ full UUID
"""

from __future__ import annotations

import json
import re
from typing import Any

import aiosqlite

from app.mcp.manager import short_server_id

_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def hermes_server_key(row: dict) -> str:
    """生成 Hermes mcp_servers 字典键。"""
    name = (row.get("name") or "").strip()
    slug = _SAFE.sub("_", name).strip("_").lower() if name else ""
    sid8 = short_server_id(str(row.get("id") or ""))
    if slug:
        return f"{slug}_{sid8}" if len(slug) < 3 else f"{slug[:48]}_{sid8}"
    return f"mcp_{sid8}"


def row_to_hermes_config(row: dict) -> dict[str, Any]:
    """单行 DB → Hermes server config。"""
    transport = (row.get("transport") or "stdio").lower()
    args = row.get("args")
    if args is None and row.get("args_json"):
        args = json.loads(row["args_json"] or "[]")
    env = row.get("env")
    if env is None and row.get("env_json"):
        env = json.loads(row["env_json"] or "{}")
    headers = row.get("headers")
    if headers is None and row.get("headers_json"):
        headers = json.loads(row["headers_json"] or "{}")
    policy = row.get("tools_policy")
    if policy is None and row.get("tools_policy_json"):
        policy = json.loads(row["tools_policy_json"] or "{}")

    cfg: dict[str, Any] = {
        "enabled": bool(row.get("enabled", True)),
    }
    if transport == "stdio":
        from app.mcp.lark_cmd import resolve_stdio_launch

        command, resolved_args = resolve_stdio_launch(
            str(row.get("command") or ""),
            list(args or []),
        )
        cfg["command"] = command
        cfg["args"] = resolved_args
        if env:
            cfg["env"] = dict(env)
    else:
        cfg["url"] = row.get("url") or ""
        if transport == "sse":
            cfg["transport"] = "sse"
        if headers:
            cfg["headers"] = dict(headers)

    if row.get("timeout") is not None:
        cfg["timeout"] = int(row["timeout"])
    if row.get("connect_timeout") is not None:
        cfg["connect_timeout"] = int(row["connect_timeout"])
    if row.get("supports_parallel"):
        cfg["supports_parallel_tool_calls"] = True
    auth_type = (row.get("auth_type") or "").strip()
    if auth_type:
        cfg["auth"] = auth_type
    if policy:
        cfg["tools"] = policy
    # 供 Bridge 反查
    cfg["_psa_server_id"] = row.get("id")
    return cfg


async def load_mcp_servers_dict(db: aiosqlite.Connection) -> dict[str, dict]:
    """加载全部启用/配置中的 MCP（含 disabled，由 Hermes enabled 字段处理）。"""
    cur = await db.execute("SELECT * FROM mcp_servers ORDER BY created_at")
    rows = await cur.fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        key = hermes_server_key(d)
        out[key] = row_to_hermes_config(d)
    return out


def filter_tools_policy(tools: list[dict], policy: dict | None) -> list[dict]:
    """按 include/exclude（支持简单 glob *）过滤 OpenAI tools。"""
    if not policy:
        return tools
    include = policy.get("include") or []
    exclude = policy.get("exclude") or []
    if isinstance(include, str):
        include = [include]
    if isinstance(exclude, str):
        exclude = [exclude]

    def _match(name: str, patterns: list) -> bool:
        import fnmatch

        for p in patterns:
            if fnmatch.fnmatch(name, str(p)):
                return True
        return False

    out = []
    for t in tools:
        fname = ((t.get("function") or {}).get("name") or "")
        # 取裸工具名（mcp__server__tool → tool）
        bare = fname.split("__")[-1] if "__" in fname else fname
        if include and not (_match(bare, include) or _match(fname, include)):
            continue
        if exclude and (_match(bare, exclude) or _match(fname, exclude)):
            continue
        out.append(t)
    return out
