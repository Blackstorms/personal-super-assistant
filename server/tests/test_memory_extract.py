"""Memory：注入预算、规则抽取回退、LLM JSON 解析。"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from app.memory.service import _parse_extract_json, get_injection, extract_from_session


def test_parse_extract_json_plain():
    raw = json.dumps(
        {
            "items": [
                {"type": "preference", "content": "喜欢中文", "confidence": 0.9},
                {"type": "fact", "content": "项目叫 PSA", "confidence": 0.8},
            ]
        },
        ensure_ascii=False,
    )
    items = _parse_extract_json(raw)
    assert len(items) == 2
    assert items[0]["type"] == "preference"


def test_parse_extract_json_fenced():
    raw = '```json\n{"items":[{"type":"session_summary","content":"讨论了技能"}]}\n```'
    items = _parse_extract_json(raw)
    assert len(items) == 1
    assert items[0]["type"] == "session_summary"


def _prepare_db(subdir: str):
    data = Path(__file__).resolve().parent / ".testdata" / subdir
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    return data


@pytest.mark.asyncio
async def test_injection_budget_and_workspace():
    _prepare_db("mem-inject")
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        wid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO workspaces(id, name, status, created_at, updated_at) VALUES(?,?,?,?,?)",
            (wid, "W", "active", utc_now(), utc_now()),
        )
        mid = str(uuid.uuid4())
        content = "用户偏好：回复用中文简体"
        await db.execute(
            """
            INSERT INTO memories(id, workspace_id, type, content, tags_json, pinned, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (mid, wid, "preference", content, "[]", 1, utc_now(), utc_now()),
        )
        await db.commit()
        text, ids = await get_injection(db, "中文", wid, max_chars=500)
        assert mid in ids
        assert "<memory>" in text
        assert "中文" in text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_extract_rule_fallback():
    _prepare_db("mem-extract")
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        sid = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO sessions(id, title, message_count, created_at, updated_at) VALUES(?,?,?,?,?)",
            (sid, "S", 0, utc_now(), utc_now()),
        )
        await db.execute(
            """
            INSERT INTO messages(id, session_id, role, content, status, created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (str(uuid.uuid4()), sid, "user", "你好", "complete", utc_now()),
        )
        await db.execute(
            """
            INSERT INTO messages(id, session_id, role, content, status, created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (str(uuid.uuid4()), sid, "assistant", "你好，我是助理", "complete", utc_now()),
        )
        await db.commit()
        created = await extract_from_session(db, sid, llm=None)
        assert len(created) >= 1
        assert created[0]["type"] == "session_summary"
    finally:
        await db.close()
