"""Agent 上下文管道分段（对齐 deer-flow middleware 职责，非 LangGraph）。"""

from __future__ import annotations

from app.agent.context.slash import resolve_slash_activation

__all__ = ["resolve_slash_activation"]
