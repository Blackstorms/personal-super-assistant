"""
共用 Tool-Loop：供 /chat/stream 与 /chat/confirm 共用。

- 最多 max_rounds 轮 LLM↔tools
- 高风险工具写入 pending（内存 + chat_runs.pending_json）后 yield tool_confirm 并返回
- 确认恢复：执行已批准工具 → 补完同批 sibling → 继续剩余轮次
- 循环检测：连续相同 (name, args) 打断
- 工具异常一律写成 role=tool 的 ToolMessage
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

import aiosqlite

from app.agent.budget import truncate_tool_result
from app.agent.compress import estimate_tokens
from app.agent.risk import canonical_tool_key, classify_risk
from app.agent.runs import CONFIRM_TIMEOUT_SEC, finish_run, get_run
from app.agent.tool_router import dispatch as execute_tool
from app.db.database import get_db, utc_now
from app.llm.gateway import LLMGateway
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
LOOP_DETECT_LIMIT = 3
# 因 max_tokens 截断时，自动续写的最大次数（不占用工具轮次语义上另计）
MAX_LENGTH_CONTINUES = 2

# 进程内 pending（与 chat_runs.pending_json 双写）
_pending_confirms: dict[str, dict[str, Any]] = {}


def set_pending(run_id: str, payload: dict[str, Any]) -> None:
    _pending_confirms[run_id] = payload


def sanitize_tool_round_content(content: str, reasoning: str) -> str:
    """有 tool_calls 时丢掉短乱码 stub，避免落库后被当成正文。"""
    c = (content or "").strip()
    r = (reasoning or "").strip()
    if not c:
        return ""
    if len(c) <= 80 and len(r) >= 100:
        return ""
    if len(c) <= 120 and len(r) >= max(200, len(c) * 10):
        return ""
    return content or ""


def get_pending(run_id: str) -> dict[str, Any] | None:
    return _pending_confirms.get(run_id)


def pop_pending(run_id: str) -> dict[str, Any] | None:
    return _pending_confirms.pop(run_id, None)


async def save_pending_json(db: aiosqlite.Connection, run_id: str, payload: dict[str, Any] | None) -> None:
    raw = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    try:
        await db.execute(
            "UPDATE chat_runs SET pending_json=? WHERE id=?",
            (raw, run_id),
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        # 旧库尚未 migrate 时忽略
        logger.debug("save pending_json failed", exc_info=True)


async def load_pending_from_db(db: aiosqlite.Connection, run_id: str) -> dict[str, Any] | None:
    try:
        cur = await db.execute("SELECT pending_json FROM chat_runs WHERE id=?", (run_id,))
        row = await cur.fetchone()
        if not row:
            return None
        try:
            raw = row["pending_json"]
        except (KeyError, IndexError):
            return None
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


async def _audit(
    db: aiosqlite.Connection,
    *,
    workspace_id: str | None,
    session_id: str,
    run_id: str,
    tool_call_id: str,
    name: str,
    source: str,
    arguments: dict,
    result: Any,
    is_error: bool,
    risk: str,
    confirm_status: str,
    duration_ms: int,
) -> None:
    await db.execute(
        """
        INSERT INTO tool_call_audits(
          id, workspace_id, session_id, run_id, tool_call_id, name, source,
          arguments_json, result_json, is_error, risk, confirm_status, duration_ms, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(uuid.uuid4()),
            workspace_id,
            session_id,
            run_id,
            tool_call_id,
            name,
            source,
            json.dumps(arguments, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
            1 if is_error else 0,
            risk,
            confirm_status,
            duration_ms,
            utc_now(),
        ),
    )
    await db.commit()


def _parse_args(tc: dict) -> dict:
    try:
        return json.loads(tc["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        return {}


async def _persist_tool_message(
    db: aiosqlite.Connection,
    session_id: str,
    tool_call_id: str,
    result_str: str,
) -> None:
    await db.execute(
        """
        INSERT INTO messages(id, session_id, role, content, tool_call_id, status, created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (str(uuid.uuid4()), session_id, "tool", result_str, tool_call_id, "complete", utc_now()),
    )
    await db.commit()


async def _execute_one(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    *,
    name: str,
    args: dict,
    mcp_manager: Any | None,
    session_id: str,
    allowed_skill_ids: set[str] | None,
    knowledge_ids: list[str] | None,
    bypass_whitelist: bool,
) -> tuple[Any, str, str, bool]:
    try:
        result, source, risk = await execute_tool(
            db,
            registry,
            name,
            args,
            mcp_manager,
            session_id=session_id,
            allowed_skill_ids=allowed_skill_ids,
            knowledge_ids=knowledge_ids,
            bypass_whitelist=bypass_whitelist,
        )
        is_error = isinstance(result, dict) and bool(result.get("error"))
    except Exception as e:  # noqa: BLE001
        result, source, risk = {"error": str(e)}, "error", classify_risk(name, args)
        is_error = True
    result = truncate_tool_result(result)
    return result, source, risk, is_error


async def _schedule_timeout_reject(run_id: str, tool_call_id: str) -> None:
    await asyncio.sleep(CONFIRM_TIMEOUT_SEC)
    st = get_run(run_id)
    if st is None:
        return
    slot = st.confirms.get(tool_call_id)
    if slot and slot["result"] is None:
        st.resolve_confirm(tool_call_id, False)
        pop_pending(run_id)
        try:
            _db = await get_db()
            try:
                await _db.execute(
                    "UPDATE chat_runs SET status=?, finished_at=?, pending_json=NULL WHERE id=? AND status=?",
                    ("timeout_rejected", utc_now(), run_id, "waiting_confirm"),
                )
                await _db.commit()
            finally:
                await _db.close()
        except Exception:  # noqa: BLE001
            logger.debug("timeout reject db update failed", exc_info=True)


def preview_confirm_arguments(name: str, args: dict | None) -> dict:
    """SSE/UI 用短预览；完整参数仍只存在 pending（避免大文件内容卡死前端）。"""
    raw = dict(args or {})
    preview: dict = {}
    path = raw.get("path")
    if isinstance(path, str) and path:
        preview["path"] = path
    content = raw.get("content")
    if isinstance(content, str):
        n = len(content)
        preview["content_chars"] = n
        preview["content_preview"] = (
            content[:160] + f"…（共 {n} 字，确认后写入完整内容）" if n > 200 else content
        )
    for k, v in raw.items():
        if k in ("path", "content"):
            continue
        if isinstance(v, str) and len(v) > 400:
            preview[k] = v[:120] + f"…（共 {len(v)} 字）"
        else:
            preview[k] = v
    if name and "path" not in preview and "content_preview" not in preview:
        return preview or raw
    return preview


async def _pause_for_confirm(
    db: aiosqlite.Connection,
    *,
    run_id: str,
    run_state: Any,
    session_id: str,
    workspace_id: str | None,
    tc: dict,
    args: dict,
    messages: list[dict],
    tools: list[dict],
    remaining_siblings: list[dict],
    rounds_left: int,
    model_profile_id: str | None,
    enable_memory: bool,
    allowed_skill_ids: set[str] | None,
    knowledge_ids: list[str] | None,
    bypass_whitelist: bool,
    risk: str,
) -> AsyncIterator[dict]:
    payload = {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "tool_call": tc,
        "arguments": args,
        "messages": messages,
        "tools": tools,
        "remaining_siblings": remaining_siblings,
        "rounds_left": rounds_left,
        "model_profile_id": model_profile_id,
        "enable_memory": enable_memory,
        "allowed_skill_ids": list(allowed_skill_ids) if allowed_skill_ids is not None else None,
        "knowledge_ids": list(knowledge_ids) if knowledge_ids else None,
        "bypass_whitelist": bypass_whitelist,
    }
    set_pending(run_id, payload)
    run_state.request_confirm(tc["id"], payload)
    await save_pending_json(db, run_id, payload)
    asyncio.create_task(_schedule_timeout_reject(run_id, tc["id"]))
    await db.execute(
        "UPDATE chat_runs SET status=? WHERE id=?",
        ("waiting_confirm", run_id),
    )
    await db.commit()
    tool_name = tc["function"]["name"]
    yield {
        "event": "tool_confirm",
        "data": {
            "tool_call_id": tc["id"],
            "name": tool_name,
            # 勿把完整大文件 content 推进 SSE/IPC，否则前端易卡住且看不到确认条
            "arguments": preview_confirm_arguments(tool_name, args),
            "risk": risk,
            "run_id": run_id,
            "timeout_sec": int(CONFIRM_TIMEOUT_SEC),
        },
    }
    # 明确结束本段 SSE，避免前端一直等 done 而转圈
    yield {
        "event": "done",
        "data": {
            "run_id": run_id,
            "status": "waiting_confirm",
            "tool_call_id": tc["id"],
            "message_id": None,
        },
    }


async def run_tool_loop(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    llm: LLMGateway,
    messages: list[dict],
    tools: list[dict],
    *,
    run_id: str,
    session_id: str,
    workspace_id: str | None,
    run_state: Any,
    mcp_manager: Any | None = None,
    allowed_skill_ids: set[str] | None = None,
    knowledge_ids: list[str] | None = None,
    bypass_whitelist: bool = False,
    enable_memory: bool = True,
    model_profile_id: str | None = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
    initial_assistant_text: str = "",
) -> AsyncIterator[dict]:
    """从当前 messages 开始跑 Tool-Loop，yield SSE 事件 dict。"""
    assistant_text = initial_assistant_text
    assistant_reasoning = ""
    final_message_id = str(uuid.uuid4())
    recent_keys: list[str] = []
    length_continues = 0

    for round_i in range(max_rounds):
        if run_state.is_cancelled():
            await db.execute(
                "UPDATE chat_runs SET status=?, finished_at=?, pending_json=NULL WHERE id=?",
                ("stopped", utc_now(), run_id),
            )
            await db.commit()
            finish_run(run_id)
            yield {
                "event": "done",
                "data": {"run_id": run_id, "status": "stopped", "message_id": final_message_id},
            }
            return

        tool_calls = None
        finish_reason: str | None = None
        yield {
            "event": "status",
            "data": {
                "phase": "llm",
                "round": round_i + 1,
                "message": f"正在调用模型（第 {round_i + 1} 轮）…",
            },
        }
        try:
            async for ev in llm.stream_chat(
                messages,
                tools=tools,
                should_stop=run_state.is_cancelled,
            ):
                if run_state.is_cancelled():
                    break
                if ev["type"] == "reasoning":
                    assistant_reasoning += ev["delta"]
                    yield {"event": "reasoning", "data": {"delta": ev["delta"]}}
                elif ev["type"] == "token":
                    assistant_text += ev["delta"]
                    yield {"event": "token", "data": {"delta": ev["delta"]}}
                elif ev["type"] == "tool_calls":
                    tool_calls = ev["tool_calls"]
                elif ev["type"] == "error":
                    msg = str(ev.get("message") or "llm error")
                    await db.execute(
                        "UPDATE chat_runs SET status=?, error_message=?, finished_at=?, pending_json=NULL WHERE id=?",
                        ("error", msg, utc_now(), run_id),
                    )
                    await db.commit()
                    finish_run(run_id)
                    yield {
                        "event": "error",
                        "data": {"code": ev.get("code") or "llm_error", "message": msg},
                    }
                    yield {
                        "event": "done",
                        "data": {"run_id": run_id, "status": "error", "message_id": final_message_id},
                    }
                    return
                elif ev["type"] == "done":
                    fr = ev.get("finish_reason")
                    if isinstance(fr, str) and fr:
                        finish_reason = fr
        except Exception as e:  # noqa: BLE001
            await db.execute(
                "UPDATE chat_runs SET status=?, error_message=?, finished_at=?, pending_json=NULL WHERE id=?",
                ("error", str(e), utc_now(), run_id),
            )
            await db.commit()
            finish_run(run_id)
            yield {"event": "error", "data": {"code": "llm_error", "message": str(e)}}
            return

        if run_state.is_cancelled():
            await db.execute(
                "UPDATE chat_runs SET status=?, finished_at=?, pending_json=NULL WHERE id=?",
                ("stopped", utc_now(), run_id),
            )
            await db.commit()
            finish_run(run_id)
            yield {
                "event": "done",
                "data": {"run_id": run_id, "status": "stopped", "message_id": final_message_id},
            }
            return

        if not tool_calls:
            # 输出长度截断：独立续写，不依赖剩余工具轮次
            while (
                finish_reason == "length"
                and length_continues < MAX_LENGTH_CONTINUES
                and (assistant_text or assistant_reasoning).strip()
                and not run_state.is_cancelled()
            ):
                length_continues += 1
                logger.info(
                    "llm finish_reason=length, auto-continue %s/%s run=%s",
                    length_continues,
                    MAX_LENGTH_CONTINUES,
                    run_id,
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text or "",
                        **(
                            {"reasoning_content": assistant_reasoning}
                            if assistant_reasoning
                            else {}
                        ),
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "上一段输出因长度限制被截断。请从断点处继续写完整，"
                            "不要重复已写出的内容，直接接着最后一句往下写。"
                        ),
                    }
                )
                assistant_reasoning = ""
                finish_reason = None
                yield {
                    "event": "tool_surface",
                    "data": {
                        "note": "output_truncated_continuing",
                        "continue": length_continues,
                    },
                }
                try:
                    async for ev in llm.stream_chat(
                        messages,
                        tools=None,
                        should_stop=run_state.is_cancelled,
                    ):
                        if run_state.is_cancelled():
                            break
                        if ev["type"] == "reasoning":
                            assistant_reasoning += ev["delta"]
                            yield {"event": "reasoning", "data": {"delta": ev["delta"]}}
                        elif ev["type"] == "token":
                            assistant_text += ev["delta"]
                            yield {"event": "token", "data": {"delta": ev["delta"]}}
                        elif ev["type"] == "error":
                            msg = str(ev.get("message") or "llm error")
                            await db.execute(
                                "UPDATE chat_runs SET status=?, error_message=?, finished_at=?, pending_json=NULL WHERE id=?",
                                ("error", msg, utc_now(), run_id),
                            )
                            await db.commit()
                            finish_run(run_id)
                            yield {
                                "event": "error",
                                "data": {"code": ev.get("code") or "llm_error", "message": msg},
                            }
                            yield {
                                "event": "done",
                                "data": {
                                    "run_id": run_id,
                                    "status": "error",
                                    "message_id": final_message_id,
                                },
                            }
                            return
                        elif ev["type"] == "done":
                            fr = ev.get("finish_reason")
                            if isinstance(fr, str) and fr:
                                finish_reason = fr
                except Exception as e:  # noqa: BLE001
                    await db.execute(
                        "UPDATE chat_runs SET status=?, error_message=?, finished_at=?, pending_json=NULL WHERE id=?",
                        ("error", str(e), utc_now(), run_id),
                    )
                    await db.commit()
                    finish_run(run_id)
                    yield {"event": "error", "data": {"code": "llm_error", "message": str(e)}}
                    return

            if run_state.is_cancelled():
                await db.execute(
                    "UPDATE chat_runs SET status=?, finished_at=?, pending_json=NULL WHERE id=?",
                    ("stopped", utc_now(), run_id),
                )
                await db.commit()
                finish_run(run_id)
                yield {
                    "event": "done",
                    "data": {"run_id": run_id, "status": "stopped", "message_id": final_message_id},
                }
                return

            # 思考只留在 reasoning_content / 思考区，绝不提升为正文 token
            break

        persist_content = sanitize_tool_round_content(assistant_text, assistant_reasoning)
        messages.append(
            {
                "role": "assistant",
                "content": persist_content,
                "tool_calls": tool_calls,
                **({"reasoning_content": assistant_reasoning} if assistant_reasoning else {}),
            }
        )
        await db.execute(
            """
            INSERT INTO messages(
              id, session_id, role, content, reasoning_content, tool_calls_json, status, created_at
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                "assistant",
                persist_content,
                assistant_reasoning or None,
                json.dumps(tool_calls, ensure_ascii=False),
                "complete",
                utc_now(),
            ),
        )
        await db.commit()
        assistant_text = ""
        assistant_reasoning = ""

        for idx, tc in enumerate(tool_calls):
            name = tc["function"]["name"]
            args = _parse_args(tc)
            risk = classify_risk(name, args)
            yield {
                "event": "tool_start",
                "data": {"tool_call_id": tc["id"], "name": name, "arguments": args},
            }

            key = canonical_tool_key(name, args)
            recent_keys.append(key)
            if len(recent_keys) >= LOOP_DETECT_LIMIT and len(set(recent_keys[-LOOP_DETECT_LIMIT:])) == 1:
                result = {
                    "error": "loop_detected",
                    "message": f"相同工具连续调用 {LOOP_DETECT_LIMIT} 次，已中断",
                    "tool": name,
                }
                result_str = json.dumps(result, ensure_ascii=False)
                await _audit(
                    db,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    run_id=run_id,
                    tool_call_id=tc["id"],
                    name=name,
                    source="loop_guard",
                    arguments=args,
                    result=result,
                    is_error=True,
                    risk=risk,
                    confirm_status="none",
                    duration_ms=0,
                )
                yield {
                    "event": "tool_result",
                    "data": {
                        "tool_call_id": tc["id"],
                        "name": name,
                        "result": result,
                        "is_error": True,
                    },
                }
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})
                await _persist_tool_message(db, session_id, tc["id"], result_str)
                # 同批剩余补占位，避免 dangling
                for sib in tool_calls[idx + 1 :]:
                    sib_name = sib["function"]["name"]
                    placeholder = {
                        "error": "skipped_due_to_loop",
                        "tool": sib_name,
                    }
                    ps = json.dumps(placeholder, ensure_ascii=False)
                    messages.append({"role": "tool", "tool_call_id": sib["id"], "content": ps})
                    await _persist_tool_message(db, session_id, sib["id"], ps)
                    yield {
                        "event": "tool_result",
                        "data": {
                            "tool_call_id": sib["id"],
                            "name": sib_name,
                            "result": placeholder,
                            "is_error": True,
                        },
                    }
                assistant_text = "检测到工具循环调用，已停止继续执行。"
                break

            if risk == "high":
                remaining = tool_calls[idx + 1 :]
                rounds_left = max_rounds - round_i - 1
                async for ev in _pause_for_confirm(
                    db,
                    run_id=run_id,
                    run_state=run_state,
                    session_id=session_id,
                    workspace_id=workspace_id,
                    tc=tc,
                    args=args,
                    messages=messages,
                    tools=tools,
                    remaining_siblings=remaining,
                    rounds_left=rounds_left,
                    model_profile_id=model_profile_id,
                    enable_memory=enable_memory,
                    allowed_skill_ids=allowed_skill_ids,
                    knowledge_ids=knowledge_ids,
                    bypass_whitelist=bypass_whitelist,
                    risk=risk,
                ):
                    yield ev
                return

            t0 = time.perf_counter()
            result, source, risk, is_error = await _execute_one(
                db,
                registry,
                name=name,
                args=args,
                mcp_manager=mcp_manager,
                session_id=session_id,
                allowed_skill_ids=allowed_skill_ids,
                knowledge_ids=knowledge_ids,
                bypass_whitelist=bypass_whitelist,
            )
            duration = int((time.perf_counter() - t0) * 1000)
            await _audit(
                db,
                workspace_id=workspace_id,
                session_id=session_id,
                run_id=run_id,
                tool_call_id=tc["id"],
                name=name,
                source=source,
                arguments=args,
                result=result,
                is_error=is_error,
                risk=risk,
                confirm_status="none",
                duration_ms=duration,
            )
            result_str = json.dumps(result, ensure_ascii=False)
            yield {
                "event": "tool_result",
                "data": {
                    "tool_call_id": tc["id"],
                    "name": name,
                    "result": result,
                    "is_error": is_error,
                },
            }
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result_str})
            await _persist_tool_message(db, session_id, tc["id"], result_str)
        else:
            # 本批工具全部执行完，进入下一轮
            continue
        # 循环打断后收尾
        break
    else:
        # max_rounds 耗尽
        pass

    await db.execute(
        """
        INSERT INTO messages(
          id, session_id, role, content, reasoning_content, status, token_estimate, created_at
        )
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            final_message_id,
            session_id,
            "assistant",
            assistant_text,
            assistant_reasoning or None,
            "complete",
            estimate_tokens(assistant_text),
            utc_now(),
        ),
    )
    await db.execute(
        "UPDATE sessions SET message_count=message_count+1, updated_at=? WHERE id=?",
        (utc_now(), session_id),
    )
    await db.execute(
        "UPDATE chat_runs SET status=?, finished_at=?, pending_json=NULL WHERE id=?",
        ("done", utc_now(), run_id),
    )
    await db.commit()
    finish_run(run_id)
    yield {"event": "done", "data": {"message_id": final_message_id}}


async def resume_after_confirm(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    *,
    run_id: str,
    tool_call_id: str,
    approve: bool,
    pending: dict[str, Any],
    mcp_manager: Any | None = None,
) -> AsyncIterator[dict]:
    """确认/拒绝后继续：补 tool 结果 → sibling → 剩余 Tool-Loop。"""
    from app.agent.after_agent import async_extract_memory
    from app.agent.llm_loader import load_llm
    from app.agent.runs import create_run, get_run

    tc = pending["tool_call"]
    if tc["id"] != tool_call_id:
        yield {"event": "error", "data": {"code": "mismatch", "message": "tool_call_id mismatch"}}
        return

    session_id = pending["session_id"]
    workspace_id = pending["workspace_id"]
    args = pending.get("arguments") or {}
    messages: list[dict] = list(pending.get("messages") or [])
    tools: list[dict] = list(pending.get("tools") or [])
    name = tc["function"]["name"]
    allowed = pending.get("allowed_skill_ids")
    allowed_skill_ids = set(allowed) if isinstance(allowed, list) else allowed
    knowledge_ids = pending.get("knowledge_ids")
    bypass_whitelist = bool(pending.get("bypass_whitelist"))
    remaining_siblings: list[dict] = list(pending.get("remaining_siblings") or [])
    rounds_left = int(pending.get("rounds_left") or 0)
    enable_memory = bool(pending.get("enable_memory", True))
    model_profile_id = pending.get("model_profile_id")

    run_state = get_run(run_id)
    if run_state is None:
        run_state = create_run(run_id, session_id)

    if not approve:
        result = {"cancelled": True}
        await _audit(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            name=name,
            source="builtin_fs",
            arguments=args,
            result=result,
            is_error=False,
            risk="high",
            confirm_status="rejected",
            duration_ms=0,
        )
        result_str = json.dumps(result, ensure_ascii=False)
        yield {
            "event": "tool_result",
            "data": {"tool_call_id": tool_call_id, "name": name, "result": result, "is_error": False},
        }
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": result_str})
        await _persist_tool_message(db, session_id, tool_call_id, result_str)
        for sib in remaining_siblings:
            placeholder = {"cancelled": True, "reason": "sibling_of_rejected"}
            ps = json.dumps(placeholder, ensure_ascii=False)
            sib_name = sib["function"]["name"]
            messages.append({"role": "tool", "tool_call_id": sib["id"], "content": ps})
            await _persist_tool_message(db, session_id, sib["id"], ps)
            yield {
                "event": "tool_result",
                "data": {
                    "tool_call_id": sib["id"],
                    "name": sib_name,
                    "result": placeholder,
                    "is_error": False,
                },
            }
        await db.execute(
            "UPDATE chat_runs SET status=?, finished_at=?, pending_json=NULL WHERE id=?",
            ("done", utc_now(), run_id),
        )
        await db.commit()
        finish_run(run_id)
        yield {"event": "done", "data": {"message_id": None, "rejected": True}}
        return

    # 批准：执行高风险工具
    t0 = time.perf_counter()
    result, source, risk, is_error = await _execute_one(
        db,
        registry,
        name=name,
        args=args,
        mcp_manager=mcp_manager,
        session_id=session_id,
        allowed_skill_ids=allowed_skill_ids,
        knowledge_ids=knowledge_ids,
        bypass_whitelist=bypass_whitelist,
    )
    duration = int((time.perf_counter() - t0) * 1000)
    await _audit(
        db,
        workspace_id=workspace_id,
        session_id=session_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        name=name,
        source=source,
        arguments=args,
        result=result,
        is_error=is_error,
        risk=risk,
        confirm_status="approved",
        duration_ms=duration,
    )
    result_str = json.dumps(result, ensure_ascii=False)
    yield {
        "event": "tool_result",
        "data": {"tool_call_id": tool_call_id, "name": name, "result": result, "is_error": is_error},
    }
    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": result_str})
    await _persist_tool_message(db, session_id, tool_call_id, result_str)
    await save_pending_json(db, run_id, None)
    await db.execute(
        "UPDATE chat_runs SET status=? WHERE id=?",
        ("running", run_id),
    )
    await db.commit()

    # 补完同批 sibling（若再遇高风险则再次 pause）
    for sidx, sib in enumerate(remaining_siblings):
        sib_name = sib["function"]["name"]
        sib_args = _parse_args(sib)
        sib_risk = classify_risk(sib_name, sib_args)
        yield {
            "event": "tool_start",
            "data": {"tool_call_id": sib["id"], "name": sib_name, "arguments": sib_args},
        }
        if sib_risk == "high":
            async for ev in _pause_for_confirm(
                db,
                run_id=run_id,
                run_state=run_state,
                session_id=session_id,
                workspace_id=workspace_id,
                tc=sib,
                args=sib_args,
                messages=messages,
                tools=tools,
                remaining_siblings=remaining_siblings[sidx + 1 :],
                rounds_left=rounds_left,
                model_profile_id=model_profile_id,
                enable_memory=enable_memory,
                allowed_skill_ids=allowed_skill_ids,
                knowledge_ids=knowledge_ids,
                bypass_whitelist=bypass_whitelist,
                risk=sib_risk,
            ):
                yield ev
            return
        t0 = time.perf_counter()
        s_result, s_source, s_risk, s_err = await _execute_one(
            db,
            registry,
            name=sib_name,
            args=sib_args,
            mcp_manager=mcp_manager,
            session_id=session_id,
            allowed_skill_ids=allowed_skill_ids,
            knowledge_ids=knowledge_ids,
            bypass_whitelist=bypass_whitelist,
        )
        duration = int((time.perf_counter() - t0) * 1000)
        await _audit(
            db,
            workspace_id=workspace_id,
            session_id=session_id,
            run_id=run_id,
            tool_call_id=sib["id"],
            name=sib_name,
            source=s_source,
            arguments=sib_args,
            result=s_result,
            is_error=s_err,
            risk=s_risk,
            confirm_status="none",
            duration_ms=duration,
        )
        ps = json.dumps(s_result, ensure_ascii=False)
        yield {
            "event": "tool_result",
            "data": {
                "tool_call_id": sib["id"],
                "name": sib_name,
                "result": s_result,
                "is_error": s_err,
            },
        }
        messages.append({"role": "tool", "tool_call_id": sib["id"], "content": ps})
        await _persist_tool_message(db, session_id, sib["id"], ps)

    llm = await load_llm(db, model_profile_id)
    # 继续剩余轮次
    cont_rounds = max(rounds_left, 1) if rounds_left > 0 else MAX_TOOL_ROUNDS
    done_seen = False
    last_ev: dict[str, Any] = {}
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
        knowledge_ids=knowledge_ids,
        bypass_whitelist=bypass_whitelist,
        enable_memory=enable_memory,
        model_profile_id=model_profile_id,
        max_rounds=cont_rounds,
    ):
        last_ev = ev
        yield ev
        if ev.get("event") == "done":
            done_seen = True
    if done_seen and enable_memory and not (last_ev.get("data") or {}).get("rejected"):
        asyncio.create_task(async_extract_memory(session_id, model_profile_id))
