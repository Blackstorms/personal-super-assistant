"""after_agent：对话结束后的异步收尾（记忆抽取等）。"""

from __future__ import annotations

import logging

from app.agent.llm_loader import load_llm
from app.db.database import get_db
from app.memory import service as memory_service

logger = logging.getLogger(__name__)


async def async_extract_memory(session_id: str, profile_id: str | None) -> None:
    """对话结束后异步抽取记忆；失败只记日志。"""
    db = await get_db()
    try:
        llm = await load_llm(db, profile_id)
        await memory_service.extract_from_session(db, session_id, llm=llm)
    except Exception as e:  # noqa: BLE001
        logger.warning("async memory extract failed: %s", e)
    finally:
        await db.close()
