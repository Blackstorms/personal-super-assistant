"""定时任务：schedule 解析与 framing / claim 单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.scheduler.framing import frame_scheduled_prompt
from app.scheduler.schedule import (
    ScheduleParseError,
    compute_next_run,
    parse_schedule,
    to_iso,
)


def test_parse_cron():
    p = parse_schedule("0 9 * * *")
    assert p.kind == "cron"
    assert p.cron_expr == "0 9 * * *"
    nxt = compute_next_run(p, after=datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc))
    assert nxt is not None
    assert nxt.hour == 9


def test_parse_interval():
    p = parse_schedule("every 30m")
    assert p.kind == "interval"
    assert p.interval_seconds == 1800
    after = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    nxt = compute_next_run(p, after=after)
    assert nxt == after + timedelta(minutes=30)


def test_parse_every_2h():
    p = parse_schedule("every 2h")
    assert p.interval_seconds == 7200


def test_parse_every_week_month_year():
    assert parse_schedule("every 1w").interval_seconds == 86400 * 7
    assert parse_schedule("every 2mo").interval_seconds == 86400 * 60
    assert parse_schedule("every 1y").interval_seconds == 86400 * 365


def test_parse_in_relative_once():
    now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    p = parse_schedule("in 30m", now=now)
    assert p.kind == "once"
    assert p.repeat_mode == "once"
    assert p.once_at == now + timedelta(minutes=30)
    assert compute_next_run(p, after=now) == p.once_at
    assert compute_next_run(p, after=now + timedelta(hours=1)) is None


def test_parse_iso_once():
    p = parse_schedule("2026-09-01T09:00:00Z")
    assert p.kind == "once"
    assert p.once_at is not None


def test_parse_every_day_at():
    p = parse_schedule("every day at 9am")
    assert p.kind == "cron"
    assert p.cron_expr == "0 9 * * *"


def test_parse_invalid():
    with pytest.raises(ScheduleParseError):
        parse_schedule("not-a-schedule")


def test_parse_interval_too_short():
    with pytest.raises(ScheduleParseError):
        parse_schedule("every 30s")


def test_framing_contains_instruction():
    text = frame_scheduled_prompt(name="喝水提醒", prompt="提醒用户喝水")
    assert "[Scheduled Task: 喝水提醒]" in text
    assert "automated scheduled execution" in text
    assert "提醒用户喝水" in text


def test_to_iso():
    dt = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    assert to_iso(dt) == "2026-08-31T12:00:00Z"


@pytest.mark.asyncio
async def test_claim_due_jobs(tmp_path, monkeypatch):
    import aiosqlite

    from app.core.config import settings
    from app.db.database import init_db
    from app.scheduler import service as sched_service

    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    await init_db()

    db = await aiosqlite.connect(str(settings.db_path))
    db.row_factory = aiosqlite.Row
    try:
        past = to_iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        job = await sched_service.create_job(
            db,
            name="due",
            prompt="do something",
            schedule_raw="in 1m",
        )
        await db.execute(
            "UPDATE scheduled_jobs SET next_run_at=? WHERE id=?",
            (past, job["id"]),
        )
        await db.commit()

        claimed = await sched_service.claim_due_jobs(db, limit=5)
        assert len(claimed) == 1
        assert claimed[0]["id"] == job["id"]

        claimed2 = await sched_service.claim_due_jobs(db, limit=5)
        assert claimed2 == []

        updated = await sched_service.get_job(db, job["id"])
        assert updated is not None
        assert updated["state"] == "completed" or updated["enabled"] is False
    finally:
        await db.close()


def test_resolve_cherry_triad():
    from app.scheduler.service import resolve_schedule_from_tool_args

    assert resolve_schedule_from_tool_args({"cron": "0 9 * * *"}) == "0 9 * * *"
    assert resolve_schedule_from_tool_args({"every": "30m"}) == "every 30m"
    assert resolve_schedule_from_tool_args({"at": "2026-09-01T09:00:00Z"}) == "2026-09-01T09:00:00Z"
    with pytest.raises(ScheduleParseError):
        resolve_schedule_from_tool_args({"cron": "0 9 * * *", "every": "30m"})
