"""Schedule 解析：cron / interval / once（DeerFlow + Cherry 语义）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

ScheduleKind = Literal["cron", "interval", "once"]


@dataclass
class ParsedSchedule:
    kind: ScheduleKind
    raw: str
    cron_expr: str | None = None
    interval_seconds: int | None = None
    once_at: datetime | None = None
    repeat_mode: Literal["once", "forever", "times"] = "forever"


class ScheduleParseError(ValueError):
    """无法解析的调度表达式。"""


_INTERVAL_RE = re.compile(
    r"^(?:every\s+)?(\d+)\s*("
    r"months?|mo|"
    r"minutes?|mins?|min|m|"
    r"hours?|hrs?|hr|h|"
    r"days?|d|"
    r"weeks?|w|"
    r"years?|y|"
    r"seconds?|secs?|sec|s"
    r")$",
    re.IGNORECASE,
)
_IN_RE = re.compile(
    r"^in\s+(\d+)\s*("
    r"months?|mo|"
    r"minutes?|mins?|min|m|"
    r"hours?|hrs?|hr|h|"
    r"days?|d|"
    r"weeks?|w|"
    r"years?|y|"
    r"seconds?|secs?|sec|s"
    r")$",
    re.IGNORECASE,
)
_CRON_RE = re.compile(r"^([\d\*\/,\-]+)\s+([\d\*\/,\-]+)\s+([\d\*\/,\-]+)\s+([\d\*\/,\-]+)\s+([\d\*\/,\-\w]+)$")


def _unit_seconds(n: int, unit: str) -> int:
    u = unit.lower()
    if u in {"s", "sec", "secs", "second", "seconds"}:
        return n
    if u in {"mo", "month", "months"}:
        return n * 86400 * 30
    if u in {"m", "min", "mins", "minute", "minutes"}:
        return n * 60
    if u in {"h", "hr", "hrs", "hour", "hours"}:
        return n * 3600
    if u in {"d", "day", "days"}:
        return n * 86400
    if u in {"w", "week", "weeks"}:
        return n * 86400 * 7
    if u in {"y", "year", "years"}:
        return n * 86400 * 365
    raise ScheduleParseError(f"unknown duration unit: {unit}")


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_schedule(raw: str, *, now: datetime | None = None) -> ParsedSchedule:
    """解析用户输入的 schedule 字符串。"""
    text = (raw or "").strip()
    if not text:
        raise ScheduleParseError("schedule is empty")
    now = _ensure_aware(now or datetime.now(timezone.utc))

    m = _IN_RE.match(text)
    if m:
        secs = _unit_seconds(int(m.group(1)), m.group(2))
        return ParsedSchedule(
            kind="once",
            raw=text,
            once_at=now + timedelta(seconds=secs),
            repeat_mode="once",
        )

    m = _INTERVAL_RE.match(text)
    if m:
        secs = _unit_seconds(int(m.group(1)), m.group(2))
        if secs < 60:
            raise ScheduleParseError("interval must be at least 60 seconds")
        return ParsedSchedule(
            kind="interval",
            raw=text,
            interval_seconds=secs,
            repeat_mode="forever",
        )

    # ISO once
    if "T" in text or re.match(r"^\d{4}-\d{2}-\d{2}", text):
        try:
            iso = text.replace("Z", "+00:00")
            once_at = datetime.fromisoformat(iso)
            once_at = _ensure_aware(once_at)
            return ParsedSchedule(kind="once", raw=text, once_at=once_at, repeat_mode="once")
        except ValueError as exc:
            raise ScheduleParseError(f"invalid ISO datetime: {text}") from exc

    # 五段 cron
    if _CRON_RE.match(text):
        try:
            from croniter import croniter

            croniter(text, now)
        except Exception as exc:  # noqa: BLE001
            raise ScheduleParseError(f"invalid cron expression: {text}") from exc
        return ParsedSchedule(kind="cron", raw=text, cron_expr=text, repeat_mode="forever")

    # Cherry-style every day at 9am → 简化映射
    day_at = re.match(
        r"^every\s+day\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$",
        text,
        re.IGNORECASE,
    )
    if day_at:
        hour = int(day_at.group(1))
        minute = int(day_at.group(2) or 0)
        ampm = (day_at.group(3) or "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        cron = f"{minute} {hour} * * *"
        return ParsedSchedule(kind="cron", raw=text, cron_expr=cron, repeat_mode="forever")

    raise ScheduleParseError(
        f"unsupported schedule: {text!r}. Use cron (0 9 * * *), every 30m / 2w / 1mo, in 30m, or ISO datetime."
    )


def compute_next_run(parsed: ParsedSchedule, *, after: datetime | None = None) -> datetime | None:
    """计算下次运行时间；once 已过期返回 None。"""
    after = _ensure_aware(after or datetime.now(timezone.utc))

    if parsed.kind == "once":
        if parsed.once_at is None:
            return None
        return parsed.once_at if parsed.once_at > after else None

    if parsed.kind == "interval":
        secs = parsed.interval_seconds or 0
        if secs <= 0:
            return None
        return after + timedelta(seconds=secs)

    if parsed.kind == "cron":
        expr = parsed.cron_expr or parsed.raw
        from croniter import croniter

        itr = croniter(expr, after)
        nxt = itr.get_next(datetime)
        return _ensure_aware(nxt)

    return None


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return _ensure_aware(dt).isoformat().replace("+00:00", "Z")


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return _ensure_aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
