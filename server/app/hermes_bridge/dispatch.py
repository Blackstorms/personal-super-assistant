"""
将工具调用转发给 Hermes registry / handle_function_call。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.agent.budget import truncate_tool_result

logger = logging.getLogger(__name__)


def classify_source(name: str) -> str:
    from app.agent.risk import classify_source as _classify_source

    return _classify_source(name)


def classify_risk(name: str, arguments: dict | None = None) -> str:
    """委托 agent.risk 表驱动分类（含 Hermes 危险 toolset / MCP 黑名单）。"""
    from app.agent.risk import classify_risk as _classify_risk

    return _classify_risk(name, arguments)


async def dispatch_hermes_tool(
    name: str,
    arguments: dict,
    *,
    session_id: str | None = None,
) -> Any:
    """在线程中调用 Hermes handle_function_call，结果做预算截断。"""
    from app.hermes_bridge.paths import ensure_hermes_on_syspath

    if not ensure_hermes_on_syspath():
        return {"error": "hermes_unavailable", "tool": name}

    def _run() -> Any:
        try:
            from model_tools import handle_function_call  # type: ignore

            result = handle_function_call(
                name,
                arguments or {},
                session_id=session_id,
                task_id=session_id,
                # 嵌入宿主不走 Hermes plugin middleware，避免缺 registration_lifecycle 等模块直接炸工具
                skip_tool_execution_middleware=True,
            )
            if isinstance(result, (dict, list)):
                return result
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except Exception:  # noqa: BLE001
                    return {"result": result}
            return {"result": result}
        except Exception as e:  # noqa: BLE001
            logger.exception("hermes dispatch failed: %s", name)
            return {"error": str(e), "tool": name}

    raw = await asyncio.to_thread(_run)
    return truncate_tool_result(raw)
