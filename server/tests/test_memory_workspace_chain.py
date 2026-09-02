"""项目内多会话上下文链：注入其他会话 session_summary / summary_text。"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app.memory.service import get_injection


def _prepare_db(subdir: str):
    data = Path(__file__).resolve().parent / ".testdata" / subdir
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    return data


async def _seed_workspace(db, utc_now):
    wid = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO workspaces(id, name, status, created_at, updated_at) VALUES(?,?,?,?,?)",
        (wid, "ChainWS", "active", utc_now(), utc_now()),
    )
    return wid


async def _seed_session(db, utc_now, *, wid, title, summary_text=None):
    sid = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO sessions(id, workspace_id, title, message_count, summary_text, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (sid, wid, title, 0, summary_text, utc_now(), utc_now()),
    )
    return sid


async def _seed_session_summary_memory(db, utc_now, *, wid, source_session_id, content):
    mid = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO memories(id, workspace_id, type, content, tags_json, pinned, source_session_id, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (mid, wid, "session_summary", content, "[]", 0, source_session_id, utc_now(), utc_now()),
    )
    return mid


@pytest.mark.asyncio
async def test_workspace_chain_injects_other_session_summaries():
    _prepare_db("mem-chain-inject")
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        wid = await _seed_workspace(db, utc_now)
        sid_a = await _seed_session(db, utc_now, wid=wid, title="会话A")
        sid_b = await _seed_session(db, utc_now, wid=wid, title="会话B")
        sid_c = await _seed_session(db, utc_now, wid=wid, title="会话C")
        mid_a = await _seed_session_summary_memory(
            db, utc_now, wid=wid, source_session_id=sid_a, content="讨论了水费催缴"
        )
        mid_b = await _seed_session_summary_memory(
            db, utc_now, wid=wid, source_session_id=sid_b, content="整理了催缴话术"
        )
        mid_c = await _seed_session_summary_memory(
            db, utc_now, wid=wid, source_session_id=sid_c, content="当前会话自己的摘要"
        )
        await db.commit()

        text, ids = await get_injection(db, "催缴", wid, session_id=sid_c, max_chars=1500)
        assert "项目内其他会话：" in text
        assert "讨论了水费催缴" in text
        assert "整理了催缴话术" in text
        assert mid_a in ids
        assert mid_b in ids
        assert mid_c not in ids
        assert "当前会话自己的摘要" not in text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_workspace_chain_uses_session_summary_text_when_no_memory():
    _prepare_db("mem-chain-summary-text")
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        wid = await _seed_workspace(db, utc_now)
        sid_a = await _seed_session(
            db, utc_now, wid=wid, title="压缩会话", summary_text="长对话压缩后的项目背景摘要"
        )
        sid_c = await _seed_session(db, utc_now, wid=wid, title="新会话")
        await db.commit()

        text, ids = await get_injection(db, "背景", wid, session_id=sid_c, max_chars=1500)
        assert "项目内其他会话：" in text
        assert "长对话压缩后的项目背景摘要" in text
        assert f"session-summary:{sid_a}" in ids
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_workspace_chain_respects_char_budget():
    _prepare_db("mem-chain-budget")
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        wid = await _seed_workspace(db, utc_now)
        sid_a = await _seed_session(db, utc_now, wid=wid, title="会话A")
        sid_b = await _seed_session(db, utc_now, wid=wid, title="会话B")
        sid_c = await _seed_session(db, utc_now, wid=wid, title="会话C")
        await _seed_session_summary_memory(
            db, utc_now, wid=wid, source_session_id=sid_a, content="AAAA" * 40
        )
        await _seed_session_summary_memory(
            db, utc_now, wid=wid, source_session_id=sid_b, content="BBBB" * 40
        )
        await db.commit()

        text, ids = await get_injection(db, "任意", wid, session_id=sid_c, max_chars=80)
        # 预算极小：不应塞进全部摘要；整体注入长度受控
        assert len(text) <= 80 + len("<memory>\n\n</memory>") + 20
        assert "当前会话自己的摘要" not in text
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_standalone_task_skips_workspace_chain():
    _prepare_db("mem-chain-standalone")
    from app.db.database import get_db, init_db, utc_now

    await init_db()
    db = await get_db()
    try:
        wid = await _seed_workspace(db, utc_now)
        sid_a = await _seed_session(db, utc_now, wid=wid, title="项目会话")
        await _seed_session_summary_memory(
            db, utc_now, wid=wid, source_session_id=sid_a, content="项目内摘要不应出现在独立任务"
        )
        # 独立任务会话（无 workspace）
        sid_solo = str(uuid.uuid4())
        await db.execute(
            """
            INSERT INTO sessions(id, workspace_id, title, message_count, created_at, updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            (sid_solo, None, "独立任务", 0, utc_now(), utc_now()),
        )
        await db.commit()

        text, ids = await get_injection(db, "摘要", None, session_id=sid_solo, max_chars=1500)
        assert "项目内其他会话：" not in text
        assert "项目内摘要不应出现在独立任务" not in text
    finally:
        await db.close()
