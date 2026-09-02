"""
Hermes 审批桥：将高风险工具标记为 needs_confirmation，复用 Runtime 确认闸。
"""

from __future__ import annotations

from typing import Any

from app.hermes_bridge.dispatch import classify_risk


def needs_confirmation(name: str, arguments: dict | None = None) -> bool:
    return classify_risk(name, arguments) == "high"


def approval_payload(
    *,
    run_id: str,
    tool_call_id: str,
    name: str,
    arguments: dict,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "tool_call_id": tool_call_id,
        "name": name,
        "arguments": arguments,
        "risk": classify_risk(name, arguments),
        "source": "hermes_approval",
    }
