"""
长上下文压缩。

对齐 deer-flow summarization 边界（自写）：
- 超消息数 / token 双阈值时触发
- LLM 摘要写入 sessions.summary_text；失败回退占位句
- 截断点保证 assistant(tool_calls) 与 tool 成对完整
- 摘要以独立 system reminder 投影，不堆进普通 transcript
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from app.db.database import utc_now
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 40
DEFAULT_MAX_TOKENS = 32_000
DEFAULT_KEEP_MESSAGES = 16
# 给摘要 system reminder 预留，避免 keep 窗口贴满后再被摘要顶破
_SUMMARY_RESERVE_TOKENS = 500

_SUMMARY_PROMPT = """将以下较早的对话压缩为简洁中文摘要，保留：用户目标、关键结论、未完成事项、重要路径/约定。
不要编造。不超过 600 字。只输出摘要正文。"""


def estimate_tokens(text: str) -> int:
    """真实 token 计数（tiktoken）；不可用时回退 2 字符 ≈ 1 token。"""
    if not text:
        return 1
    try:
        import tiktoken

        try:
            enc = tiktoken.get_encoding("cl100k_base")
        except Exception:  # noqa: BLE001
            enc = tiktoken.get_encoding("o200k_base")
        return max(1, len(enc.encode(text)))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 2)


def _msg_tokens(m: dict) -> int:
    return estimate_tokens(json.dumps(m, ensure_ascii=False))


_SKILL_TOOL_NAMES = frozenset(
    {
        "describe_skill",
        "run_skill",
        "skills_list",
        "skill_view",
        "skill_manage",
    }
)

_BREAKDOWN_KEYS = ("system_prompt", "tools", "conversation", "mcp", "skills")


def _bucket_for_tool_name(name: str) -> str:
    n = name or ""
    if n.startswith("mcp__"):
        return "mcp"
    if n in _SKILL_TOOL_NAMES:
        return "skills"
    return "tools"


def categorize_context_tokens(msgs: list[dict]) -> dict[str, int]:
    """把投影消息拆成 UI 分段：System Prompt / Tools / Conversation / MCP / Skills。"""
    buckets = {k: 0 for k in _BREAKDOWN_KEYS}
    call_cat: dict[str, str] = {}
    for m in msgs:
        for tc in m.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            tid = str(tc.get("id") or "")
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str((fn or {}).get("name") or "")
            if tid:
                call_cat[tid] = _bucket_for_tool_name(name)

    for m in msgs:
        tok = _msg_tokens(m)
        role = m.get("role")
        content = str(m.get("content") or "")
        if role == "system" or content.startswith("[Conversation summary]"):
            buckets["system_prompt"] += tok
        elif role == "tool":
            buckets[call_cat.get(str(m.get("tool_call_id") or ""), "tools")] += tok
        elif role == "assistant" and m.get("tool_calls"):
            names: list[str] = []
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                names.append(str((fn or {}).get("name") or ""))
            cats = {_bucket_for_tool_name(n) for n in names} or {"tools"}
            if len(cats) == 1:
                buckets[next(iter(cats))] += tok
            else:
                buckets["tools"] += tok
        else:
            buckets["conversation"] += tok
    return buckets


def find_keep_start(hist_msgs: list[dict], keep: int) -> int:
    """
    计算保留窗口起点，并向前扩展以保证 tool 成对。
    若起点落在 tool 消息上，或紧跟在带 tool_calls 的 assistant 之后被切开，则左移。
    """
    if keep <= 0 or keep >= len(hist_msgs):
        return 0
    start = len(hist_msgs) - keep
    # 若 start 处是 tool，向前找到对应 assistant(tool_calls)
    while start > 0 and hist_msgs[start].get("role") == "tool":
        start -= 1
    # 若 start-1 是带 tool_calls 的 assistant，而 start 起是其 tool 结果，应包含该 assistant
    if start > 0:
        prev = hist_msgs[start - 1]
        if prev.get("role") == "assistant" and prev.get("tool_calls"):
            # 当前窗口从 tool 结果开始 → 把 assistant 一并纳入
            if hist_msgs[start].get("role") == "tool":
                start -= 1
    # 若 start 是 assistant(tool_calls)，确保其后 tool 都在窗口内（keep 可能不够时仍尽量成对）
    if start < len(hist_msgs):
        cur = hist_msgs[start]
        if cur.get("role") == "assistant" and cur.get("tool_calls"):
            # 窗口已含该 assistant，OK
            pass
    return max(0, start)


def _msg_copy(m: dict) -> dict:
    return json.loads(json.dumps(m, ensure_ascii=False))


def _advance_start(hist_msgs: list[dict], start: int) -> int:
    """窗口仍超预算时，越过最旧一条（assistant+tools 成对跳过）。"""
    n = len(hist_msgs)
    if start >= n - 1:
        return n - 1
    nxt = start + 1
    cur = hist_msgs[start]
    if cur.get("role") == "assistant" and cur.get("tool_calls"):
        while nxt < n and hist_msgs[nxt].get("role") == "tool":
            nxt += 1
    return min(nxt, n - 1)


def _trim_message_to_budget(m: dict, budget: int) -> dict:
    """截断单条消息，尽量让序列化 token 不超过 budget。"""
    out = _msg_copy(m)
    if budget <= 0:
        out["content"] = ""
        return out
    if _msg_tokens(out) <= budget:
        return out
    content = str(out.get("content") or "")
    lo, hi = 0, len(content)
    best = dict(out)
    best["content"] = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        trial = dict(out)
        cut = content[:mid]
        trial["content"] = (cut + "\n[truncated]") if mid < len(content) else cut
        if _msg_tokens(trial) <= budget:
            best = trial
            lo = mid + 1
        else:
            hi = mid - 1
    out = best
    if _msg_tokens(out) <= budget:
        return out
    if out.get("tool_calls"):
        slim = []
        for tc in out["tool_calls"]:
            if not isinstance(tc, dict):
                continue
            fn = dict(tc.get("function") or {})
            fn["arguments"] = "{}"
            slim.append({**tc, "function": fn})
        out["tool_calls"] = slim
        if _msg_tokens(out) <= budget:
            return out
    out["content"] = ""
    return out


def fit_keep_window(
    hist_msgs: list[dict],
    keep: int,
    max_tok: int,
) -> tuple[int, list[dict]]:
    """
    选出不超过 max_tok 的保留窗口。
    先按 keep 收缩条数（保持 tool 成对），仍超则丢掉最旧消息、截断超长工具结果。
    """
    if not hist_msgs:
        return 0, []
    n = len(hist_msgs)
    keep = max(1, min(int(keep) or 1, n))
    start = find_keep_start(hist_msgs, keep)
    recent = hist_msgs[start:]

    while keep > 1 and sum(_msg_tokens(m) for m in recent) > max_tok:
        prev_start = start
        keep -= 1
        start = find_keep_start(hist_msgs, keep)
        if start <= prev_start:
            start = _advance_start(hist_msgs, prev_start)
        recent = hist_msgs[start:]
        if start >= n - 1:
            recent = hist_msgs[-1:]
            start = n - 1
            break

    if sum(_msg_tokens(m) for m in recent) <= max_tok:
        return start, list(recent)

    fitted: list[dict] = [_msg_copy(m) for m in recent]
    while len(fitted) > 1 and sum(_msg_tokens(m) for m in fitted) > max_tok:
        head = fitted[0]
        fitted = fitted[1:]
        if head.get("role") == "assistant" and head.get("tool_calls"):
            while fitted and fitted[0].get("role") == "tool":
                fitted = fitted[1:]
        if not fitted:
            fitted = [_msg_copy(hist_msgs[-1])]
            break

    if sum(_msg_tokens(m) for m in fitted) > max_tok:
        remain = max_tok
        trimmed: list[dict] = []
        for i, m in enumerate(fitted):
            rest = len(fitted) - i - 1
            reserved = rest * 32
            budget = remain if rest == 0 else max(32, remain - reserved)
            tm = _trim_message_to_budget(m, budget)
            trimmed.append(tm)
            remain = max(0, remain - _msg_tokens(tm))
        fitted = trimmed

    return n - len(fitted), fitted


def project_compressed_history(
    hist_msgs: list[dict],
    *,
    keep: int,
    max_tok: int,
    summary: str = "",
) -> list[dict]:
    """只读投影：摘要 + 适配后的 keep 窗口，总量尽量不超过 max_tok。"""
    keep_budget = max(64, int(max_tok) - _SUMMARY_RESERVE_TOKENS) if summary else max_tok
    _start, recent = fit_keep_window(hist_msgs, keep, keep_budget)
    projected: list[dict] = []
    if summary:
        projected.append({"role": "system", "content": f"[Conversation summary]\n{summary}"})
    projected.extend(recent)
    total = sum(_msg_tokens(m) for m in projected)
    if total <= max_tok or not projected:
        return projected
    # 摘要把预算顶破：再按剩余额度裁剪 keep
    summary_msgs = [projected[0]] if summary else []
    summary_tok = sum(_msg_tokens(m) for m in summary_msgs)
    remain = max(64, max_tok - summary_tok)
    _s, recent = fit_keep_window(recent, len(recent), remain)
    return summary_msgs + recent


async def _load_session_summary(db: aiosqlite.Connection, session_id: str) -> str:
    cur = await db.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
    row = await cur.fetchone()
    if not row:
        return ""
    keys = row.keys()
    if "summary_text" in keys and row["summary_text"]:
        return row["summary_text"] or ""
    return ""


async def _save_session_summary(
    db: aiosqlite.Connection,
    session_id: str,
    summary: str,
    summary_upto_id: str | None,
) -> None:
    cur = await db.execute("PRAGMA table_info(sessions)")
    cols = {r["name"] for r in await cur.fetchall()}
    if "summary_text" not in cols:
        return
    await db.execute(
        "UPDATE sessions SET summary_text=?, summary_upto_id=?, updated_at=? WHERE id=?",
        (summary, summary_upto_id, utc_now(), session_id),
    )
    await db.commit()


async def llm_summarize(llm: LLMGateway, older_msgs: list[dict], prior_summary: str) -> str:
    """调用 LLM 生成摘要；失败抛异常由调用方回退。"""
    parts: list[str] = []
    if prior_summary:
        parts.append(f"Previous summary:\n{prior_summary}")
    for m in older_msgs:
        role = m.get("role")
        if role == "user":
            parts.append(f"User: {(m.get('content') or '')[:1000]}")
        elif role == "assistant" and not m.get("tool_calls"):
            parts.append(f"Assistant: {(m.get('content') or '')[:1000]}")
        elif role == "assistant" and m.get("tool_calls"):
            names = []
            for tc in m.get("tool_calls") or []:
                names.append((tc.get("function") or {}).get("name") or "?")
            parts.append(f"Assistant called tools: {', '.join(names)}")
    blob = "\n".join(parts)[:12000]
    resp = await llm.complete(
        [
            {"role": "system", "content": _SUMMARY_PROMPT},
            {"role": "user", "content": blob},
        ]
    )
    return (resp.get("content") or "").strip()


async def compress_history(
    db: aiosqlite.Connection,
    session_id: str,
    hist_msgs: list[dict],
    *,
    compress_cfg: dict,
    llm: LLMGateway | None = None,
    message_ids: list[str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """
    对历史消息做双阈值压缩。

    返回 (投影后的 hist 列表用于拼进 messages, hints)。
    投影：可选 [summary system reminder] + 适配后的 keep 窗口（总量不超过 max_tokens）。
    """
    max_msg = int(compress_cfg.get("max_messages", DEFAULT_MAX_MESSAGES))
    max_tok = int(compress_cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
    keep = int(compress_cfg.get("keep_messages", DEFAULT_KEEP_MESSAGES))
    use_llm = bool(compress_cfg.get("llm_summary", True))

    total_tokens = sum(_msg_tokens(m) for m in hist_msgs)
    prior = await _load_session_summary(db, session_id)
    hints: dict[str, Any] = {
        "compressed": False,
        "before_tokens": total_tokens,
        "after_tokens": total_tokens,
        "used_tokens": total_tokens,
        "limit_tokens": max_tok,
        "message_count": len(hist_msgs),
        "max_messages": max_msg,
        "keep_messages": keep,
        "has_summary": bool(prior),
        "breakdown": categorize_context_tokens(hist_msgs),
    }

    need = len(hist_msgs) > max_msg or total_tokens > max_tok
    if not need:
        # 未超阈值：原样返回；summary_text 留在 DB 供下次超限时合并
        return hist_msgs, hints

    start, _recent = fit_keep_window(
        hist_msgs, keep, max(64, max_tok - _SUMMARY_RESERVE_TOKENS)
    )
    older = hist_msgs[:start]

    summary = prior
    if older:
        if use_llm and llm is not None:
            try:
                summary = await llm_summarize(llm, older, prior)
            except Exception as e:  # noqa: BLE001
                logger.warning("LLM compress failed, fallback placeholder: %s", e)
                summary = (
                    prior
                    or f"[Earlier conversation summarized: {len(older)} messages omitted]"
                )
                if prior:
                    summary = prior + f"\n(Additional {len(older)} messages omitted.)"
        else:
            summary = (
                prior
                or f"[Earlier conversation summarized: {len(older)} messages omitted]"
            )
            if prior and older:
                summary = prior + f"\n(Additional {len(older)} messages omitted.)"

        upto_id = None
        if message_ids and start > 0 and start - 1 < len(message_ids):
            upto_id = message_ids[start - 1]
        if summary:
            await _save_session_summary(db, session_id, summary, upto_id)

    projected = project_compressed_history(
        hist_msgs, keep=keep, max_tok=max_tok, summary=summary or ""
    )
    # 若 fit 把 start 推得更靠后，以投影中非摘要条数为准
    kept = [m for m in projected if not str(m.get("content") or "").startswith("[Conversation summary]")]
    after = sum(_msg_tokens(m) for m in projected)
    hints["compressed"] = True
    hints["after_tokens"] = after
    hints["used_tokens"] = after
    hints["has_summary"] = bool(summary)
    hints["kept_messages"] = len(kept)
    hints["summarized_messages"] = max(0, len(hist_msgs) - len(kept))
    hints["breakdown"] = categorize_context_tokens(projected)
    return projected, hints


async def estimate_session_context(
    db: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any]:
    """只读估算会话上下文用量（供 UI；不做 LLM 摘要）。"""
    from app.db.database import fetch_setting

    compress_cfg = await fetch_setting(db, "compress") or {}
    max_msg = int(compress_cfg.get("max_messages", DEFAULT_MAX_MESSAGES))
    max_tok = int(compress_cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
    keep = int(compress_cfg.get("keep_messages", DEFAULT_KEEP_MESSAGES))

    cur = await db.execute(
        "SELECT role, content, tool_calls_json, tool_call_id FROM messages "
        "WHERE session_id=? ORDER BY created_at",
        (session_id,),
    )
    rows = await cur.fetchall()
    hist_msgs: list[dict] = []
    for h in rows:
        if h["role"] == "tool":
            hist_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": h["tool_call_id"] or "",
                    "content": h["content"] or "",
                }
            )
        elif h["role"] == "assistant" and h["tool_calls_json"]:
            hist_msgs.append(
                {
                    "role": "assistant",
                    "content": h["content"] or "",
                    "tool_calls": json.loads(h["tool_calls_json"]),
                }
            )
        else:
            hist_msgs.append({"role": h["role"], "content": h["content"] or ""})

    raw_tokens = sum(_msg_tokens(m) for m in hist_msgs)
    summary = await _load_session_summary(db, session_id)
    would_compress = len(hist_msgs) > max_msg or raw_tokens > max_tok
    used = raw_tokens
    projected_for_usage = hist_msgs
    if would_compress and hist_msgs:
        projected_for_usage = project_compressed_history(
            hist_msgs, keep=keep, max_tok=max_tok, summary=summary or ""
        )
        used = sum(_msg_tokens(m) for m in projected_for_usage)
    elif summary:
        # 有历史摘要但尚未再次超阈值：用量仍按原文（与 compress_history 未触发时一致）
        used = raw_tokens

    pct = round(min(100.0, (used / max_tok) * 100), 1) if max_tok > 0 else 0.0
    return {
        "used_tokens": used,
        "raw_tokens": raw_tokens,
        "limit_tokens": max_tok,
        "percent": pct,
        "message_count": len(hist_msgs),
        "max_messages": max_msg,
        "keep_messages": keep,
        "compressed": bool(summary),
        "has_summary": bool(summary),
        "near_limit": pct >= 80 or len(hist_msgs) >= max_msg,
        "would_compress": would_compress,
        "breakdown": categorize_context_tokens(projected_for_usage),
    }
