"""受控文件 API。"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.security import require_token
from app.db.deps import db_dep
from app.fs import whitelist as fs
from app.fs.whitelist import WhitelistError

router = APIRouter(dependencies=[Depends(require_token)])


class WriteBody(BaseModel):
    path: str
    content: str


@router.get("/list")
async def list_dir(path: str = Query(...), db: aiosqlite.Connection = Depends(db_dep)):
    try:
        return {"entries": await fs.list_dir(db, path)}
    except WhitelistError as e:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(e)}) from e


@router.get("/read")
async def read_file(
    path: str = Query(...),
    max_bytes: int = 512000,
    db: aiosqlite.Connection = Depends(db_dep),
):
    try:
        return await fs.read_text(db, path, max_bytes=max_bytes)
    except WhitelistError as e:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(e)}) from e


@router.post("/write")
async def write_file(body: WriteBody, db: aiosqlite.Connection = Depends(db_dep)):
    """高风险写接口；UI 层应二次确认。"""
    try:
        return await fs.write_text(db, body.path, body.content)
    except WhitelistError as e:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(e)}) from e
