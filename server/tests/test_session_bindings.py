"""会话 composer 绑定持久化。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.agent.session_bindings import (
    normalize_bindings,
    parse_bindings_json,
    save_session_composer_bindings,
    session_row_with_bindings,
)


def test_normalize_and_parse_bindings():
    raw = normalize_bindings(
        expert_id="e1",
        skill_ids=["s1"],
        mcp_ids=["preset-mcp-feishu"],
        knowledge_ids=None,
        model_profile_id="m1",
    )
    assert raw["mcp_ids"] == ["preset-mcp-feishu"]
    assert raw["knowledge_ids"] is None
    parsed = parse_bindings_json(json.dumps(raw))
    assert parsed is not None
    assert parsed["mcp_ids"] == ["preset-mcp-feishu"]
    assert session_row_with_bindings(
        {"id": "x", "composer_bindings_json": json.dumps(raw)}
    )["composer_bindings"]["mcp_ids"] == ["preset-mcp-feishu"]


def _prepare_db(subdir: str) -> Path:
    data = Path(__file__).resolve().parent / ".testdata" / subdir
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    return data


@pytest.mark.asyncio
async def test_save_session_composer_bindings_roundtrip():
    _prepare_db("session-bindings")
    from app.db.database import get_db, init_db, utc_now
    import uuid

    await init_db()
    db = await get_db()
    try:
        cols = await db.execute("PRAGMA table_info(sessions)")
        names = {r[1] for r in await cols.fetchall()}
        assert "composer_bindings_json" in names

        sid = str(uuid.uuid4())
        now = utc_now()
        await db.execute(
            "INSERT INTO sessions(id, title, message_count, created_at, updated_at) VALUES(?,?,?,?,?)",
            (sid, "t", 0, now, now),
        )
        await db.commit()
        await save_session_composer_bindings(
            db,
            sid,
            {
                "expert_id": None,
                "skill_ids": [],
                "mcp_ids": ["preset-mcp-feishu"],
                "knowledge_ids": [],
                "model_profile_id": None,
            },
        )
        cur = await db.execute("SELECT * FROM sessions WHERE id=?", (sid,))
        row = session_row_with_bindings(dict(await cur.fetchone()))
        assert row["composer_bindings"]["mcp_ids"] == ["preset-mcp-feishu"]
    finally:
        await db.close()
