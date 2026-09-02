"""首条用户消息后，根据问题自动生成会话标题。"""

from __future__ import annotations

import asyncio
import logging
import re

import aiosqlite

from app.db.database import utc_now

logger = logging.getLogger(__name__)

TITLE_PROMPT = """根据用户的第一条消息，生成一个简短的中文会话标题。
要求：8-20字，概括核心意图，不要标点符号，不要引号，只输出标题本身。"""

DEFAULT_TITLES = frozenset({"新会话", "新任务", "项目会话", "未命名会话"})


def fallback_title(content: str) -> str:
    """规则回退：取首行并截断。"""
    text = content.strip()
    if text.startswith("/"):
        parts = text.split(None, 1)
        text = parts[1] if len(parts) > 1 else parts[0]
    text = text.split("\n")[0].strip()
    if "[附件:" in text:
        text = text.split("[附件:")[0].strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > 24:
        text = text[:24] + "…"
    return text or "新会话"


def sanitize_title(raw: str) -> str:
    t = raw.strip().strip("\"'""''「」")
    t = re.sub(r"\s+", " ", t.replace("\n", " ")).strip()
    if len(t) > 40:
        t = t[:40]
    return t


async def _needs_auto_title(db: aiosqlite.Connection, session_id: str) -> bool:
    cur = await db.execute("SELECT title FROM sessions WHERE id=?", (session_id,))
    row = await cur.fetchone()
    if not row:
        return False
    if (row["title"] or "") not in DEFAULT_TITLES:
        return False
    cur = await db.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE session_id=? AND role='user'",
        (session_id,),
    )
    count = (await cur.fetchone())["c"]
    return count == 1


async def generate_title_llm(llm, user_content: str) -> str:
    snippet = user_content.strip()[:500]
    resp = await llm.complete(
        [
            {"role": "system", "content": TITLE_PROMPT},
            {"role": "user", "content": snippet},
        ]
    )
    title = sanitize_title(resp.get("content") or "")
    return title if len(title) >= 2 else ""


async def maybe_auto_title(
    db: aiosqlite.Connection,
    session_id: str,
    user_content: str,
    profile_id: str | None = None,
) -> str | None:
    """
    首条用户消息且标题为默认值时，生成并写入新标题。
    LLM 超时或失败时使用规则回退。
    """
    if not await _needs_auto_title(db, session_id):
        return None

    new_title = fallback_title(user_content)
    try:
        from app.agent.runtime import _load_llm

        llm = await _load_llm(db, profile_id)
        llm_title = await asyncio.wait_for(generate_title_llm(llm, user_content), timeout=2.5)
        if llm_title:
            new_title = llm_title
    except Exception as e:  # noqa: BLE001
        logger.debug("session title llm fallback: %s", e)

    await db.execute(
        "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
        (new_title, utc_now(), session_id),
    )
    await db.commit()
    return new_title
