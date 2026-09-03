"""会话级实时事件总线：定时任务 headless 执行时，打开中的会话可订阅流式思考/正文。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class _SessionLive:
    run_id: str
    session_id: str
    draft_reasoning: str = ""
    draft_content: str = ""
    ended: bool = False
    end_event: str | None = None
    end_data: dict[str, Any] = field(default_factory=dict)
    subscribers: list[asyncio.Queue] = field(default_factory=list)

    def _fanout(self, ev: dict[str, Any]) -> None:
        dead: list[asyncio.Queue] = []
        for q in self.subscribers:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                dead.append(q)
        if dead:
            self.subscribers = [q for q in self.subscribers if q not in dead]

    def publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        payload = dict(data or {})
        # 维护当前未落库轮次的草稿，供晚进入的订阅者一次性对齐
        if event == "status" and payload.get("phase") == "llm":
            self.draft_reasoning = ""
            self.draft_content = ""
        elif event in {"tool_start", "tool_confirm", "done", "error"}:
            if event == "tool_start":
                self.draft_reasoning = ""
                self.draft_content = ""
        elif event == "reasoning":
            self.draft_reasoning += str(payload.get("delta") or "")
        elif event == "token":
            self.draft_content += str(payload.get("delta") or payload.get("text") or "")

        self._fanout({"event": event, "data": payload})

    def finish(self, event: str = "done", data: dict[str, Any] | None = None) -> None:
        if self.ended:
            return
        self.ended = True
        self.end_event = event
        self.end_data = dict(data or {})
        self._fanout({"event": event, "data": self.end_data})
        self._fanout({"event": "live_closed", "data": {"run_id": self.run_id}})


class LiveBus:
    def __init__(self) -> None:
        self._by_session: dict[str, _SessionLive] = {}

    def begin(self, session_id: str, run_id: str) -> None:
        # 覆盖同会话旧 run（理论上不应并发）
        self._by_session[session_id] = _SessionLive(run_id=run_id, session_id=session_id)

    def publish(self, session_id: str, event: str, data: dict[str, Any] | None = None) -> None:
        live = self._by_session.get(session_id)
        if not live or live.ended:
            return
        live.publish(event, data)

    def end(self, session_id: str, *, event: str = "done", data: dict[str, Any] | None = None) -> None:
        live = self._by_session.get(session_id)
        if not live:
            return
        if not live.ended:
            live.finish(event, data)

    def drop(self, session_id: str, run_id: str | None = None) -> None:
        live = self._by_session.get(session_id)
        if not live:
            return
        if run_id and live.run_id != run_id:
            return
        self._by_session.pop(session_id, None)

    def get(self, session_id: str) -> _SessionLive | None:
        return self._by_session.get(session_id)

    async def subscribe(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """订阅当前 run：先对齐草稿，再推送后续事件；无活跃 run 时立即结束。"""
        live = self._by_session.get(session_id)
        if not live or live.ended:
            yield {
                "event": "live_idle",
                "data": {"session_id": session_id, "active": False},
            }
            return

        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        live.subscribers.append(q)
        try:
            yield {
                "event": "live_attached",
                "data": {
                    "session_id": session_id,
                    "run_id": live.run_id,
                    "active": True,
                },
            }
            if live.draft_reasoning or live.draft_content:
                yield {
                    "event": "live_sync",
                    "data": {
                        "run_id": live.run_id,
                        "reasoning": live.draft_reasoning,
                        "content": live.draft_content,
                    },
                }
            while True:
                ev = await q.get()
                yield ev
                if ev.get("event") in {"done", "error", "live_closed", "tool_confirm"}:
                    break
        finally:
            if q in live.subscribers:
                live.subscribers.remove(q)


live_bus = LiveBus()
