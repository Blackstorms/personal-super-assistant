"""后台 ticker：周期性 claim 并执行到期定时任务。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db.database import fetch_setting, get_db
from app.scheduler import service as sched_service
from app.scheduler.executor import execute_job, running_count

logger = logging.getLogger("psa.scheduler.ticker")

DEFAULT_POLL_SECONDS = 30
DEFAULT_MAX_CONCURRENT = 2


async def _scheduler_config(db) -> dict[str, Any]:
    cfg = await fetch_setting(db, "scheduler") or {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "poll_interval_seconds": int(cfg.get("poll_interval_seconds") or DEFAULT_POLL_SECONDS),
        "max_concurrent_jobs": int(cfg.get("max_concurrent_jobs") or DEFAULT_MAX_CONCURRENT),
    }


async def tick_once(app: Any) -> int:
    """执行一轮调度；返回启动的任务数。"""
    registry = getattr(app.state, "skill_registry", None)
    if registry is None:
        return 0

    db = await get_db()
    try:
        cfg = await _scheduler_config(db)
        if not cfg["enabled"]:
            return 0
        slots = max(0, cfg["max_concurrent_jobs"] - running_count())
        if slots <= 0:
            return 0
        claimed = await sched_service.claim_due_jobs(db, limit=slots)
        if not claimed:
            return 0

        from app.mcp.manager import mcp_manager

        started = 0
        for job in claimed:
            # 每个 job 使用独立 DB 连接，避免并发冲突
            asyncio.create_task(_run_claimed(app, job, mcp_manager))
            started += 1
        return started
    finally:
        await db.close()


async def _run_claimed(app: Any, job: dict, mcp_manager: Any) -> None:
    registry = getattr(app.state, "skill_registry", None)
    if registry is None:
        return
    db = await get_db()
    try:
        await execute_job(db, job, registry=registry, mcp_manager=mcp_manager, manual=False)
    except Exception:  # noqa: BLE001
        logger.exception("tick execute failed job_id=%s", job.get("id"))
    finally:
        await db.close()


async def start_scheduler(app: Any) -> asyncio.Task:
    """在 lifespan 中启动后台循环，返回 task 以便 shutdown 时 cancel。"""

    async def _loop() -> None:
        log = logging.getLogger("psa.scheduler")
        log.info("scheduler ticker started")
        while True:
            try:
                n = await tick_once(app)
                if n:
                    log.info("scheduler dispatched %s job(s)", n)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("scheduler tick error")
            # 读取最新 poll 间隔
            poll = DEFAULT_POLL_SECONDS
            try:
                db = await get_db()
                try:
                    cfg = await _scheduler_config(db)
                    poll = max(5, int(cfg["poll_interval_seconds"]))
                finally:
                    await db.close()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(poll)

    task = asyncio.create_task(_loop(), name="psa-scheduler-ticker")
    app.state.scheduler_task = task
    return task


async def stop_scheduler(app: Any) -> None:
    task = getattr(app.state, "scheduler_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    app.state.scheduler_task = None
