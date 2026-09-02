"""定时任务执行器：创建/复用会话 + headless Agent run。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import aiosqlite

from app.db.database import utc_now
from app.scheduler import service as sched_service
from app.scheduler.framing import frame_scheduled_prompt

logger = logging.getLogger("psa.scheduler.executor")

_running_jobs: set[str] = set()


def running_count() -> int:
    return len(_running_jobs)


async def _ensure_session(db: aiosqlite.Connection, job: dict) -> tuple[str, bool]:
    """返回 (session_id, skipped)。reuse 模式下若有 running run 则 skip。"""
    delivery = job.get("delivery_mode") or "new_session"
    if delivery == "fixed_session" and job.get("target_session_id"):
        sid = job["target_session_id"]
        cur = await db.execute("SELECT id FROM sessions WHERE id=?", (sid,))
        if await cur.fetchone():
            if await sched_service.session_has_running_run(db, sid):
                return sid, True
            return sid, False
        # 目标会话不存在则新建并回写
    sid = str(uuid.uuid4())
    title = f"[定时] {job.get('name') or '任务'}"
    now = utc_now()
    await db.execute(
        """
        INSERT INTO sessions(id, workspace_id, title, message_count, created_at, updated_at)
        VALUES(?,?,?,?,?,?)
        """,
        (sid, job.get("workspace_id"), title, 0, now, now),
    )
    if delivery == "fixed_session":
        await db.execute(
            "UPDATE scheduled_jobs SET target_session_id=?, updated_at=? WHERE id=?",
            (sid, now, job["id"]),
        )
    await db.commit()
    return sid, False


async def execute_job(
    db: aiosqlite.Connection,
    job: dict,
    *,
    registry: Any,
    mcp_manager: Any | None = None,
    manual: bool = False,
) -> dict[str, Any]:
    """执行单个定时任务；manual=True 时不依赖 claim（用于立即触发）。"""
    job_id = job["id"]
    if job_id in _running_jobs:
        run_row = await sched_service.create_run_row(
            db,
            job_id=job_id,
            session_id=None,
            run_id=None,
            status="skipped",
            error_message="job already running",
        )
        return {"status": "skipped", "run_row_id": run_row, "reason": "already_running"}

    session_id, skipped = await _ensure_session(db, job)
    if skipped:
        run_row = await sched_service.create_run_row(
            db,
            job_id=job_id,
            session_id=session_id,
            run_id=None,
            status="skipped",
            error_message="session has active run",
        )
        return {"status": "skipped", "run_row_id": run_row, "session_id": session_id}

    run_row_id = await sched_service.create_run_row(
        db, job_id=job_id, session_id=session_id, run_id=None, status="running"
    )
    _running_jobs.add(job_id)
    framed = frame_scheduled_prompt(name=job.get("name") or "", prompt=job.get("prompt") or "")

    try:
        from app.agent.runtime import run_chat_collect

        result = await run_chat_collect(
            db,
            registry,
            session_id,
            framed,
            enable_skills=True,
            enable_mcp=True,
            enable_memory=True,
            enable_knowledge=True,
            mcp_manager=mcp_manager,
            model_profile_id=job.get("model_profile_id"),
            expert_id=job.get("expert_id"),
            knowledge_ids=job.get("knowledge_ids"),
            skill_ids=job.get("skill_ids"),
            mcp_ids=job.get("mcp_ids"),
            bypass_whitelist=True,
        )
        status = result.get("status") or "success"
        preview = (result.get("assistant_text") or "")[:2000]
        err = result.get("error")
        if status == "needs_confirmation":
            # 记为 failed，附带待确认说明
            finish_status = "failed"
        elif status == "failed":
            finish_status = "failed"
        else:
            finish_status = "success"

        await sched_service.finish_run_row(
            db,
            run_row_id,
            status=finish_status,
            run_id=result.get("run_id"),
            session_id=session_id,
            output_preview=preview,
            error_message=err,
        )
        await sched_service.mark_job_result(
            db, job_id, status=finish_status, error=err
        )
        return {
            "status": finish_status,
            "run_row_id": run_row_id,
            "session_id": session_id,
            "run_id": result.get("run_id"),
            "output_preview": preview,
            "error": err,
            "manual": manual,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("scheduled job failed job_id=%s", job_id)
        await sched_service.finish_run_row(
            db,
            run_row_id,
            status="failed",
            session_id=session_id,
            error_message=str(e),
        )
        await sched_service.mark_job_result(db, job_id, status="failed", error=str(e))
        return {
            "status": "failed",
            "run_row_id": run_row_id,
            "session_id": session_id,
            "error": str(e),
            "manual": manual,
        }
    finally:
        _running_jobs.discard(job_id)
