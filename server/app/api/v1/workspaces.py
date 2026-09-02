"""项目（工作区）API。产品文案称「项目」，API 路径保持 /workspaces。"""

from __future__ import annotations

import json
import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_token
from app.db.database import utc_now
from app.db.deps import db_dep

router = APIRouter(dependencies=[Depends(require_token)])


class WorkspaceIn(BaseModel):
    name: str
    description: str | None = None
    instructions: str | None = None
    expert_id: str | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    knowledge_ids: list[str] | None = None
    root_paths: list[str] | None = None  # 可选，不强制


class WorkspacePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    expert_id: str | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    knowledge_ids: list[str] | None = None
    root_paths: list[str] | None = None
    status: str | None = None


def _row(r: aiosqlite.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "description": r["description"],
        "instructions": r["instructions"] if "instructions" in r.keys() else None,
        "expert_id": r["expert_id"] if "expert_id" in r.keys() else None,
        "skill_ids": json.loads((r["skill_ids_json"] if "skill_ids_json" in r.keys() else None) or "[]"),
        "mcp_ids": json.loads((r["mcp_ids_json"] if "mcp_ids_json" in r.keys() else None) or "[]"),
        "knowledge_ids": json.loads(
            (r["knowledge_ids_json"] if "knowledge_ids_json" in r.keys() else None) or "[]"
        ),
        "root_paths": json.loads(r["root_paths_json"] or "[]"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


@router.get("")
async def list_workspaces(db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM workspaces WHERE status!='deleted' ORDER BY updated_at DESC")
    rows = await cur.fetchall()
    items = [_row(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.post("")
async def create_workspace(body: WorkspaceIn, db: aiosqlite.Connection = Depends(db_dep)):
    wid = str(uuid.uuid4())
    now = utc_now()
    await db.execute(
        """
        INSERT INTO workspaces(
          id, name, description, root_paths_json, instructions, expert_id,
          skill_ids_json, mcp_ids_json, knowledge_ids_json, status, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            wid,
            body.name,
            body.description,
            json.dumps(body.root_paths or []),
            body.instructions,
            body.expert_id,
            json.dumps(body.skill_ids or []),
            json.dumps(body.mcp_ids or []),
            json.dumps(body.knowledge_ids or []),
            "active",
            now,
            now,
        ),
    )
    await db.commit()
    return await get_workspace(wid, db)


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "workspace not found"})
    return _row(r)


@router.patch("/{workspace_id}")
async def patch_workspace(workspace_id: str, body: WorkspacePatch, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "workspace not found"})
    current = _row(r)
    name = body.name if body.name is not None else current["name"]
    description = body.description if body.description is not None else current["description"]
    instructions = body.instructions if body.instructions is not None else current["instructions"]
    expert_id = body.expert_id if body.expert_id is not None else current["expert_id"]
    skill_ids = body.skill_ids if body.skill_ids is not None else current["skill_ids"]
    mcp_ids = body.mcp_ids if body.mcp_ids is not None else current["mcp_ids"]
    knowledge_ids = body.knowledge_ids if body.knowledge_ids is not None else current["knowledge_ids"]
    root_paths = body.root_paths if body.root_paths is not None else current["root_paths"]
    status = body.status if body.status is not None else current["status"]
    await db.execute(
        """
        UPDATE workspaces SET name=?, description=?, root_paths_json=?, instructions=?, expert_id=?,
          skill_ids_json=?, mcp_ids_json=?, knowledge_ids_json=?, status=?, updated_at=?
        WHERE id=?
        """,
        (
            name,
            description,
            json.dumps(root_paths),
            instructions,
            expert_id,
            json.dumps(skill_ids),
            json.dumps(mcp_ids),
            json.dumps(knowledge_ids),
            status,
            utc_now(),
            workspace_id,
        ),
    )
    await db.commit()
    return await get_workspace(workspace_id, db)


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    await db.execute(
        "UPDATE workspaces SET status=?, updated_at=? WHERE id=?",
        ("archived", utc_now(), workspace_id),
    )
    await db.commit()
    return {"ok": True}


@router.get("/{workspace_id}/summary")
async def workspace_summary(workspace_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT COUNT(*) AS c FROM sessions WHERE workspace_id=?", (workspace_id,))
    sessions = (await cur.fetchone())["c"]
    cur = await db.execute(
        """
        SELECT COUNT(*) AS c FROM checklist_items i
        JOIN checklists c ON c.id=i.checklist_id
        WHERE c.workspace_id=? AND i.done=0
        """,
        (workspace_id,),
    )
    open_items = (await cur.fetchone())["c"]
    cur = await db.execute(
        "SELECT state, doc_count, name, id FROM knowledge_sources WHERE workspace_id=?",
        (workspace_id,),
    )
    sources = [dict(r) for r in await cur.fetchall()]
    cur = await db.execute(
        "SELECT id, title, updated_at FROM sessions WHERE workspace_id=? ORDER BY updated_at DESC LIMIT 20",
        (workspace_id,),
    )
    session_items = [dict(r) for r in await cur.fetchall()]
    return {
        "session_count": sessions,
        "open_checklist_items": open_items,
        "knowledge_sources": sources,
        "sessions": session_items,
    }
