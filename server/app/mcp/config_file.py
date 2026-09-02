"""MCP 配置文件导出/同步（Cursor / Claude mcpServers 格式）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import aiosqlite

from app.core.config import settings
from app.mcp.import_config import parse_mcp_import
from app.mcp.manager import MCPManager, short_server_id

PRESET_KEY_BY_ID = {
    "preset-mcp-wecom": "wecom",
    "preset-mcp-feishu": "feishu",
    "preset-mcp-qqmail": "qqmail",
}
PRESET_ID_BY_KEY = {v: k for k, v in PRESET_KEY_BY_ID.items()}


def mcp_config_path() -> Path:
    return settings.data_dir / "mcp.json"


def _config_key(server_id: str, name: str) -> str:
    if server_id in PRESET_KEY_BY_ID:
        return PRESET_KEY_BY_ID[server_id]
    slug = re.sub(r"[^\w\-]", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or short_server_id(server_id)


def server_row_to_entry(row: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if row.get("url"):
        entry["url"] = row["url"]
        if row.get("transport") and row["transport"] != "stdio":
            entry["transport"] = row["transport"]
    else:
        entry["command"] = row["command"]
        args = json.loads(row.get("args_json") or "[]")
        if args:
            entry["args"] = args
    env = json.loads(row.get("env_json") or "{}")
    if env:
        entry["env"] = env
    if not row.get("enabled"):
        entry["disabled"] = True
    return entry


def export_mcp_config(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mcp_servers: dict[str, Any] = {}
    used_keys: set[str] = set()
    for row in rows:
        key = _config_key(str(row["id"]), str(row["name"]))
        if key in used_keys:
            key = f"{key}-{short_server_id(str(row['id']))}"
        used_keys.add(key)
        mcp_servers[key] = server_row_to_entry(row)
    return {"mcpServers": mcp_servers}


async def sync_mcp_config(db: aiosqlite.Connection, config: dict[str, Any], manager: MCPManager) -> int:
    """从完整 mcpServers JSON 同步到数据库；返回变更条目数。"""
    raw_servers = config.get("mcpServers")
    if not isinstance(raw_servers, dict):
        raise ValueError("配置需要 mcpServers 对象")

    rows = await manager.list_servers(db)
    by_id = {str(r["id"]): r for r in rows}
    by_name = {str(r["name"]): r for r in rows}
    custom_ids = {str(r["id"]) for r in rows if not str(r["id"]).startswith("preset-mcp-")}

    touched_custom: set[str] = set()
    changes = 0

    for key, cfg in raw_servers.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"mcpServers.{key} 必须是对象")
        entry = parse_mcp_import({"mcpServers": {key: cfg}})[0]
        preset_id = PRESET_ID_BY_KEY.get(str(key))

        if preset_id and preset_id in by_id:
            await manager.update_server(db, preset_id, entry)
            changes += 1
            continue

        existing = by_name.get(entry["name"])
        if existing and not str(existing["id"]).startswith("preset-mcp-"):
            await manager.update_server(db, str(existing["id"]), entry)
            touched_custom.add(str(existing["id"]))
            changes += 1
        else:
            created = await manager.create_server(db, entry)
            touched_custom.add(str(created["id"]))
            changes += 1

    for cid in custom_ids:
        if cid not in touched_custom:
            await manager.delete_server(db, cid)
            changes += 1

    path = mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changes


async def write_config_mirror(config: dict[str, Any]) -> Path:
    path = mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
