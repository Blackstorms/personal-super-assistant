"""内置时间工具：返回本机或指定时区的当前日期时间。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

TZ_ALIASES: dict[str, str] = {
    "utc": "UTC",
    "gmt": "UTC",
    "北京": "Asia/Shanghai",
    "上海": "Asia/Shanghai",
    "中国": "Asia/Shanghai",
    "国内": "Asia/Shanghai",
    "cst": "Asia/Shanghai",
    "cn": "Asia/Shanghai",
    "香港": "Asia/Hong_Kong",
    "台北": "Asia/Taipei",
    "新加坡": "Asia/Singapore",
    "东京": "Asia/Tokyo",
    "日本": "Asia/Tokyo",
    "首尔": "Asia/Seoul",
    "纽约": "America/New_York",
    "美东": "America/New_York",
    "洛杉矶": "America/Los_Angeles",
    "美西": "America/Los_Angeles",
    "伦敦": "Europe/London",
    "巴黎": "Europe/Paris",
    "柏林": "Europe/Berlin",
    "悉尼": "Australia/Sydney",
}

CURRENT_TIME_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "current_time",
        "description": (
            "获取当前真实日期与时间（本机时区，或指定 IANA 时区）。"
            "用户询问几点、今天几号、星期几、现在日期时必须调用，禁止猜测。"
            "不要用 web_search 查时间。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "timezone": {
                    "type": "string",
                    "description": (
                        "可选。IANA 时区名（如 Asia/Shanghai、America/New_York），"
                        "或常见别名（北京、纽约、东京、UTC）。省略则使用本机时区。"
                    ),
                }
            },
        },
    },
}


def _resolve_tz(raw: str | None) -> tuple[Any, str]:
    """返回 (tzinfo, timezone_label)。label 便于展示。"""
    key = (raw or "").strip()
    if not key or key.lower() in {"local", "本地", "本机"}:
        now = datetime.now().astimezone()
        label = getattr(now.tzinfo, "key", None) or now.tzname() or "local"
        return now.tzinfo, str(label)

    mapped = TZ_ALIASES.get(key) or TZ_ALIASES.get(key.lower())
    name = mapped or key
    try:
        tz = ZoneInfo(name)
    except ZoneInfoNotFoundError as e:
        raise ValueError(f"unknown timezone: {raw}") from e
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"invalid timezone: {raw}") from e
    return tz, name


def handle_current_time(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments or {}
    raw_tz = args.get("timezone")
    tz_arg = str(raw_tz).strip() if raw_tz not in (None, "") else ""
    try:
        tzinfo, tz_label = _resolve_tz(tz_arg or None)
    except ValueError as e:
        return {"error": str(e), "timezone": tz_arg}

    now = datetime.now(tzinfo)
    offset = now.strftime("%z")
    if offset and len(offset) >= 5:
        utc_offset = f"{offset[:3]}:{offset[3:]}"
    else:
        utc_offset = offset or ""
    weekday = WEEKDAYS[now.weekday()]
    display = (
        f"{now.year}年{now.month}月{now.day}日 {weekday} "
        f"{now.strftime('%H:%M:%S')}（{tz_label}，UTC{utc_offset}）"
    )
    return {
        "display": display,
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday,
        "timezone": tz_label,
        "utc_offset": utc_offset,
        "unix": int(now.timestamp()),
    }
