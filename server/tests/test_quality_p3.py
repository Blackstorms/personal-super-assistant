"""P3 质量：风险表、FTS trigger、Hermes on/off、mini MCP stdio。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_TMP = str(Path(__file__).resolve().parent / ".testdata" / "quality")
Path(_TMP).mkdir(parents=True, exist_ok=True)
os.environ["PSA_DATA_DIR"] = _TMP


def test_risk_table_psa_and_hermes():
    from app.agent.risk import (
        HERMES_DANGEROUS_TOOLSETS,
        HERMES_HIGH_TOOLS,
        classify_risk,
    )

    assert classify_risk("fs_write", {}) == "high"
    assert classify_risk("schedule_task", {}) == "low"
    assert classify_risk("knowledge_search", {}) == "low"
    assert classify_risk("web_search", {}) == "low"
    assert classify_risk("current_time", {}) == "low"
    assert classify_risk("terminal", {}) == "high"
    assert classify_risk("execute_code", {}) == "high"
    assert classify_risk("skill_manage", {"action": "delete"}) == "high"
    assert classify_risk("skill_manage", {"action": "list"}) == "low"
    assert classify_risk("mcp__abcd1234__delete_file", {}) == "high"
    assert "terminal" in HERMES_DANGEROUS_TOOLSETS
    assert "write_file" in HERMES_HIGH_TOOLS


def test_dispatch_risk_delegates_to_table():
    from app.hermes_bridge.dispatch import classify_risk

    assert classify_risk("fs_write", {}) == "high"
    assert classify_risk("browser_navigate", {}) == "high"


@pytest.mark.asyncio
async def test_fts_triggers_sync_memories(tmp_path: Path, monkeypatch):
    from app.core.config import settings
    from app.db import database as dbmod

    data = tmp_path / "fts"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    await dbmod.init_db()
    db = await dbmod.get_db()
    try:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'memories_%'"
        )
        names = {r[0] for r in await cur.fetchall()}
        assert "memories_ai" in names
        assert "memories_ad" in names
        mid = "m1"
        now = dbmod.utc_now()
        await db.execute(
            """
            INSERT INTO memories(id, workspace_id, type, content, tags_json, pinned, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (mid, None, "fact", "触发器索引内容 hellofts", "[]", 0, now, now),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT content FROM memories_fts WHERE memories_fts MATCH 'hellofts'"
        )
        row = await cur.fetchone()
        assert row is not None
        assert "hellofts" in row[0]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_hermes_off_fallback_surface_no_bridge_dup(monkeypatch):
    """Hermes off：工具面走降级，不要求 Hub。"""
    import app.hermes_bridge.lifecycle as life
    from app.agent.tool_router import build_tool_surface
    from app.core.config import settings
    from app.db.database import get_db, init_db
    from app.skills.registry import SkillRegistry

    monkeypatch.setattr(life, "hermes_available", lambda: False)
    settings.data_dir = Path(_TMP) / "hermes_off"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    db = await get_db()
    try:
        reg = SkillRegistry(settings.data_dir / "skills")
        tools = await build_tool_surface(db, reg, enable_skills=True, enable_mcp=True)
        names = {
            ((t.get("function") or {}).get("name") or "")
            for t in tools
        }
        assert "fs_list" in names
        assert "fs_write" not in names  # 对话默认关闭写文件，避免卡确认
        assert "knowledge_search" in names
        assert "schedule_task" in names
        assert "web_search" in names
        assert "current_time" in names
        tools_w = await build_tool_surface(
            db, reg, enable_skills=False, enable_mcp=False, enable_fs_write=True
        )
        assert "fs_write" in {
            ((t.get("function") or {}).get("name") or "") for t in tools_w
        }
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_mini_mcp_stdio_create_and_list(tmp_path: Path, monkeypatch):
    """stdio MCP：可写入 SQLite 并列出；连接失败时 call 返回 error。"""
    from app.core.config import settings
    from app.db.database import get_db, init_db
    from app.mcp.manager import MCPManager

    data = tmp_path / "mcpstdio"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    await init_db()
    db = await get_db()
    mgr = MCPManager()
    try:
        created = await mgr.create_server(
            db,
            {
                "name": "mini-stdio",
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-c", "print('not-a-real-mcp')"],
                "enabled": True,
            },
        )
        rows = await mgr.list_servers(db)
        assert any(r["id"] == created["id"] for r in rows)
        # 非 MCP 进程：discover/call 应失败但不抛崩
        tools = await mgr.openai_tools(db, prefer_hermes=False)
        assert isinstance(tools, list)
        result = await mgr.call_tool(
            db, created["id"], "noop", {}, prefer_hermes=False
        )
        assert isinstance(result, dict)
        assert "error" in result or result.get("isError") or "content" in result
    finally:
        await db.close()
