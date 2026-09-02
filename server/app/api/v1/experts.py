"""专家（人设预设）API。"""

from __future__ import annotations

import json
import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_token
from app.db.database import utc_now
from app.db.deps import db_dep
from app.experts.presets import expert_meta

router = APIRouter(dependencies=[Depends(require_token)])


class ExpertIn(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    model_profile_id: str | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    knowledge_ids: list[str] | None = None


class ExpertPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    model_profile_id: str | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    knowledge_ids: list[str] | None = None


def _row_to_expert(r: aiosqlite.Row) -> dict:
    item = {
        "id": r["id"],
        "name": r["name"],
        "description": r["description"],
        "system_prompt": r["system_prompt"],
        "model_profile_id": r["model_profile_id"],
        "skill_ids": json.loads(r["skill_ids_json"] or "[]"),
        "mcp_ids": json.loads(r["mcp_ids_json"] or "[]"),
        "knowledge_ids": json.loads(r["knowledge_ids_json"] or "[]"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "is_preset": str(r["id"]).startswith("preset-expert-"),
    }
    meta = expert_meta(str(r["id"]))
    if meta:
        item.update(meta)
    else:
        item.setdefault("category", "个人")
        item.setdefault("badge", None)
        item.setdefault("icon", "default")
    return item


@router.get("")
async def list_experts(db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM experts ORDER BY updated_at DESC")
    rows = await cur.fetchall()
    return {"items": [_row_to_expert(r) for r in rows], "total": len(rows)}


@router.post("")
async def create_expert(body: ExpertIn, db: aiosqlite.Connection = Depends(db_dep)):
    eid = str(uuid.uuid4())
    now = utc_now()
    await db.execute(
        """
        INSERT INTO experts(
          id, name, description, system_prompt, model_profile_id,
          skill_ids_json, mcp_ids_json, knowledge_ids_json, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            eid,
            body.name,
            body.description,
            body.system_prompt,
            body.model_profile_id,
            json.dumps(body.skill_ids or []),
            json.dumps(body.mcp_ids or []),
            json.dumps(body.knowledge_ids or []),
            now,
            now,
        ),
    )
    await db.commit()
    cur = await db.execute("SELECT * FROM experts WHERE id=?", (eid,))
    return _row_to_expert(await cur.fetchone())


@router.get("/{expert_id}")
async def get_expert(expert_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM experts WHERE id=?", (expert_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "expert not found"})
    return _row_to_expert(r)


@router.patch("/{expert_id}")
async def patch_expert(expert_id: str, body: ExpertPatch, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM experts WHERE id=?", (expert_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "expert not found"})
    name = body.name if body.name is not None else r["name"]
    description = body.description if body.description is not None else r["description"]
    system_prompt = body.system_prompt if body.system_prompt is not None else r["system_prompt"]
    model_profile_id = body.model_profile_id if body.model_profile_id is not None else r["model_profile_id"]
    skill_ids = body.skill_ids if body.skill_ids is not None else json.loads(r["skill_ids_json"] or "[]")
    mcp_ids = body.mcp_ids if body.mcp_ids is not None else json.loads(r["mcp_ids_json"] or "[]")
    knowledge_ids = (
        body.knowledge_ids if body.knowledge_ids is not None else json.loads(r["knowledge_ids_json"] or "[]")
    )
    await db.execute(
        """
        UPDATE experts SET name=?, description=?, system_prompt=?, model_profile_id=?,
          skill_ids_json=?, mcp_ids_json=?, knowledge_ids_json=?, updated_at=?
        WHERE id=?
        """,
        (
            name,
            description,
            system_prompt,
            model_profile_id,
            json.dumps(skill_ids),
            json.dumps(mcp_ids),
            json.dumps(knowledge_ids),
            utc_now(),
            expert_id,
        ),
    )
    await db.commit()
    return await get_expert(expert_id, db)


@router.delete("/{expert_id}")
async def delete_expert(expert_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    await db.execute("DELETE FROM experts WHERE id=?", (expert_id,))
    await db.commit()
    return {"ok": True}
