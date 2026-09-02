"""
对话运行注册表（内存态）：支撑停止与确认闸。

chat_runs 表负责持久化状态；本模块负责运行中控制（cancel / confirm Event）。
确认超时默认 120s，按拒绝处理。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

CONFIRM_TIMEOUT_SEC = 120.0


class RunState:
    """单次对话运行的控制面。"""

    def __init__(self, run_id: str, session_id: str):
        self.run_id = run_id
        self.session_id = session_id
        self.cancel = asyncio.Event()
        self.confirms: Dict[str, dict] = {}
        self.pending_payload: dict[str, Any] | None = None
        self.started_at = time.time()

    def request_confirm(self, tool_call_id: str, payload: dict[str, Any] | None = None) -> None:
        self.confirms[tool_call_id] = {"event": asyncio.Event(), "result": None}
        if payload is not None:
            self.pending_payload = payload

    def resolve_confirm(self, tool_call_id: str, approve: bool) -> bool:
        slot = self.confirms.get(tool_call_id)
        if slot is None:
            # 兼容：仅有一个 pending 时按 run 级确认
            if self.pending_payload and not self.confirms:
                return False
            for s in self.confirms.values():
                if s["result"] is None:
                    s["result"] = approve
                    s["event"].set()
                    return True
            return False
        slot["result"] = approve
        slot["event"].set()
        return True

    async def wait_confirm(self, tool_call_id: str, timeout: float = CONFIRM_TIMEOUT_SEC) -> Optional[bool]:
        slot = self.confirms.get(tool_call_id)
        if slot is None:
            return None
        try:
            await asyncio.wait_for(slot["event"].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return slot["result"]

    def is_cancelled(self) -> bool:
        return self.cancel.is_set()


RUNS: Dict[str, RunState] = {}


def create_run(run_id: str, session_id: str) -> RunState:
    state = RunState(run_id, session_id)
    RUNS[run_id] = state
    return state


def get_run(run_id: str) -> RunState | None:
    return RUNS.get(run_id)


def stop_run(run_id: str, session_id: str | None = None) -> bool:
    state = RUNS.get(run_id)
    if state is None:
        return False
    if session_id is not None and state.session_id != session_id:
        return False
    state.cancel.set()
    for slot in state.confirms.values():
        if slot["result"] is None:
            slot["result"] = False
        slot["event"].set()
    return True


def stop_session(session_id: str) -> int:
    """停止该会话下所有进行中的 run（含前端尚未拿到真实 run_id 的情况）。"""
    stopped = 0
    for rid, state in list(RUNS.items()):
        if state.session_id == session_id:
            if stop_run(rid):
                stopped += 1
    return stopped


def finish_run(run_id: str) -> None:
    RUNS.pop(run_id, None)


def request_stop(run_id: str, session_id: str | None = None) -> None:
    """按 run_id 停止；run_id 无效或为 pending 时回退到 session 级停止。"""
    rid = (run_id or "").strip()
    if rid and rid != "pending" and stop_run(rid, session_id=session_id):
        return
    if session_id:
        stop_session(session_id)
    elif rid:
        stop_run(rid)
