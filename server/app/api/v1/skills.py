"""技能 API。"""

from __future__ import annotations

import asyncio
import json

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.security import require_token
from app.db.deps import db_dep, skill_registry

router = APIRouter(dependencies=[Depends(require_token)])


class SkillCreate(BaseModel):
    id: str = Field(..., description="技能 ID，即斜杠命令名，如 my-skill")
    name: str
    description: str = ""
    triggers: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    body: str = ""
    version: str = "1.0"
    enabled: bool = True


class SkillPatch(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    description: str | None = None
    triggers: list[str] | None = None
    permissions: list[str] | None = None
    body: str | None = None
    version: str | None = None


class RunBody(BaseModel):
    input: dict | str


class MatchBody(BaseModel):
    query: str


class SkillParseBody(BaseModel):
    content: str
    skill_id: str | None = None
    fallback_id: str | None = Field(None, description="通常为文件名去掉 .md")


class SkillImportBody(BaseModel):
    content: str
    skill_id: str | None = None
    fallback_id: str | None = None
    enabled: bool = True


def _skill_dict(s, *, include_body: bool = False) -> dict:
    data = {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "triggers": s.triggers,
        "permissions": s.permissions,
        "enabled": s.enabled,
        "version": s.version,
        "skill_path": s.skill_path,
    }
    if include_body:
        data["body"] = s.body
    return data


@router.get("")
async def list_skills(request: Request, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM skills ORDER BY name")
    rows = await cur.fetchall()
    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "triggers": json.loads(r["triggers_json"] or "[]"),
                "permissions": json.loads(r["permissions_json"] or "[]"),
                "enabled": bool(r["enabled"]),
                "version": r["version"],
                "skill_path": r["skill_path"],
            }
        )
    return {"items": items}


@router.post("")
async def create_skill(
    body: SkillCreate,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    reg = skill_registry(request)
    try:
        meta = await reg.create_skill(
            db,
            skill_id=body.id.strip(),
            name=body.name,
            description=body.description,
            triggers=body.triggers,
            permissions=body.permissions,
            body=body.body,
            version=body.version,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(400, detail={"code": "invalid", "message": str(e)}) from e
    return _skill_dict(meta, include_body=True)


@router.post("/parse")
async def parse_skill_md(body: SkillParseBody, request: Request):
    """解析 SKILL.md 文本，返回表单字段（不写入）。"""
    reg = skill_registry(request)
    try:
        meta = reg.parse_skill_content(
            body.content,
            skill_id=body.skill_id.strip() if body.skill_id else None,
            fallback_id=body.fallback_id.strip() if body.fallback_id else None,
        )
    except ValueError as e:
        raise HTTPException(400, detail={"code": "invalid", "message": str(e)}) from e
    return _skill_dict(meta, include_body=True)


@router.post("/import")
async def import_skill_md(
    body: SkillImportBody,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """从 SKILL.md 文本导入并创建技能。"""
    reg = skill_registry(request)
    try:
        meta = reg.parse_skill_content(
            body.content,
            skill_id=body.skill_id.strip() if body.skill_id else None,
            fallback_id=body.fallback_id.strip() if body.fallback_id else None,
        )
        created = await reg.create_skill(
            db,
            skill_id=meta.id,
            name=meta.name,
            description=meta.description,
            triggers=meta.triggers,
            permissions=meta.permissions,
            body=meta.body,
            version=meta.version,
            enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(400, detail={"code": "invalid", "message": str(e)}) from e
    return _skill_dict(created, include_body=True)


@router.get("/hermes/slash-commands")
async def hermes_slash_commands():
    """Hermes skill_commands 扫描结果（供斜杠菜单增强）。"""
    from app.hermes_bridge.skills_adapter import list_hermes_skill_commands

    items = await list_hermes_skill_commands()
    return {"items": items}


@router.get("/hermes/catalog")
async def hermes_catalog(request: Request):
    """列出可导入到本机技能库的 Hermes 技能（插件 / 已安装 / 内置）。"""
    from app.hermes_bridge.hub_adapter import list_hermes_catalog

    items = list_hermes_catalog()
    own_ids = {s.id for s in skill_registry(request)._cache.values()}
    for it in items:
        it["imported"] = it.get("id") in own_ids
    return {"items": items}


class HermesImportBody(BaseModel):
    identifier: str
    skill_id: str | None = None


class BundleIn(BaseModel):
    name: str
    description: str = ""
    skills: list[str] = Field(default_factory=list)
    instruction: str = ""


@router.get("/bundles")
async def list_bundles(db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM skill_bundles ORDER BY name")
    rows = await cur.fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "skills": json.loads(r["skills_json"] or "[]"),
                "instruction": r["instruction"] or "",
            }
            for r in rows
        ]
    }


@router.post("/bundles")
async def create_bundle(body: BundleIn, db: aiosqlite.Connection = Depends(db_dep)):
    import uuid

    from app.db.database import utc_now

    bid = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO skill_bundles(id, name, description, skills_json, instruction, updated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            bid,
            body.name.strip(),
            body.description,
            json.dumps(body.skills, ensure_ascii=False),
            body.instruction,
            utc_now(),
        ),
    )
    await db.commit()
    return {"id": bid, "name": body.name, "skills": body.skills}


@router.delete("/bundles/{bundle_id}")
async def delete_bundle(bundle_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    await db.execute("DELETE FROM skill_bundles WHERE id=?", (bundle_id,))
    await db.commit()
    return {"ok": True}


@router.get("/pending-writes")
async def list_pending_writes(db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute(
        "SELECT * FROM pending_skill_writes WHERE status='pending' ORDER BY created_at DESC"
    )
    rows = await cur.fetchall()
    return {
        "items": [
            {
                "id": r["id"],
                "skill_id": r["skill_id"],
                "action": r["action"],
                "diff_text": r["diff_text"],
                "status": r["status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


class HubSearchBody(BaseModel):
    query: str
    limit: int = 20


class HubInstallBody(BaseModel):
    identifier: str


@router.post("/hub/search")
async def hub_search(body: HubSearchBody):
    from app.hermes_bridge.hub_adapter import hub_search as _search

    items = await _search(body.query, limit=body.limit)
    return {"items": items}


@router.post("/hub/install")
async def hub_install(body: HubInstallBody, request: Request):
    from app.hermes_bridge.hub_adapter import hub_install as _install

    result = await _install(body.identifier)
    # 安装后尝试重载本地技能表
    if result.get("ok"):
        try:
            reg = skill_registry(request)
            await reg.reload()
        except Exception:  # noqa: BLE001
            pass
    return result


@router.post("/hermes/import")
async def hermes_import_skill(
    body: HermesImportBody,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """把 Hermes / Hub 技能复制进本机 skills/ 目录。"""
    from app.hermes_bridge.hub_adapter import resolve_hermes_skill

    try:
        resolved = await asyncio.to_thread(resolve_hermes_skill, body.identifier)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "invalid", "message": str(e)}) from e

    reg = skill_registry(request)
    try:
        created = await reg.import_from_markdown(
            db,
            content=resolved["content"],
            skill_id=(body.skill_id or "").strip() or resolved.get("id"),
            fallback_id=resolved.get("id"),
            extra_files=resolved.get("extra_files") or {},
        )
    except ValueError as e:
        raise HTTPException(400, detail={"code": "invalid", "message": str(e)}) from e
    return _skill_dict(created, include_body=True)


@router.post("/match")
async def match_skills(body: MatchBody, request: Request):
    reg = skill_registry(request)
    matched = reg.match(body.query)
    return {"matched": [{"id": s.id, "score": score, "name": s.name} for s, score in matched]}


@router.get("/{skill_id}")
async def get_skill(skill_id: str, request: Request):
    reg = skill_registry(request)
    s = reg.get(skill_id)
    if not s:
        raise HTTPException(404, detail={"code": "not_found", "message": "skill not found"})
    return _skill_dict(s, include_body=True)


@router.patch("/{skill_id}")
async def patch_skill(
    skill_id: str,
    body: SkillPatch,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    reg = skill_registry(request)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, detail={"code": "empty", "message": "no fields to update"})
    try:
        if set(fields.keys()) == {"enabled"}:
            if not reg.get(skill_id):
                raise HTTPException(404, detail={"code": "not_found", "message": "skill not found"})
            await reg.set_enabled(db, skill_id, bool(body.enabled))
            s = reg.get(skill_id)
            if not s:
                raise HTTPException(404, detail={"code": "not_found", "message": "skill not found"})
            return _skill_dict(s, include_body=True)
        meta = await reg.update_skill(db, skill_id, **fields)
    except ValueError as e:
        raise HTTPException(400, detail={"code": "invalid", "message": str(e)}) from e
    return _skill_dict(meta, include_body=True)


@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    reg = skill_registry(request)
    ok = await reg.delete_skill(db, skill_id)
    if not ok:
        raise HTTPException(404, detail={"code": "not_found", "message": "skill not found"})
    return {"ok": True}


@router.post("/reload")
async def reload_skills(request: Request):
    reg = skill_registry(request)
    n = await reg.reload()
    return {"loaded": n}


@router.post("/{skill_id}/run")
async def run_skill(skill_id: str, body: RunBody, request: Request):
    reg = skill_registry(request)
    s = reg.get(skill_id)
    if not s or not s.enabled:
        raise HTTPException(404, detail={"code": "not_found", "message": "skill not found"})
    payload = body.input if isinstance(body.input, str) else json.dumps(body.input, ensure_ascii=False)
    # 试运行：返回技能引导 + 输入，便于演示闭环
    return {
        "ok": True,
        "output": {
            "skill": s.name,
            "applied_input": payload,
            "guidance_preview": s.body[:1000],
        },
        "logs": [f"skill {skill_id} executed in dry-run mode"],
    }
