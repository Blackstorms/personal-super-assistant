"""记忆中心 API。"""

from __future__ import annotations

import json
import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.agent import runtime as agent_runtime
from app.core.security import require_token
from app.core.workspace_scope import workspace_scope_clause
from app.db.database import utc_now
from app.db.deps import db_dep
from app.memory import service as memory_service

router = APIRouter(dependencies=[Depends(require_token)])


class MemoryIn(BaseModel):
    type: str
    content: str
    tags: list[str] | None = None
    pinned: bool = False
    workspace_id: str | None = None
    confidence: float | None = None


class MemoryPatch(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    type: str | None = None
    confidence: float | None = None


class SearchBody(BaseModel):
    query: str
    top_k: int = 5
    workspace_id: str | None = None
    standalone: bool = False


class ExtractBody(BaseModel):
    session_id: str


@router.get("")
async def list_memories(
    type: str | None = None,
    workspace_id: str | None = None,
    standalone: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = 0,
    db: aiosqlite.Connection = Depends(db_dep),
):
    sql = "SELECT * FROM memories WHERE 1=1"
    params: list = []
    if type:
        sql += " AND type=?"
        params.append(type)
    clause, scope_params = workspace_scope_clause(workspace_id=workspace_id, standalone=standalone)
    sql += clause
    params.extend(scope_params)
    sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur = await db.execute(sql, params)
    rows = await cur.fetchall()
    items = []
    for r in rows:
        d = dict(r)
        items.append(
            {
                **d,
                "tags": json.loads(r["tags_json"] or "[]"),
                "pinned": bool(r["pinned"]),
            }
        )
    return {"items": items, "total": len(items)}


@router.post("")
async def create_memory(body: MemoryIn, db: aiosqlite.Connection = Depends(db_dep)):
    mid = str(uuid.uuid4())
    now = utc_now()
    cur = await db.execute("PRAGMA table_info(memories)")
    cols = {r["name"] for r in await cur.fetchall()}
    if "confidence" in cols:
        await db.execute(
            """
            INSERT INTO memories(id, workspace_id, type, content, tags_json, pinned, confidence, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                mid,
                body.workspace_id,
                body.type,
                body.content,
                json.dumps(body.tags or [], ensure_ascii=False),
                1 if body.pinned else 0,
                body.confidence,
                now,
                now,
            ),
        )
    else:
        await db.execute(
            """
            INSERT INTO memories(id, workspace_id, type, content, tags_json, pinned, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                mid,
                body.workspace_id,
                body.type,
                body.content,
                json.dumps(body.tags or [], ensure_ascii=False),
                1 if body.pinned else 0,
                now,
                now,
            ),
        )
    await db.commit()
    return {"id": mid, "type": body.type, "content": body.content, "pinned": body.pinned}


@router.patch("/{memory_id}")
async def patch_memory(memory_id: str, body: MemoryPatch, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM memories WHERE id=?", (memory_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "memory not found"})
    content = body.content if body.content is not None else r["content"]
    tags = body.tags if body.tags is not None else json.loads(r["tags_json"] or "[]")
    pinned = body.pinned if body.pinned is not None else bool(r["pinned"])
    mtype = body.type if body.type is not None else r["type"]
    keys = r.keys()
    conf = body.confidence
    if conf is None and "confidence" in keys:
        conf = r["confidence"]
    cols = await db.execute("PRAGMA table_info(memories)")
    colset = {x["name"] for x in await cols.fetchall()}
    if "confidence" in colset:
        await db.execute(
            "UPDATE memories SET type=?, content=?, tags_json=?, pinned=?, confidence=?, updated_at=? WHERE id=?",
            (mtype, content, json.dumps(tags, ensure_ascii=False), 1 if pinned else 0, conf, utc_now(), memory_id),
        )
    else:
        await db.execute(
            "UPDATE memories SET type=?, content=?, tags_json=?, pinned=?, updated_at=? WHERE id=?",
            (mtype, content, json.dumps(tags, ensure_ascii=False), 1 if pinned else 0, utc_now(), memory_id),
        )
    await db.commit()
    return {"id": memory_id, "content": content, "pinned": pinned, "type": mtype}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    await db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    await db.commit()
    return {"ok": True}


@router.post("/search")
async def search_memories(body: SearchBody, db: aiosqlite.Connection = Depends(db_dep)):
    if body.standalone:
        q = (body.query or "").replace('"', "").strip()
        rows: list = []
        if q:
            try:
                cur = await db.execute(
                    """
                    SELECT m.id, m.content FROM memories_fts f
                    JOIN memories m ON m.rowid = f.rowid
                    WHERE memories_fts MATCH ? AND m.workspace_id IS NULL
                    LIMIT ?
                    """,
                    (q, body.top_k + 5),
                )
                rows = await cur.fetchall()
            except Exception:  # noqa: BLE001
                like = f"%{q[:40]}%"
                cur = await db.execute(
                    """
                    SELECT id, content FROM memories
                    WHERE content LIKE ? AND workspace_id IS NULL
                    ORDER BY pinned DESC LIMIT ?
                    """,
                    (like, body.top_k + 5),
                )
                rows = await cur.fetchall()
        else:
            cur = await db.execute(
                "SELECT id, content FROM memories WHERE workspace_id IS NULL ORDER BY pinned DESC LIMIT ?",
                (body.top_k + 5,),
            )
            rows = await cur.fetchall()
        ids = [r["id"] for r in rows[: body.top_k]]
    else:
        text, ids = await memory_service.get_injection(
            db, body.query, body.workspace_id, top_k=body.top_k, max_chars=50_000
        )
        if not ids:
            return {"items": []}
        placeholders = ",".join("?" * len(ids))
        cur = await db.execute(f"SELECT * FROM memories WHERE id IN ({placeholders})", ids)
        rows = await cur.fetchall()
        by_id = {r["id"]: r for r in rows}
        ordered = [by_id[i] for i in ids if i in by_id]
        return {
            "items": [
                {**dict(r), "tags": json.loads(r["tags_json"] or "[]"), "pinned": bool(r["pinned"])} for r in ordered
            ],
            "injection_preview": text[:500],
        }

    if not ids:
        return {"items": []}
    placeholders = ",".join("?" * len(ids))
    cur = await db.execute(f"SELECT * FROM memories WHERE id IN ({placeholders})", ids)
    rows = await cur.fetchall()
    by_id = {r["id"]: r for r in rows}
    ordered = [by_id[i] for i in ids if i in by_id]
    return {
        "items": [
            {**dict(r), "tags": json.loads(r["tags_json"] or "[]"), "pinned": bool(r["pinned"])} for r in ordered
        ],
    }


@router.post("/extract")
async def extract_memories(
    body: ExtractBody,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """从会话抽取记忆（LLM + 规则回退）。"""
    llm = await agent_runtime._load_llm(db)
    created = await memory_service.extract_from_session(db, body.session_id, llm=llm)
    return {"created": created}
