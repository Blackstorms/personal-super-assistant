"""Hermes toolsets API。"""

from __future__ import annotations

import uuid

import aiosqlite
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import require_token
from app.db.database import utc_now
from app.db.deps import db_dep
from app.hermes_bridge.lifecycle import get_bridge_status, hermes_available
from app.hermes_bridge.tool_surface import list_toolsets

router = APIRouter(dependencies=[Depends(require_token)])


class ToolsetPatch(BaseModel):
    enabled: bool


@router.get("/toolsets")
async def get_toolsets(db: aiosqlite.Connection = Depends(db_dep)):
    available = await list_toolsets()
    cur = await db.execute("SELECT toolset, enabled FROM hermes_toolset_settings")
    rows = {r["toolset"]: bool(r["enabled"]) for r in await cur.fetchall()}
    items = []
    for name, meta in (available or {}).items():
        items.append(
            {
                "id": name,
                "name": name,
                "enabled": rows.get(name, True),
                "meta": meta if isinstance(meta, dict) else {"info": str(meta)},
            }
        )
    if not items:
        for name, en in rows.items():
            items.append({"id": name, "name": name, "enabled": en, "meta": {}})
    return {
        "items": items,
        "hermes": get_bridge_status(),
        "hermes_available": hermes_available(),
    }


@router.put("/toolsets/{toolset}")
async def put_toolset(
    toolset: str,
    body: ToolsetPatch,
    db: aiosqlite.Connection = Depends(db_dep),
):
    now = utc_now()
    await db.execute(
        """
        INSERT INTO hermes_toolset_settings(id, toolset, enabled, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(toolset) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at
        """,
        (str(uuid.uuid4()), toolset, 1 if body.enabled else 0, now),
    )
    await db.commit()
    return {"ok": True, "toolset": toolset, "enabled": body.enabled}
