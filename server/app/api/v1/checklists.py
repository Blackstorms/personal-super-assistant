"""清单 API（I11）。"""

from __future__ import annotations

import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.checklists.parser import create_from_message, create_from_session
from app.core.security import require_token
from app.core.workspace_scope import workspace_scope_clause
from app.db.database import utc_now
from app.db.deps import db_dep
from app.fs import whitelist as fs
from app.fs.whitelist import WhitelistError

router = APIRouter(dependencies=[Depends(require_token)])


class ChecklistIn(BaseModel):
    workspace_id: str | None = None
    session_id: str | None = None
    title: str
    items: list[str] | None = None


class ItemPatch(BaseModel):
    done: bool | None = None
    content: str | None = None


class ParseBody(BaseModel):
    message_id: str | None = None
    session_id: str | None = None


class SyncBody(BaseModel):
    target: str  # file
    path: str | None = None


@router.get("")
async def list_checklists(
    workspace_id: str | None = None,
    standalone: bool = False,
    session_id: str | None = None,
    db: aiosqlite.Connection = Depends(db_dep),
):
    clauses: list[str] = []
    params: list[str] = []
    scope_clause, scope_params = workspace_scope_clause(workspace_id=workspace_id, standalone=standalone)
    if scope_clause:
        clauses.append(scope_clause.strip().removeprefix("AND").strip())
        params.extend(scope_params)
    if session_id:
        clauses.append("session_id=?")
        params.append(session_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = await db.execute(f"SELECT * FROM checklists{where} ORDER BY updated_at DESC", params)
    return {"items": [dict(r) for r in await cur.fetchall()]}


@router.post("")
async def create_checklist(body: ChecklistIn, db: aiosqlite.Connection = Depends(db_dep)):
    cid = str(uuid.uuid4())
    now = utc_now()
    await db.execute(
        """
        INSERT INTO checklists(id, workspace_id, session_id, title, created_at, updated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (cid, body.workspace_id, body.session_id, body.title, now, now),
    )
    for i, content in enumerate(body.items or []):
        await db.execute(
            """
            INSERT INTO checklist_items(id, checklist_id, content, done, sort_order, updated_at)
            VALUES(?,?,?,?,?,?)
            """,
            (str(uuid.uuid4()), cid, content, 0, i, now),
        )
    await db.commit()
    return {"id": cid, "title": body.title}


@router.get("/{checklist_id}")
async def get_checklist(checklist_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM checklists WHERE id=?", (checklist_id,))
    c = await cur.fetchone()
    if not c:
        raise HTTPException(404, detail={"code": "not_found", "message": "checklist not found"})
    cur = await db.execute(
        "SELECT * FROM checklist_items WHERE checklist_id=? ORDER BY sort_order",
        (checklist_id,),
    )
    items = [{**dict(r), "done": bool(r["done"])} for r in await cur.fetchall()]
    return {**dict(c), "items": items}


@router.patch("/{checklist_id}")
async def patch_checklist(checklist_id: str, title: str, db: aiosqlite.Connection = Depends(db_dep)):
    await db.execute(
        "UPDATE checklists SET title=?, updated_at=? WHERE id=?",
        (title, utc_now(), checklist_id),
    )
    await db.commit()
    return await get_checklist(checklist_id, db)


@router.delete("/{checklist_id}")
async def delete_checklist(checklist_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    await db.execute("DELETE FROM checklists WHERE id=?", (checklist_id,))
    await db.commit()
    return {"ok": True}


@router.post("/parse")
async def parse_checklist(body: ParseBody, db: aiosqlite.Connection = Depends(db_dep)):
    try:
        if body.message_id:
            return await create_from_message(db, body.message_id)
        if body.session_id:
            return await create_from_session(db, body.session_id)
        raise HTTPException(400, detail={"code": "bad_request", "message": "message_id or session_id required"})
    except ValueError as e:
        raise HTTPException(400, detail={"code": "parse_failed", "message": str(e)}) from e


@router.patch("/{checklist_id}/items/{item_id}")
async def patch_item(
    checklist_id: str,
    item_id: str,
    body: ItemPatch,
    db: aiosqlite.Connection = Depends(db_dep),
):
    cur = await db.execute("SELECT * FROM checklist_items WHERE id=? AND checklist_id=?", (item_id, checklist_id))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "item not found"})
    done = body.done if body.done is not None else bool(r["done"])
    content = body.content if body.content is not None else r["content"]
    await db.execute(
        "UPDATE checklist_items SET done=?, content=?, updated_at=? WHERE id=?",
        (1 if done else 0, content, utc_now(), item_id),
    )
    await db.execute("UPDATE checklists SET updated_at=? WHERE id=?", (utc_now(), checklist_id))
    await db.commit()
    return {"id": item_id, "done": done, "content": content}


@router.post("/{checklist_id}/sync")
async def sync_checklist(checklist_id: str, body: SyncBody, db: aiosqlite.Connection = Depends(db_dep)):
    """将清单导出为白名单内 Markdown 文件（不再支持回写记忆）。"""
    detail = await get_checklist(checklist_id, db)
    lines = [f"- [{'x' if i['done'] else ' '}] {i['content']}" for i in detail["items"]]
    text = detail["title"] + "\n" + "\n".join(lines)
    if body.target == "file":
        if not body.path:
            raise HTTPException(400, detail={"code": "path_required", "message": "path required"})
        try:
            return await fs.write_text(db, body.path, text)
        except WhitelistError as e:
            raise HTTPException(403, detail={"code": "forbidden", "message": str(e)}) from e
    raise HTTPException(400, detail={"code": "bad_target", "message": "target must be file"})
