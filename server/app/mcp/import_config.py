"""解析 Claude/Cursor 风格的 MCP JSON 配置。"""

from __future__ import annotations

import json
from typing import Any


def parse_mcp_import(raw: str | dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """
    支持格式：
    1. { "mcpServers": { "name": { command, args, env, url } } }
    2. { "name", "command", "args", "env", "url", "transport" }
    3. [ { ... }, ... ]
    """
    if isinstance(raw, str):
        raw = json.loads(raw.strip())
    if not isinstance(raw, (dict, list)):
        raise ValueError("MCP 配置必须是 JSON 对象或数组")

    servers: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"第 {i + 1} 项必须是对象")
            name = str(item.get("name") or item.get("id") or f"mcp-{i + 1}")
            servers.append(_normalize_entry(name, item))
        return servers

    if "mcpServers" in raw and isinstance(raw["mcpServers"], dict):
        for name, cfg in raw["mcpServers"].items():
            if not isinstance(cfg, dict):
                raise ValueError(f"mcpServers.{name} 必须是对象")
            servers.append(_normalize_entry(str(name), cfg))
        return servers

    if "command" in raw or "url" in raw:
        name = str(raw.get("name") or "imported-mcp")
        return [_normalize_entry(name, raw)]

    raise ValueError("无法识别的 MCP JSON：需要 mcpServers、command/url 或数组格式")


def _normalize_entry(name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
    enabled = cfg.get("enabled", True)
    display_name = str(cfg.get("name") or name)

    url = cfg.get("url")
    if url:
        transport = str(cfg.get("transport") or _guess_url_transport(str(url)))
        return {
            "name": display_name,
            "transport": transport,
            "command": None,
            "args": [],
            "env": env,
            "url": str(url),
            "enabled": bool(enabled),
        }

    command = cfg.get("command")
    if not command:
        raise ValueError(f"「{display_name}」缺少 command 或 url")

    args = cfg.get("args") or []
    if isinstance(args, str):
        args = args.split()
    if not isinstance(args, list):
        raise ValueError(f"「{display_name}」args 必须是数组")

    return {
        "name": display_name,
        "transport": str(cfg.get("transport") or "stdio"),
        "command": str(command),
        "args": [str(a) for a in args],
        "env": env,
        "url": None,
        "enabled": bool(enabled),
    }


def _guess_url_transport(url: str) -> str:
    lower = url.lower()
    if "/sse" in lower or lower.endswith("/sse"):
        return "sse"
    return "http"
