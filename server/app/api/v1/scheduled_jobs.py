"""定时任务 REST API。"""

from __future__ import annotations

import asyncio

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.security import require_token
from app.db.deps import db_dep, skill_registry
from app.mcp.manager import mcp_manager
from app.scheduler.schedule import ScheduleParseError
from app.scheduler import service as sched_service
from app.scheduler.executor import execute_job
from app.scheduler.framing import framing_preview

router = APIRouter(dependencies=[Depends(require_token)])


class JobCreate(BaseModel):
    name: str
    prompt: str
    schedule_raw: str | None = None
    schedule_kind: str | None = None
    # Cherry 三态别名
    cron: str | None = None
    every: str | None = None
    at: str | None = None
    repeat_mode: str | None = None
    repeat_limit: int | None = None
    workspace_id: str | None = None
    model_profile_id: str | None = None
    expert_id: str | None = None
    knowledge_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    delivery_mode: str = "new_session"
    target_session_id: str | None = None


class JobUpdate(BaseModel):
    name: str | None = None
    prompt: str | None = None
    schedule_raw: str | None = None
    cron: str | None = None
    every: str | None = None
    at: str | None = None
    repeat_mode: str | None = None
    repeat_limit: int | None = None
    workspace_id: str | None = None
    model_profile_id: str | None = None
    expert_id: str | None = None
    knowledge_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    delivery_mode: str | None = None
    target_session_id: str | None = None


class FramingPreviewIn(BaseModel):
    name: str = "定时任务"
    prompt: str = ""


def _resolve_raw(body: JobCreate | JobUpdate) -> str | None:
    try:
        args = {
            "cron": body.cron,
            "every": body.every,
            "at": body.at,
            "schedule_raw": body.schedule_raw,
        }
        if isinstance(body, JobCreate):
            return sched_service.resolve_schedule_from_tool_args(args)
        # update: 仅当提供了任一字段时解析
        if any(args.values()):
            return sched_service.resolve_schedule_from_tool_args(args)
        return None
    except ScheduleParseError as e:
        raise HTTPException(400, detail={"code": "bad_schedule", "message": str(e)}) from e


@router.get("")
async def list_jobs(
    workspace_id: str | None = None,
    include_disabled: bool = Query(True),
    db: aiosqlite.Connection = Depends(db_dep),
):
    items = await sched_service.list_jobs(
        db, workspace_id=workspace_id, include_disabled=include_disabled
    )
    return {"items": items}


@router.post("")
async def create_job(body: JobCreate, db: aiosqlite.Connection = Depends(db_dep)):
    if not body.prompt.strip():
        raise HTTPException(400, detail={"code": "bad_request", "message": "prompt required"})
    try:
        raw = _resolve_raw(body)
        assert raw
        job = await sched_service.create_job(
            db,
            name=body.name,
            prompt=body.prompt,
            schedule_raw=raw,
            schedule_kind=body.schedule_kind,
            repeat_mode=body.repeat_mode,
            repeat_limit=body.repeat_limit,
            workspace_id=body.workspace_id,
            model_profile_id=body.model_profile_id,
            expert_id=body.expert_id,
            knowledge_ids=body.knowledge_ids,
            skill_ids=body.skill_ids,
            mcp_ids=body.mcp_ids,
            delivery_mode=body.delivery_mode,
            target_session_id=body.target_session_id,
        )
        return job
    except ScheduleParseError as e:
        raise HTTPException(400, detail={"code": "bad_schedule", "message": str(e)}) from e


@router.post("/framing-preview")
async def preview_framing(body: FramingPreviewIn):
    return {"preview": framing_preview(name=body.name, prompt=body.prompt)}


@router.get("/{job_id}")
async def get_job(job_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    job = await sched_service.get_job(db, job_id)
    if not job:
        raise HTTPException(404, detail={"code": "not_found", "message": "job not found"})
    return job


@router.put("/{job_id}")
async def update_job(job_id: str, body: JobUpdate, db: aiosqlite.Connection = Depends(db_dep)):
    try:
        fields = body.model_dump(exclude_unset=True)
        raw = _resolve_raw(body)
        if raw is not None:
            fields["schedule_raw"] = raw
        for k in ("cron", "every", "at"):
            fields.pop(k, None)
        job = await sched_service.update_job(db, job_id, **fields)
        return job
    except KeyError:
        raise HTTPException(404, detail={"code": "not_found", "message": "job not found"}) from None
    except ScheduleParseError as e:
        raise HTTPException(400, detail={"code": "bad_schedule", "message": str(e)}) from e


@router.post("/{job_id}/pause")
async def pause_job(job_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    try:
        return await sched_service.pause_job(db, job_id)
    except KeyError:
        raise HTTPException(404, detail={"code": "not_found", "message": "job not found"}) from None


@router.post("/{job_id}/resume")
async def resume_job(job_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    try:
        return await sched_service.resume_job(db, job_id)
    except KeyError:
        raise HTTPException(404, detail={"code": "not_found", "message": "job not found"}) from None
    except ScheduleParseError as e:
        raise HTTPException(400, detail={"code": "bad_schedule", "message": str(e)}) from e


@router.post("/{job_id}/run")
async def run_job_now(
    job_id: str,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    job = await sched_service.get_job(db, job_id)
    if not job:
        raise HTTPException(404, detail={"code": "not_found", "message": "job not found"})
    registry = skill_registry(request)

    async def _bg() -> None:
        from app.db.database import get_db

        bg_db = await get_db()
        try:
            await execute_job(
                bg_db, job, registry=registry, mcp_manager=mcp_manager, manual=True
            )
        finally:
            await bg_db.close()

    asyncio.create_task(_bg())
    return {"ok": True, "job_id": job_id, "message": "triggered"}


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    job = await sched_service.get_job(db, job_id)
    if not job:
        raise HTTPException(404, detail={"code": "not_found", "message": "job not found"})
    await sched_service.delete_job(db, job_id)
    return {"ok": True}


@router.get("/{job_id}/runs")
async def list_job_runs(
    job_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: aiosqlite.Connection = Depends(db_dep),
):
    job = await sched_service.get_job(db, job_id)
    if not job:
        raise HTTPException(404, detail={"code": "not_found", "message": "job not found"})
    return {"items": await sched_service.list_runs(db, job_id, limit=limit)}
