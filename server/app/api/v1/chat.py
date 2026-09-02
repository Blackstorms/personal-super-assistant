"""对话 SSE API。"""

from __future__ import annotations

import json

import aiosqlite
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.agent import runtime as agent_runtime
from app.core.security import require_token
from app.db.deps import db_dep, skill_registry
from app.mcp.manager import mcp_manager

router = APIRouter(dependencies=[Depends(require_token)])


class StreamBody(BaseModel):
    session_id: str
    content: str
    parent_message_id: str | None = None
    enable_skills: bool = True
    enable_mcp: bool = True
    enable_memory: bool = True
    enable_knowledge: bool = True
    model_profile_id: str | None = None
    expert_id: str | None = None
    knowledge_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    mcp_ids: list[str] | None = None
    use_attachments: bool = False


class StopBody(BaseModel):
    session_id: str
    run_id: str = ""


class ConfirmBody(BaseModel):
    session_id: str
    run_id: str
    tool_call_id: str
    approve: bool = True


async def _event_source(agen):
    async for ev in agen:
        yield {
            "event": ev["event"],
            "data": json.dumps(ev.get("data") or {}, ensure_ascii=False),
        }


@router.post("/stream")
async def chat_stream(
    body: StreamBody,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """F6：流式对话（SSE）。"""
    registry = skill_registry(request)
    # 对话热路径不预取 mcp_manager 工具表；由 build_tool_surface / Hermes 独占
    tools: list = []

    return EventSourceResponse(
        _event_source(
            agent_runtime.run_chat_stream(
                db,
                registry,
                body.session_id,
                body.content,
                enable_skills=body.enable_skills,
                enable_mcp=body.enable_mcp,
                enable_memory=body.enable_memory,
                enable_knowledge=body.enable_knowledge,
                mcp_manager=mcp_manager,
                mcp_tools=tools,
                model_profile_id=body.model_profile_id,
                expert_id=body.expert_id,
                knowledge_ids=body.knowledge_ids,
                skill_ids=body.skill_ids,
                mcp_ids=body.mcp_ids,
                use_attachments=body.use_attachments,
            )
        ),
        ping=15000,
    )


@router.post("/stop")
async def chat_stop(body: StopBody):
    agent_runtime.request_stop(body.run_id, session_id=body.session_id)
    return {"ok": True}


@router.post("/confirm")
async def chat_confirm(
    body: ConfirmBody,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    registry = skill_registry(request)
    return EventSourceResponse(
        _event_source(
            agent_runtime.confirm_tool(
                db,
                registry,
                body.run_id,
                body.tool_call_id,
                approve=True,
                mcp_manager=mcp_manager,
            )
        )
    )


@router.post("/reject")
async def chat_reject(
    body: ConfirmBody,
    request: Request,
    db: aiosqlite.Connection = Depends(db_dep),
):
    registry = skill_registry(request)
    return EventSourceResponse(
        _event_source(
            agent_runtime.confirm_tool(
                db,
                registry,
                body.run_id,
                body.tool_call_id,
                approve=False,
                mcp_manager=mcp_manager,
            )
        )
    )
