"""MCP：sid8 映射、工具过滤、输出截断（不依赖外部 npx）。"""

from __future__ import annotations

import json

import pytest

from app.agent.budget import truncate_tool_result
from app.mcp.manager import MCPManager, short_server_id


def test_short_server_id_mapping():
    mgr = MCPManager()
    full = "abcdef12-3456-7890-abcd-ef1234567890"
    s8 = mgr.register_server_id(full)
    assert s8 == short_server_id(full)
    assert len(s8) == 8
    assert mgr.resolve_server_id(s8) == full
    assert mgr.resolve_server_id(full) == full


def test_filter_openai_tools_by_uuid():
    mgr = MCPManager()
    full = "11111111-2222-3333-4444-555555555555"
    s8 = mgr.register_server_id(full)
    other = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mgr.register_server_id(other)
    tools = [
        {"type": "function", "function": {"name": f"mcp__{s8}__list", "description": "x", "parameters": {}}},
        {
            "type": "function",
            "function": {
                "name": f"mcp__{short_server_id(other)}__read",
                "description": "y",
                "parameters": {},
            },
        },
        {"type": "function", "function": {"name": "fs_read", "description": "z", "parameters": {}}},
    ]
    filtered = mgr.filter_openai_tools(tools, [full])
    names = [t["function"]["name"] for t in filtered]
    assert f"mcp__{s8}__list" in names
    assert f"mcp__{short_server_id(other)}__read" not in names
    assert "fs_read" in names


def test_truncate_tool_result():
    big = {"data": "x" * 20000}
    out = truncate_tool_result(big, max_chars=100)
    assert isinstance(out, dict)
    assert out.get("_truncated") is True
    assert out["original_chars"] > 100


@pytest.mark.asyncio
async def test_call_tool_without_sdk_or_server(tmp_path, monkeypatch):
    """无真实 server 时 call_tool 返回 error，不抛崩。"""
    import os
    from pathlib import Path

    data = Path(__file__).resolve().parent / ".testdata" / "mcp"
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    from app.db.database import get_db, init_db

    await init_db()
    db = await get_db()
    mgr = MCPManager()
    try:
        created = await mgr.create_server(
            db,
            {
                "name": "fake",
                "transport": "stdio",
                "command": "/nonexistent/cmd",
                "args": [],
                "enabled": True,
            },
        )
        result = await mgr.call_tool(db, created["id"], "noop", {})
        assert "error" in result
    finally:
        await db.close()
        await mgr.close_all()
