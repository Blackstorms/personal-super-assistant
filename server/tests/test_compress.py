"""上下文压缩：成对保留、占位回退。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.agent.compress import find_keep_start, compress_history, fit_keep_window, _msg_tokens


def test_find_keep_start_pairs_tools():
    hist = [
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "function": {"name": "fs_read"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "{}"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "2"},
        {"role": "assistant", "content": "ok2"},
    ]
    # keep=2 → 从 user2 开始
    start = find_keep_start(hist, 2)
    assert start == 4
    # keep=4 → 原始起点落在 tool，应左移到带 tool_calls 的 assistant
    start4 = find_keep_start(hist, 4)
    assert hist[start4].get("role") == "assistant"
    assert hist[start4].get("tool_calls")
    assert start4 == 1


@pytest.mark.asyncio
async def test_compress_placeholder_without_llm():
    data = Path(__file__).resolve().parent / ".testdata" / "compress"
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        sid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO sessions(id, title, message_count, created_at, updated_at) VALUES(?,?,?,?,?)",
            (sid, "S", 0, utc_now(), utc_now()),
        )
        await db.commit()
        hist = [{"role": "user", "content": f"msg-{i}"} for i in range(30)]
        hist += [{"role": "assistant", "content": f"a-{i}"} for i in range(30)]
        projected, hints = await compress_history(
            db,
            sid,
            hist,
            compress_cfg={
                "max_messages": 10,
                "max_tokens": 100,
                "keep_messages": 4,
                "llm_summary": False,
            },
            llm=None,
        )
        assert hints["compressed"] is True
        assert any(
            m.get("role") == "system" and "summary" in (m.get("content") or "").lower()
            for m in projected
        )
        cur = await db.execute("SELECT summary_text FROM sessions WHERE id=?", (sid,))
        row = await cur.fetchone()
        assert row is not None
        assert row["summary_text"]
    finally:
        await db.close()


def test_fit_keep_window_stays_under_budget():
    """超长工具结果不得把保留窗口顶破 max_tokens。"""
    hist = [
        {"role": "user", "content": "read it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t1", "function": {"name": "fs_read", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "x" * 20000},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "next"},
    ]
    start, recent = fit_keep_window(hist, keep=16, max_tok=800)
    used = sum(_msg_tokens(m) for m in recent)
    assert used <= 800
    assert recent
    assert start >= 0


@pytest.mark.asyncio
async def test_compress_history_after_tokens_not_over_limit():
    data = Path(__file__).resolve().parent / ".testdata" / "compress-over"
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        sid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO sessions(id, title, message_count, created_at, updated_at) VALUES(?,?,?,?,?)",
            (sid, "S", 0, utc_now(), utc_now()),
        )
        await db.commit()
        hist = [
            {"role": "user", "content": "a"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "t1", "function": {"name": "fs_read"}}],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "tool-output " * 4000},
            {"role": "user", "content": "b"},
        ]
        projected, hints = await compress_history(
            db,
            sid,
            hist,
            compress_cfg={
                "max_messages": 40,
                "max_tokens": 800,
                "keep_messages": 16,
                "llm_summary": False,
            },
            llm=None,
        )
        assert hints["compressed"] is True
        assert hints["used_tokens"] <= 800
        assert sum(_msg_tokens(m) for m in projected) <= 800
    finally:
        await db.close()
