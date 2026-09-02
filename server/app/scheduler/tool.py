"""内置工具 schedule_task：对话创建/管理定时任务。"""

from __future__ import annotations

import asyncio
from typing import Any

import aiosqlite

from app.scheduler.schedule import ScheduleParseError
from app.scheduler import service as sched_service

SCHEDULE_TASK_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "schedule_task",
        "description": (
            "创建或管理自动化定时任务。"
            "action: create / list / pause / resume / remove / run。"
            "create 时必须提供 prompt（触发时 Agent 要执行的指令），"
            "以及 cron（如 '0 9 * * *'）、every（如 'every 30m'）、at（如 'in 1h' 或 ISO 时间）三者之一。"
            "用户用中文描述「每天九点做…」「一小时后…」时，请转换成对应表达式并调用本工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "pause", "resume", "remove", "run"],
                },
                "job_id": {"type": "string", "description": "pause/resume/remove/run 时必填"},
                "name": {"type": "string", "description": "任务名称"},
                "prompt": {
                    "type": "string",
                    "description": "任务触发时交给 Agent 执行的中文指令",
                },
                "cron": {"type": "string"},
                "every": {"type": "string"},
                "at": {"type": "string"},
                "session_mode": {
                    "type": "string",
                    "enum": ["new", "reuse"],
                    "description": "new=每次新建会话；reuse=固定会话",
                },
                "workspace_id": {"type": "string"},
                "model_profile_id": {"type": "string"},
                "expert_id": {"type": "string"},
                "knowledge_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["action"],
        },
    },
}


async def handle_schedule_task(
    db: aiosqlite.Connection,
    arguments: dict,
    *,
    registry: Any | None = None,
    mcp_manager: Any | None = None,
) -> Any:
    action = (arguments.get("action") or "").strip().lower()
    if action == "list":
        items = await sched_service.list_jobs(db)
        return {
            "jobs": [
                {
                    "id": j["id"],
                    "name": j["name"],
                    "schedule_raw": j["schedule_raw"],
                    "schedule_kind": j["schedule_kind"],
                    "next_run_at": j.get("next_run_at"),
                    "enabled": j.get("enabled"),
                    "state": j.get("state"),
                    "last_status": j.get("last_status"),
                }
                for j in items
            ],
            "manage_url": "/automation",
        }

    if action == "create":
        prompt = (arguments.get("prompt") or "").strip()
        if not prompt:
            return {"error": "prompt is required for create"}
        try:
            raw = sched_service.resolve_schedule_from_tool_args(arguments)
        except ScheduleParseError as e:
            return {"error": str(e)}
        session_mode = (arguments.get("session_mode") or "new").lower()
        delivery = "fixed_session" if session_mode == "reuse" else "new_session"
        try:
            job = await sched_service.create_job(
                db,
                name=(arguments.get("name") or "定时任务").strip(),
                prompt=prompt,
                schedule_raw=raw,
                workspace_id=arguments.get("workspace_id"),
                model_profile_id=arguments.get("model_profile_id"),
                expert_id=arguments.get("expert_id"),
                knowledge_ids=arguments.get("knowledge_ids"),
                delivery_mode=delivery,
            )
        except ScheduleParseError as e:
            return {"error": str(e)}
        return {
            "ok": True,
            "job": {
                "id": job["id"],
                "name": job["name"],
                "schedule_raw": job["schedule_raw"],
                "next_run_at": job.get("next_run_at"),
            },
            "manage_url": "/automation",
            "message": "定时任务已创建，可在「自动化」页管理",
        }

    job_id = (arguments.get("job_id") or "").strip()
    if action in {"pause", "resume", "remove", "run"} and not job_id:
        return {"error": "job_id is required"}

    try:
        if action == "pause":
            job = await sched_service.pause_job(db, job_id)
            return {"ok": True, "job": {"id": job["id"], "state": job["state"], "enabled": job["enabled"]}}
        if action == "resume":
            job = await sched_service.resume_job(db, job_id)
            return {
                "ok": True,
                "job": {
                    "id": job["id"],
                    "state": job["state"],
                    "next_run_at": job.get("next_run_at"),
                },
            }
        if action == "remove":
            await sched_service.delete_job(db, job_id)
            return {"ok": True, "deleted": job_id}
        if action == "run":
            job = await sched_service.get_job(db, job_id)
            if not job:
                return {"error": "job not found"}
            if registry is None:
                return {
                    "ok": True,
                    "job_id": job_id,
                    "message": "请打开「自动化」页点击「立即运行」",
                    "manage_url": "/automation",
                }

            from app.db.database import get_db
            from app.scheduler.executor import execute_job

            async def _bg() -> None:
                bg = await get_db()
                try:
                    await execute_job(
                        bg, job, registry=registry, mcp_manager=mcp_manager, manual=True
                    )
                finally:
                    await bg.close()

            asyncio.create_task(_bg())
            return {
                "ok": True,
                "job_id": job_id,
                "message": "已触发立即运行",
                "manage_url": "/automation",
            }
    except KeyError:
        return {"error": "job not found"}
    except ScheduleParseError as e:
        return {"error": str(e)}

    return {"error": f"unknown action: {action}"}
