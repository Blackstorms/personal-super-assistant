"""schema 迁移 / user_version 黄金测试。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_TMP = str(Path(__file__).resolve().parent / ".testdata" / "migrate")
Path(_TMP).mkdir(parents=True, exist_ok=True)
os.environ["PSA_DATA_DIR"] = _TMP


@pytest.mark.asyncio
async def test_init_db_sets_user_version_and_pending_json(tmp_path: Path, monkeypatch):
    from app.core.config import settings
    from app.db import database as dbmod

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    # 重新指向 schema
    await dbmod.init_db()
    conn = await dbmod.get_db()
    try:
        cur = await conn.execute("PRAGMA user_version")
        row = await cur.fetchone()
        assert int(row[0]) == dbmod.SCHEMA_VERSION
        cols = await dbmod._column_names(conn, "chat_runs")
        assert "pending_json" in cols
        # scheduled_jobs / hermes_toolset_settings 应存在
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('scheduled_jobs','hermes_toolset_settings')"
        )
        names = {r[0] for r in await cur.fetchall()}
        assert "scheduled_jobs" in names
        assert "hermes_toolset_settings" in names
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('memories_ai','knowledge_chunks_ai')"
        )
        triggers = {r[0] for r in await cur.fetchall()}
        assert "memories_ai" in triggers
        assert "knowledge_chunks_ai" in triggers
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_estimate_tokens_uses_tiktoken_or_fallback():
    from app.agent.compress import estimate_tokens

    n = estimate_tokens("hello world 你好世界")
    assert n >= 1
    # 不应比字符数还大太多
    assert n < 100
