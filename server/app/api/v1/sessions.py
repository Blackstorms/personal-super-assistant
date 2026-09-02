"""会话与消息 API。"""

from __future__ import annotations

import json
import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.agent.session_bindings import save_session_composer_bindings, session_row_with_bindings
from app.core.security import require_token
from app.db.database import utc_now
from app.db.deps import db_dep
from app.fs import session_attachments as sa

router = APIRouter(dependencies=[Depends(require_token)])


class SessionIn(BaseModel):
    title: str | None = None
    workspace_id: str | None = None


class SessionPatch(BaseModel):
    title: str | None = None
    composer_bindings: dict | None = None


class AttachFileIn(BaseModel):
    name: str
    content: str
    encoding: str = "utf-8"


class AttachIn(BaseModel):
    paths: list[str] | None = None
    files: list[AttachFileIn] | None = None


@router.get("")
async def list_sessions(
    workspace_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(db_dep),
):
    if workspace_id:
        cur = await db.execute(
            "SELECT * FROM sessions WHERE workspace_id=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (workspace_id, limit, offset),
        )
    else:
        cur = await db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    rows = await cur.fetchall()
    return {"items": [session_row_with_bindings(dict(r)) for r in rows], "total": len(rows)}


@router.post("")
async def create_session(body: SessionIn, db: aiosqlite.Connection = Depends(db_dep)):
    sid = str(uuid.uuid4())
    now = utc_now()
    title = body.title or "新会话"
    await db.execute(
        """
        INSERT INTO sessions(id, workspace_id, title, message_count, created_at, updated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (sid, body.workspace_id, title, 0, now, now),
    )
    await db.commit()
    return {
        "id": sid,
        "workspace_id": body.workspace_id,
        "title": title,
        "message_count": 0,
        "created_at": now,
        "updated_at": now,
        "composer_bindings": None,
    }


@router.get("/{session_id}")
async def get_session(session_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    return session_row_with_bindings(dict(r))


@router.patch("/{session_id}")
async def patch_session(session_id: str, body: SessionPatch, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    if body.title is not None:
        await db.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (body.title, utc_now(), session_id),
        )
        await db.commit()
    if body.composer_bindings is not None:
        await save_session_composer_bindings(db, session_id, body.composer_bindings)
    return await get_session(session_id, db)


@router.delete("/{session_id}")
async def delete_session(session_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    await db.commit()
    sa.delete_session_files(session_id)
    return {"ok": True}


@router.get("/{session_id}/messages")
async def list_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=500),
    db: aiosqlite.Connection = Depends(db_dep),
):
    cur = await db.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at LIMIT ?",
        (session_id, limit),
    )
    rows = await cur.fetchall()
    items = []
    for r in rows:
        item = dict(r)
        if item.get("tool_calls_json"):
            item["tool_calls"] = json.loads(item["tool_calls_json"])
        items.append(item)
    return {"items": items}


@router.get("/{session_id}/active-run")
async def get_active_run(session_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    """查询会话是否有后台进行中的 run（定时任务 headless 执行时无本机 SSE）。"""
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    cur = await db.execute(
        """
        SELECT id, status, started_at, error_message
        FROM chat_runs
        WHERE session_id=? AND status IN ('running', 'waiting_confirm')
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (session_id,),
    )
    row = await cur.fetchone()
    if not row:
        return {"active": False, "run": None}
    return {
        "active": True,
        "run": {
            "id": row["id"],
            "status": row["status"],
            "started_at": row["started_at"],
            "error_message": row["error_message"],
        },
    }


@router.get("/{session_id}/pending-confirm")
async def get_pending_confirm(session_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    """恢复高风险工具确认条（刷新/重进会话后仍可点确认）。"""
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    cur = await db.execute(
        """
        SELECT id, pending_json, status, started_at
        FROM chat_runs
        WHERE session_id=? AND status='waiting_confirm' AND pending_json IS NOT NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (session_id,),
    )
    row = await cur.fetchone()
    if not row:
        return {"pending": None}
    try:
        payload = json.loads(row["pending_json"] or "{}")
    except json.JSONDecodeError:
        return {"pending": None}
    tc = payload.get("tool_call") or {}
    fn = tc.get("function") or {}
    name = fn.get("name") or (tc.get("name") if isinstance(tc.get("name"), str) else "") or "tool"
    args = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    tool_call_id = tc.get("id") or payload.get("tool_call_id")
    if not tool_call_id:
        return {"pending": None}
    from app.agent.tool_loop import preview_confirm_arguments

    return {
        "pending": {
            "run_id": row["id"],
            "tool_call_id": tool_call_id,
            "name": name,
            "arguments": preview_confirm_arguments(name, args),
            "risk": "high",
            "started_at": row["started_at"],
        }
    }


@router.get("/{session_id}/context")
async def get_session_context(session_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    """会话上下文用量（压缩阈值 / 已用 token），供 composer 展示。"""
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    from app.agent.compress import estimate_session_context

    return await estimate_session_context(db, session_id)


@router.get("/{session_id}/attachments")
async def list_session_attachments(session_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    items = await sa.list_attachments(db, session_id)
    return {"items": items, "total": len(items)}


@router.post("/{session_id}/attachments")
async def add_session_attachments(
    session_id: str,
    body: AttachIn,
    db: aiosqlite.Connection = Depends(db_dep),
):
    cur = await db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
    if not await cur.fetchone():
        raise HTTPException(404, detail={"code": "not_found", "message": "session not found"})
    created: list[dict] = []
    if body.paths:
        created.extend(await sa.ingest_paths(db, session_id, body.paths))
    if body.files:
        created.extend(await sa.ingest_text_files(db, session_id, [f.model_dump() for f in body.files]))
    if not created:
        raise HTTPException(400, detail={"code": "empty", "message": "no valid attachments"})
    return {"items": created, "total": len(created)}
