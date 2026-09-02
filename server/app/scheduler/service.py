"""定时任务领域服务：CRUD + claim + 状态更新。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.db.database import utc_now
from app.scheduler.framing import framing_preview
from app.scheduler.schedule import (
    ScheduleParseError,
    compute_next_run,
    parse_schedule,
    to_iso,
)


def _dumps(value: list[str] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None) -> list[str] | None:
    if not value:
        return None
    try:
        data = json.loads(value)
        return [str(x) for x in data] if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def row_to_job(row: aiosqlite.Row | dict) -> dict[str, Any]:
    d = dict(row)
    d["enabled"] = bool(d.get("enabled"))
    d["run_count"] = int(d.get("run_count") or 0)
    d["knowledge_ids"] = _loads(d.pop("knowledge_ids_json", None))
    d["skill_ids"] = _loads(d.pop("skill_ids_json", None))
    d["mcp_ids"] = _loads(d.pop("mcp_ids_json", None))
    d["framing_preview"] = framing_preview(name=d.get("name") or "", prompt=d.get("prompt") or "")
    return d


async def list_jobs(
    db: aiosqlite.Connection,
    *,
    workspace_id: str | None = None,
    include_disabled: bool = True,
) -> list[dict]:
    sql = """
        SELECT j.*, (
            SELECT COUNT(*) FROM scheduled_job_runs r WHERE r.job_id = j.id
        ) AS run_count
        FROM scheduled_jobs j
    """
    args: list[Any] = []
    clauses: list[str] = []
    if workspace_id:
        clauses.append("j.workspace_id=?")
        args.append(workspace_id)
    if not include_disabled:
        clauses.append("j.enabled=1")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY j.updated_at DESC"
    cur = await db.execute(sql, args)
    return [row_to_job(r) for r in await cur.fetchall()]


async def get_job(db: aiosqlite.Connection, job_id: str) -> dict | None:
    cur = await db.execute("SELECT * FROM scheduled_jobs WHERE id=?", (job_id,))
    row = await cur.fetchone()
    return row_to_job(row) if row else None


async def create_job(
    db: aiosqlite.Connection,
    *,
    name: str,
    prompt: str,
    schedule_raw: str,
    schedule_kind: str | None = None,
    repeat_mode: str | None = None,
    repeat_limit: int | None = None,
    workspace_id: str | None = None,
    model_profile_id: str | None = None,
    expert_id: str | None = None,
    knowledge_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    mcp_ids: list[str] | None = None,
    delivery_mode: str = "new_session",
    target_session_id: str | None = None,
) -> dict:
    parsed = parse_schedule(schedule_raw)
    if schedule_kind and schedule_kind != parsed.kind:
        # 允许显式 kind 校验
        if schedule_kind not in {"cron", "interval", "once"}:
            raise ScheduleParseError(f"invalid schedule_kind: {schedule_kind}")
    next_at = compute_next_run(parsed)
    now = utc_now()
    job_id = str(uuid.uuid4())
    mode = repeat_mode or parsed.repeat_mode
    if parsed.kind == "once":
        mode = "once"
    await db.execute(
        """
        INSERT INTO scheduled_jobs(
          id, name, prompt, schedule_raw, schedule_kind, interval_seconds, next_run_at,
          repeat_mode, repeat_limit, repeat_done, enabled, state,
          workspace_id, model_profile_id, expert_id,
          knowledge_ids_json, skill_ids_json, mcp_ids_json,
          delivery_mode, target_session_id,
          created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            job_id,
            name.strip() or "定时任务",
            prompt.strip(),
            schedule_raw.strip(),
            parsed.kind,
            parsed.interval_seconds,
            to_iso(next_at),
            mode,
            repeat_limit,
            0,
            1,
            "active" if next_at else "completed",
            workspace_id,
            model_profile_id,
            expert_id,
            _dumps(knowledge_ids),
            _dumps(skill_ids),
            _dumps(mcp_ids),
            delivery_mode if delivery_mode in {"new_session", "fixed_session"} else "new_session",
            target_session_id if delivery_mode == "fixed_session" else None,
            now,
            now,
        ),
    )
    await db.commit()
    job = await get_job(db, job_id)
    assert job is not None
    return job


async def update_job(db: aiosqlite.Connection, job_id: str, **fields: Any) -> dict:
    job = await get_job(db, job_id)
    if not job:
        raise KeyError("job not found")

    name = fields.get("name", job["name"])
    prompt = fields.get("prompt", job["prompt"])
    schedule_raw = fields.get("schedule_raw", job["schedule_raw"])
    delivery_mode = fields.get("delivery_mode", job["delivery_mode"])
    target_session_id = fields.get("target_session_id", job.get("target_session_id"))
    repeat_mode = fields.get("repeat_mode", job["repeat_mode"])
    repeat_limit = fields.get("repeat_limit", job.get("repeat_limit"))
    workspace_id = fields.get("workspace_id", job.get("workspace_id"))
    model_profile_id = fields.get("model_profile_id", job.get("model_profile_id"))
    expert_id = fields.get("expert_id", job.get("expert_id"))
    knowledge_ids = fields.get("knowledge_ids", job.get("knowledge_ids"))
    skill_ids = fields.get("skill_ids", job.get("skill_ids"))
    mcp_ids = fields.get("mcp_ids", job.get("mcp_ids"))

    parsed = parse_schedule(schedule_raw)
    next_at = compute_next_run(parsed)
    if parsed.kind == "once":
        repeat_mode = "once"

    await db.execute(
        """
        UPDATE scheduled_jobs SET
          name=?, prompt=?, schedule_raw=?, schedule_kind=?, interval_seconds=?, next_run_at=?,
          repeat_mode=?, repeat_limit=?,
          workspace_id=?, model_profile_id=?, expert_id=?,
          knowledge_ids_json=?, skill_ids_json=?, mcp_ids_json=?,
          delivery_mode=?, target_session_id=?,
          state=CASE WHEN ?=0 THEN 'completed' WHEN enabled=0 THEN 'paused' ELSE 'active' END,
          updated_at=?
        WHERE id=?
        """,
        (
            name,
            prompt,
            schedule_raw.strip(),
            parsed.kind,
            parsed.interval_seconds,
            to_iso(next_at),
            repeat_mode,
            repeat_limit,
            workspace_id,
            model_profile_id,
            expert_id,
            _dumps(knowledge_ids),
            _dumps(skill_ids),
            _dumps(mcp_ids),
            delivery_mode,
            target_session_id if delivery_mode == "fixed_session" else None,
            0 if next_at is None and parsed.kind == "once" else 1,
            utc_now(),
            job_id,
        ),
    )
    await db.commit()
    updated = await get_job(db, job_id)
    assert updated is not None
    return updated


async def pause_job(db: aiosqlite.Connection, job_id: str) -> dict:
    await db.execute(
        "UPDATE scheduled_jobs SET enabled=0, state='paused', updated_at=? WHERE id=?",
        (utc_now(), job_id),
    )
    await db.commit()
    job = await get_job(db, job_id)
    if not job:
        raise KeyError("job not found")
    return job


async def resume_job(db: aiosqlite.Connection, job_id: str) -> dict:
    job = await get_job(db, job_id)
    if not job:
        raise KeyError("job not found")
    parsed = parse_schedule(job["schedule_raw"])
    next_at = compute_next_run(parsed)
    await db.execute(
        """
        UPDATE scheduled_jobs SET enabled=1, state=?, next_run_at=?, updated_at=? WHERE id=?
        """,
        ("active" if next_at else "completed", to_iso(next_at), utc_now(), job_id),
    )
    await db.commit()
    updated = await get_job(db, job_id)
    assert updated is not None
    return updated


async def delete_job(db: aiosqlite.Connection, job_id: str) -> None:
    await db.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
    await db.commit()


async def list_runs(db: aiosqlite.Connection, job_id: str, *, limit: int = 50) -> list[dict]:
    cur = await db.execute(
        """
        SELECT * FROM scheduled_job_runs
        WHERE job_id=?
        ORDER BY started_at DESC
        LIMIT ?
        """,
        (job_id, limit),
    )
    return [dict(r) for r in await cur.fetchall()]


async def claim_due_jobs(db: aiosqlite.Connection, *, limit: int = 5) -> list[dict]:
    """CAS：选出到点任务并推进 next_run_at，返回 claim 到的 job 列表。"""
    now = datetime.now(timezone.utc)
    now_iso = to_iso(now)
    cur = await db.execute(
        """
        SELECT * FROM scheduled_jobs
        WHERE enabled=1 AND state='active' AND next_run_at IS NOT NULL AND next_run_at<=?
        ORDER BY next_run_at ASC
        LIMIT ?
        """,
        (now_iso, limit),
    )
    rows = await cur.fetchall()
    claimed: list[dict] = []
    for row in rows:
        job = row_to_job(row)
        parsed = parse_schedule(job["schedule_raw"])
        # 推进下次：interval/cron 从 now 算；once 置空
        if parsed.kind == "once" or job["repeat_mode"] == "once":
            next_at = None
            new_state = "completed"
            enabled = 0
        else:
            next_at = compute_next_run(parsed, after=now)
            new_state = "active" if next_at else "completed"
            enabled = 1 if next_at else 0

        # CAS：仅当 next_run_at 未变才更新
        cur2 = await db.execute(
            """
            UPDATE scheduled_jobs
            SET next_run_at=?, state=?, enabled=?, updated_at=?
            WHERE id=? AND next_run_at=?
            """,
            (to_iso(next_at), new_state, enabled, utc_now(), job["id"], job["next_run_at"]),
        )
        if cur2.rowcount:
            claimed.append(job)
    await db.commit()
    return claimed


async def session_has_running_run(db: aiosqlite.Connection, session_id: str) -> bool:
    cur = await db.execute(
        "SELECT 1 FROM chat_runs WHERE session_id=? AND status='running' LIMIT 1",
        (session_id,),
    )
    return await cur.fetchone() is not None


async def create_run_row(
    db: aiosqlite.Connection,
    *,
    job_id: str,
    session_id: str | None,
    run_id: str | None,
    status: str = "running",
    error_message: str | None = None,
    output_preview: str | None = None,
) -> str:
    rid = str(uuid.uuid4())
    now = utc_now()
    finished = None if status == "running" else now
    await db.execute(
        """
        INSERT INTO scheduled_job_runs(
          id, job_id, session_id, run_id, status, started_at, finished_at, output_preview, error_message
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (rid, job_id, session_id, run_id, status, now, finished, output_preview, error_message),
    )
    await db.commit()
    return rid


async def finish_run_row(
    db: aiosqlite.Connection,
    run_row_id: str,
    *,
    status: str,
    run_id: str | None = None,
    session_id: str | None = None,
    output_preview: str | None = None,
    error_message: str | None = None,
) -> None:
    await db.execute(
        """
        UPDATE scheduled_job_runs
        SET status=?, run_id=COALESCE(?, run_id), session_id=COALESCE(?, session_id),
            output_preview=?, error_message=?, finished_at=?
        WHERE id=?
        """,
        (status, run_id, session_id, output_preview, error_message, utc_now(), run_row_id),
    )
    await db.commit()


async def mark_job_result(
    db: aiosqlite.Connection,
    job_id: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    job = await get_job(db, job_id)
    if not job:
        return
    repeat_done = int(job.get("repeat_done") or 0) + (1 if status == "success" else 0)
    updates: dict[str, Any] = {
        "last_run_at": utc_now(),
        "last_status": status,
        "last_error": error,
        "repeat_done": repeat_done,
        "updated_at": utc_now(),
    }
    # times 模式结束
    if job.get("repeat_mode") == "times" and job.get("repeat_limit"):
        if repeat_done >= int(job["repeat_limit"]):
            updates["enabled"] = 0
            updates["state"] = "completed"
            updates["next_run_at"] = None

    await db.execute(
        """
        UPDATE scheduled_jobs SET
          last_run_at=?, last_status=?, last_error=?, repeat_done=?,
          enabled=COALESCE(?, enabled), state=COALESCE(?, state),
          next_run_at=CASE WHEN ? IS NOT NULL AND ?=0 THEN NULL ELSE next_run_at END,
          updated_at=?
        WHERE id=?
        """,
        (
            updates["last_run_at"],
            updates["last_status"],
            updates["last_error"],
            updates["repeat_done"],
            updates.get("enabled"),
            updates.get("state"),
            updates.get("enabled"),
            updates.get("enabled"),
            updates["updated_at"],
            job_id,
        ),
    )
    await db.commit()


def resolve_schedule_from_tool_args(args: dict) -> str:
    """Cherry 三态：cron | every | at → schedule_raw。"""
    cron = (args.get("cron") or "").strip()
    every = (args.get("every") or "").strip()
    at = (args.get("at") or "").strip()
    schedule = (args.get("schedule") or args.get("schedule_raw") or "").strip()
    specified = [x for x in (cron, every, at, schedule) if x]
    if len(specified) > 1 and not schedule:
        # cron/every/at 只能选一个
        count = sum(1 for x in (cron, every, at) if x)
        if count > 1:
            raise ScheduleParseError("specify only one of cron, every, or at")
    if cron:
        return cron
    if every:
        return every if every.lower().startswith("every") else f"every {every}"
    if at:
        return at
    if schedule:
        return schedule
    raise ScheduleParseError("missing schedule: provide cron, every, or at")
