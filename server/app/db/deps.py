"""FastAPI 依赖：请求级 DB 连接。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiosqlite
from fastapi import Request

from app.db.database import get_db


async def db_dep() -> AsyncIterator[aiosqlite.Connection]:
    db = await get_db()
    try:
        yield db
    finally:
        await db.close()


def skill_registry(request: Request):
    return request.app.state.skill_registry
