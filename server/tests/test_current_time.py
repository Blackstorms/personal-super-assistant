"""内置 current_time 工具。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.agent.current_time import handle_current_time
from app.agent.risk import classify_risk, classify_source


def test_current_time_local_fields():
    out = handle_current_time({})
    assert "error" not in out
    assert out["weekday"] in {
        "星期一",
        "星期二",
        "星期三",
        "星期四",
        "星期五",
        "星期六",
        "星期日",
    }
    assert out["date"] == datetime.now().strftime("%Y-%m-%d")
    assert "display" in out
    assert out["iso"]
    assert isinstance(out["unix"], int)


def test_current_time_timezone_alias():
    out = handle_current_time({"timezone": "北京"})
    assert out["timezone"] == "Asia/Shanghai"
    assert "+08:00" in out["utc_offset"] or out["utc_offset"].startswith("+08")


def test_current_time_iana():
    out = handle_current_time({"timezone": "UTC"})
    assert out["timezone"] == "UTC"
    assert "error" not in out


def test_current_time_invalid_timezone():
    out = handle_current_time({"timezone": "Not/AZone"})
    assert "error" in out


def test_current_time_risk_and_source():
    assert classify_risk("current_time", {}) == "low"
    assert classify_source("current_time") == "builtin_time"


def test_current_time_on_builtin_surface():
    from app.agent.tool_router import BUILTIN_TOOLS

    names = {((t.get("function") or {}).get("name") or "") for t in BUILTIN_TOOLS}
    assert "current_time" in names


@pytest.mark.asyncio
async def test_dispatch_current_time():
    from unittest.mock import MagicMock

    from app.agent.tool_router import dispatch

    result, source, risk = await dispatch(MagicMock(), MagicMock(), "current_time", {})
    assert source == "builtin_time"
    assert risk == "low"
    assert "display" in result
    assert "error" not in result


def test_mock_calls_current_time():
    from app.llm.gateway import MockLLMGateway

    gw = MockLLMGateway()
    tools = [{"type": "function", "function": {"name": "current_time"}}]
    kind, payload = gw._decide([{"role": "user", "content": "现在几点了"}], tools)
    assert kind == "tool"
    assert payload[0]["function"]["name"] == "current_time"
