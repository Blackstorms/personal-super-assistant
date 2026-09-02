"""
Agent Runtime 编排入口：Slash → Context → ToolLoop → AfterAgent。

能力在 hermes_bridge / SkillRegistry；本模块只编排 lifespan 级对话入口。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator

import aiosqlite

from app.agent.after_agent import async_extract_memory
from app.agent.compress import estimate_tokens
from app.agent.context_builder import (
    build_messages,
    resolve_session_bindings,
    skill_allow_set,
)
from app.agent.llm_loader import load_llm
from app.agent.runs import create_run, finish_run, request_stop
from app.agent.session_title import maybe_auto_title
from app.agent.tool_loop import (
    load_pending_from_db,
    pop_pending,
    resume_after_confirm,
    run_tool_loop,
)
from app.agent.tool_router import BUILTIN_TOOLS, build_tool_surface, dispatch as execute_tool
from app.core.config import settings
from app.db.database import utc_now
from app.skills.registry import SkillRegistry

# 兼容旧 import：checklist / memories / session_title
_load_llm = load_llm

__all__ = [
    "request_stop",
    "run_chat_stream",
    "run_chat_collect",
    "confirm_tool",
    "execute_tool",
    "BUILTIN_TOOLS",
    "build_messages",
    "_load_llm",
    "load_llm",
]


def short_server_id(server_id: str) -> str:
    return server_id.replace("-", "")[:8]


async def run_chat_stream(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    session_id: str,
    user_content: str,
    *,
    enable_skills: bool = True,
    enable_mcp: bool = True,
    enable_memory: bool = True,
    enable_knowledge: bool = True,
    mcp_manager: Any | None = None,
    mcp_tools: list[dict] | None = None,
    model_profile_id: str | None = None,
    expert_id: str | None = None,
    knowledge_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    mcp_ids: list[str] | None = None,
    use_attachments: bool = False,
    bypass_whitelist: bool = False,
) -> AsyncIterator[dict]:
    """主对话生成器，yield 已结构化的 SSE 事件 dict。"""
    del mcp_tools  # API 兼容；工具面由 build_tool_surface 统一组装
    run_id = str(uuid.uuid4())
    run_state = create_run(run_id, session_id)
    cur = await db.execute("SELECT workspace_id FROM sessions WHERE id=?", (session_id,))
    sess = await cur.fetchone()

    # 持久化本轮 composer 绑定，供下次打开会话反填
    from app.agent.session_bindings import save_session_composer_bindings

    await save_session_composer_bindings(
        db,
        session_id,
        {
            "expert_id": expert_id,
            "skill_ids": skill_ids,
            "mcp_ids": mcp_ids,
            "knowledge_ids": knowledge_ids,
            "model_profile_id": model_profile_id,
        },
    )
    if not sess:
        finish_run(run_id)
        yield {"event": "error", "data": {"code": "not_found", "message": "session not found"}}
        return
    workspace_id = sess["workspace_id"]

    bindings = await resolve_session_bindings(
        db,
        workspace_id,
        expert_id=expert_id,
        knowledge_ids=knowledge_ids,
        skill_ids=skill_ids,
        mcp_ids=mcp_ids,
        model_profile_id=model_profile_id,
    )
    resolved_expert = bindings["expert_id"]
    resolved_knowledge = bindings["knowledge_ids"]
    resolved_model = bindings["model_profile_id"]
    project_instructions = bindings["project_instructions"]
    resolved_skill_ids: list[str] | None = bindings["skill_ids"]
    resolved_mcp_ids: list[str] | None = bindings["mcp_ids"]
    allowed_skill_ids = skill_allow_set(resolved_skill_ids)

    slash = None
    if enable_skills:
        from app.agent.context.slash import resolve_slash_activation

        slash = await resolve_slash_activation(user_content, registry, allowed_skill_ids)
    effective_user = slash.remaining_content if slash else user_content
    content_for_match = effective_user

    await db.execute(
        "INSERT INTO chat_runs(id, session_id, status, started_at) VALUES(?,?,?,?)",
        (run_id, session_id, "running", utc_now()),
    )
    user_msg_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO messages(id, session_id, role, content, status, token_estimate, created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            user_msg_id,
            session_id,
            "user",
            user_content,
            "complete",
            estimate_tokens(user_content),
            utc_now(),
        ),
    )
    await db.execute(
        "UPDATE sessions SET message_count=message_count+1, updated_at=? WHERE id=?",
        (utc_now(), session_id),
    )
    await db.commit()

    # 尽早通知前端进入思考态（标题生成可能较慢）
    yield {"event": "run_started", "data": {"run_id": run_id, "session_id": session_id}}

    auto_title = await maybe_auto_title(db, session_id, effective_user, resolved_model)
    if auto_title:
        yield {"event": "session_title", "data": {"session_id": session_id, "title": auto_title}}

    if slash:
        yield {
            "event": "skill_activated",
            "data": {"skill_id": slash.skill_id, "via": "slash"},
        }

    llm = await load_llm(db, resolved_model)

    from app.fs import session_attachments as sa

    attachment_snippets: list[dict] = []
    attachment_mode = use_attachments
    if attachment_mode:
        attachment_snippets = await sa.load_context_snippets(db, session_id)
        if attachment_snippets:
            enable_knowledge = False
            resolved_knowledge = []
        else:
            attachment_mode = False

    messages, hints = await build_messages(
        db,
        registry,
        session_id,
        effective_user,
        enable_skills=enable_skills,
        enable_memory=enable_memory,
        enable_knowledge=enable_knowledge,
        workspace_id=workspace_id,
        expert_id=resolved_expert,
        knowledge_ids=resolved_knowledge,
        project_instructions=project_instructions,
        llm=llm,
        slash_reminder=slash.reminder if slash else None,
        content_for_match=content_for_match,
        session_attachments=attachment_snippets or None,
        attachment_mode=attachment_mode,
        allowed_skill_ids=allowed_skill_ids,
        bypass_whitelist=bypass_whitelist,
    )
    if hints.get("attachments"):
        yield {"event": "attachments_loaded", "data": {"items": hints["attachments"]}}
    if hints.get("memory_ids"):
        yield {
            "event": "memory_hint",
            "data": {"memory_ids": hints["memory_ids"], "preview": hints["memory_ids"]},
        }
    if hints.get("knowledge"):
        yield {"event": "knowledge_hit", "data": {"items": hints["knowledge"]}}

    # 每轮都推送上下文用量；压缩时额外带 before/after
    limit_tok = int(hints.get("limit_tokens") or 32000)
    used_tok = int(hints.get("used_tokens") or hints.get("after_tokens") or 0)
    pct = round(min(100.0, (used_tok / limit_tok) * 100), 1) if limit_tok > 0 else 0.0
    usage_data = {
        "used_tokens": used_tok,
        "raw_tokens": int(hints.get("before_tokens") or used_tok),
        "limit_tokens": limit_tok,
        "percent": pct,
        "message_count": hints.get("message_count"),
        "max_messages": hints.get("max_messages"),
        "compressed": bool(hints.get("compressed")),
        "has_summary": bool(hints.get("has_summary")),
        "kept_messages": hints.get("kept_messages"),
        "summarized_messages": hints.get("summarized_messages"),
        "near_limit": pct >= 80,
        "breakdown": hints.get("breakdown") or {},
    }
    yield {"event": "context_usage", "data": usage_data}
    if hints.get("compressed"):
        yield {
            "event": "compress",
            "data": {
                "before_tokens": hints["before_tokens"],
                "after_tokens": hints["after_tokens"],
                "kept_messages": hints.get("kept_messages"),
                "summarized_messages": hints.get("summarized_messages"),
                **usage_data,
            },
        }

    tools = await build_tool_surface(
        db,
        registry,
        enable_skills=enable_skills,
        enable_mcp=enable_mcp,
        enable_fs_write=settings.enable_chat_fs_write,
        allowed_skill_ids=allowed_skill_ids,
        mcp_ids=resolved_mcp_ids,
        mcp_manager=mcp_manager,
        slash_permissions=getattr(slash, "permissions", None) if slash else None,
    )

    yield {
        "event": "tool_surface",
        "data": {
            "tool_count": len(tools),
            "skill_tools": sum(
                1
                for t in tools
                if ((t.get("function") or {}).get("name") or "")
                in {"skills_list", "skill_view", "skill_manage", "describe_skill", "run_skill"}
            ),
            "mcp_tools": sum(
                1
                for t in tools
                if ((t.get("function") or {}).get("name") or "").startswith("mcp__")
            ),
        },
    }

    done_ok = False
    async for ev in run_tool_loop(
        db,
        registry,
        llm,
        messages,
        tools,
        run_id=run_id,
        session_id=session_id,
        workspace_id=workspace_id,
        run_state=run_state,
        mcp_manager=mcp_manager,
        allowed_skill_ids=allowed_skill_ids,
        knowledge_ids=resolved_knowledge if resolved_knowledge else None,
        bypass_whitelist=bypass_whitelist,
        enable_memory=enable_memory,
        model_profile_id=resolved_model,
    ):
        yield ev
        if ev.get("event") == "done" and not (ev.get("data") or {}).get("rejected"):
            done_ok = True

    if enable_memory and done_ok:
        asyncio.create_task(async_extract_memory(session_id, resolved_model))


async def run_chat_collect(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    session_id: str,
    user_content: str,
    *,
    enable_skills: bool = True,
    enable_mcp: bool = True,
    enable_memory: bool = True,
    enable_knowledge: bool = True,
    mcp_manager: Any | None = None,
    model_profile_id: str | None = None,
    expert_id: str | None = None,
    knowledge_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    mcp_ids: list[str] | None = None,
    bypass_whitelist: bool = False,
) -> dict[str, Any]:
    """Headless 包装：消费 run_chat_stream，返回汇总结果（定时任务用）。"""
    assistant_parts: list[str] = []
    run_id: str | None = None
    needs_confirm = False
    error: str | None = None
    message_id: str | None = None

    async for ev in run_chat_stream(
        db,
        registry,
        session_id,
        user_content,
        enable_skills=enable_skills,
        enable_mcp=enable_mcp,
        enable_memory=enable_memory,
        enable_knowledge=enable_knowledge,
        mcp_manager=mcp_manager,
        model_profile_id=model_profile_id,
        expert_id=expert_id,
        knowledge_ids=knowledge_ids,
        skill_ids=skill_ids,
        mcp_ids=mcp_ids,
        use_attachments=False,
        bypass_whitelist=bypass_whitelist,
    ):
        event = ev.get("event")
        data = ev.get("data") or {}
        if event == "run_started":
            run_id = data.get("run_id") or run_id
        elif event == "token":
            assistant_parts.append(str(data.get("delta") or data.get("text") or ""))
        elif event == "tool_confirm":
            needs_confirm = True
            run_id = data.get("run_id") or run_id
            break
        elif event == "error":
            error = str(data.get("message") or data.get("code") or "error")
        elif event == "done":
            message_id = data.get("message_id")

    text = "".join(assistant_parts).strip()
    status = "success"
    if error:
        status = "failed"
    elif needs_confirm:
        status = "needs_confirmation"
        if not error:
            error = "high-risk tool requires confirmation; scheduled run stopped"

    return {
        "status": status,
        "run_id": run_id,
        "message_id": message_id,
        "assistant_text": text,
        "error": error,
        "needs_confirmation": needs_confirm,
    }


async def confirm_tool(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    run_id: str,
    tool_call_id: str,
    approve: bool,
    mcp_manager: Any | None = None,
) -> AsyncIterator[dict]:
    """确认或拒绝高风险工具，并继续完整 Tool-Loop。"""
    from app.agent.runs import get_run

    pending = pop_pending(run_id)
    state = get_run(run_id)
    if state:
        state.resolve_confirm(tool_call_id, approve)
        if pending is None and state.pending_payload:
            pending = state.pending_payload
    if pending is None:
        pending = await load_pending_from_db(db, run_id)
    if not pending:
        yield {"event": "error", "data": {"code": "no_pending", "message": "no pending confirm"}}
        return

    async for ev in resume_after_confirm(
        db,
        registry,
        run_id=run_id,
        tool_call_id=tool_call_id,
        approve=approve,
        pending=pending,
        mcp_manager=mcp_manager,
    ):
        yield ev
