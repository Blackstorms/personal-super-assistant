"""上下文用量估算。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.agent.compress import categorize_context_tokens, estimate_tokens


def test_estimate_tokens_nonempty():
    n = estimate_tokens("你好世界 hello")
    assert n >= 1


def _prepare_db(subdir: str) -> Path:
    data = Path(__file__).resolve().parent / ".testdata" / subdir
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    return data


@pytest.mark.asyncio
async def test_estimate_session_context():
    _prepare_db("context-usage")
    from app.agent.compress import estimate_session_context
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        sid = str(uuid.uuid4())
        now = utc_now()
        await db.execute(
            "INSERT INTO sessions(id, title, message_count, created_at, updated_at) VALUES(?,?,?,?,?)",
            (sid, "t", 0, now, now),
        )
        await db.execute(
            """
            INSERT INTO messages(id, session_id, role, content, created_at)
            VALUES(?,?,?,?,?)
            """,
            (str(uuid.uuid4()), sid, "user", "hello " * 50, now),
        )
        await db.commit()
        usage = await estimate_session_context(db, sid)
        assert usage["used_tokens"] >= 1
        assert usage["limit_tokens"] >= 1
        assert 0 <= usage["percent"] <= 100
        assert usage["message_count"] == 1
        assert usage["compressed"] is False
        assert "breakdown" in usage
        assert usage["breakdown"]["conversation"] >= 1
    finally:
        await db.close()


def test_categorize_context_tokens_splits_tools_and_mcp():
    msgs = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "t1", "function": {"name": "fs_read"}},
                {"id": "t2", "function": {"name": "mcp__abcd1234__list"}},
            ],
        },
        {"role": "tool", "tool_call_id": "t1", "content": "file"},
        {"role": "tool", "tool_call_id": "t2", "content": "mcp-ok"},
        {"role": "system", "content": "[Conversation summary]\nolder chat"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "t3", "function": {"name": "describe_skill"}}],
        },
        {"role": "tool", "tool_call_id": "t3", "content": "skill md"},
    ]
    b = categorize_context_tokens(msgs)
    assert b["conversation"] >= 1
    assert b["tools"] >= 1
    assert b["mcp"] >= 1
    assert b["skills"] >= 1
    assert b["system_prompt"] >= 1
