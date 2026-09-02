"""
记忆领域服务。

对齐 deer-flow Memory 边界（自写，不搬 DeerMem 文件）：
- 读：置顶 + FTS（带 workspace）+ 项目内多会话摘要链 + 注入字符预算
- 写：LLM 抽取 preference/fact/session_summary；失败回退规则摘要
- 压缩前可 flush，对话结束后可异步抽取
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import aiosqlite

from app.db.database import utc_now
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

DEFAULT_MAX_INJECTION_CHARS = 1500
WORKSPACE_CHAIN_SUMMARY_LIMIT = 5
WORKSPACE_CHAIN_SESSION_LIMIT = 3

_EXTRACT_PROMPT = """你是记忆抽取器。根据对话摘录，提取值得长期保存的信息。
只输出 JSON 对象，不要 Markdown 代码围栏：
{
  "items": [
    {"type": "preference"|"fact"|"session_summary", "content": "...", "confidence": 0.0-1.0}
  ]
}
规则：
- preference：用户偏好（语气、格式、工具习惯等）
- fact：稳定事实（姓名、项目、路径约定等）
- session_summary：本段对话一句话摘要（最多 1 条）
- 无信息则 items 为空数组
- 每条 content 简短中文，不超过 120 字
"""


async def get_injection(
    db: aiosqlite.Connection,
    query: str,
    workspace_id: str | None = None,
    *,
    session_id: str | None = None,
    max_chars: int = DEFAULT_MAX_INJECTION_CHARS,
    top_k: int = 5,
) -> tuple[str, list[str]]:
    """
    组装注入文本与命中 memory_ids。
    置顶记忆优先；FTS 按 workspace 过滤；
    有 workspace 时再聚合同项目其他会话的 session_summary / summary_text；
    总字符受预算限制。
    """
    memory_ids: list[str] = []
    lines: list[str] = []
    used = 0

    def _try_add(mid: str, content: str, prefix: str = "-") -> bool:
        nonlocal used
        piece = f"{prefix} {content.strip()}"
        if used + len(piece) + 1 > max_chars:
            return False
        lines.append(piece)
        memory_ids.append(mid)
        used += len(piece) + 1
        return True

    # 1) 置顶
    if workspace_id:
        cur = await db.execute(
            """
            SELECT id, content FROM memories
            WHERE pinned=1 AND (workspace_id=? OR workspace_id IS NULL)
            ORDER BY updated_at DESC LIMIT 10
            """,
            (workspace_id,),
        )
    else:
        cur = await db.execute(
            "SELECT id, content FROM memories WHERE pinned=1 ORDER BY updated_at DESC LIMIT 10"
        )
    pinned = await cur.fetchall()
    for r in pinned:
        if not _try_add(r["id"], r["content"], prefix="*"):
            break

    # 2) FTS / LIKE
    q = (query or "").replace('"', "").strip()
    if q and used < max_chars:
        rows: list = []
        try:
            if workspace_id:
                cur = await db.execute(
                    """
                    SELECT m.id, m.content FROM memories_fts f
                    JOIN memories m ON m.rowid = f.rowid
                    WHERE memories_fts MATCH ?
                      AND (m.workspace_id = ? OR m.workspace_id IS NULL)
                    LIMIT ?
                    """,
                    (q, workspace_id, top_k + 5),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT m.id, m.content FROM memories_fts f
                    JOIN memories m ON m.rowid = f.rowid
                    WHERE memories_fts MATCH ?
                    LIMIT ?
                    """,
                    (q, top_k + 5),
                )
            rows = await cur.fetchall()
        except Exception:  # noqa: BLE001
            like = f"%{q[:40]}%"
            if workspace_id:
                cur = await db.execute(
                    """
                    SELECT id, content FROM memories
                    WHERE content LIKE ? AND (workspace_id=? OR workspace_id IS NULL)
                    ORDER BY pinned DESC LIMIT ?
                    """,
                    (like, workspace_id, top_k + 5),
                )
            else:
                cur = await db.execute(
                    "SELECT id, content FROM memories WHERE content LIKE ? ORDER BY pinned DESC LIMIT ?",
                    (like, top_k + 5),
                )
            rows = await cur.fetchall()

        seen = set(memory_ids)
        added = 0
        for r in rows:
            if r["id"] in seen:
                continue
            if not _try_add(r["id"], r["content"]):
                break
            seen.add(r["id"])
            added += 1
            if added >= top_k:
                break

    # 3) 项目内多会话上下文链（仅 workspace）
    if workspace_id and used < max_chars:
        chain_header_added = False
        covered_sessions: set[str] = set()

        # 来源 A：其他会话的 session_summary 记忆
        if session_id:
            cur = await db.execute(
                """
                SELECT m.id, m.content, m.source_session_id, s.title
                FROM memories m
                LEFT JOIN sessions s ON s.id = m.source_session_id
                WHERE m.type = 'session_summary'
                  AND m.workspace_id = ?
                  AND m.source_session_id IS NOT NULL
                  AND m.source_session_id != ?
                ORDER BY m.updated_at DESC
                LIMIT ?
                """,
                (workspace_id, session_id, WORKSPACE_CHAIN_SUMMARY_LIMIT),
            )
        else:
            cur = await db.execute(
                """
                SELECT m.id, m.content, m.source_session_id, s.title
                FROM memories m
                LEFT JOIN sessions s ON s.id = m.source_session_id
                WHERE m.type = 'session_summary'
                  AND m.workspace_id = ?
                  AND m.source_session_id IS NOT NULL
                ORDER BY m.updated_at DESC
                LIMIT ?
                """,
                (workspace_id, WORKSPACE_CHAIN_SUMMARY_LIMIT),
            )
        summary_rows = await cur.fetchall()
        for r in summary_rows:
            src = r["source_session_id"]
            if src:
                covered_sessions.add(src)
            title = (r["title"] or "未命名会话").strip() or "未命名会话"
            content = r["content"] or ""
            piece = f"> [{title}] {content}"
            if not chain_header_added:
                header = "项目内其他会话："
                if used + len(header) + 1 > max_chars:
                    break
                lines.append(header)
                used += len(header) + 1
                chain_header_added = True
            if not _try_add(r["id"], piece, prefix="-"):
                break

        # 来源 B：sessions.summary_text（压缩摘要，补尚未 extract 的会话）
        if used < max_chars:
            if session_id:
                cur = await db.execute(
                    """
                    SELECT id, title, summary_text
                    FROM sessions
                    WHERE workspace_id = ?
                      AND id != ?
                      AND summary_text IS NOT NULL
                      AND TRIM(summary_text) != ''
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (workspace_id, session_id, WORKSPACE_CHAIN_SESSION_LIMIT),
                )
            else:
                cur = await db.execute(
                    """
                    SELECT id, title, summary_text
                    FROM sessions
                    WHERE workspace_id = ?
                      AND summary_text IS NOT NULL
                      AND TRIM(summary_text) != ''
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (workspace_id, WORKSPACE_CHAIN_SESSION_LIMIT),
                )
            session_rows = await cur.fetchall()
            for r in session_rows:
                sid = r["id"]
                if sid in covered_sessions:
                    continue
                title = (r["title"] or "未命名会话").strip() or "未命名会话"
                summary = (r["summary_text"] or "").strip()
                if not summary:
                    continue
                # 压缩摘要截断，避免单条占满预算
                if len(summary) > 200:
                    summary = summary[:200] + "…"
                piece = f"> [{title}] {summary}"
                chain_id = f"session-summary:{sid}"
                if not chain_header_added:
                    header = "项目内其他会话："
                    if used + len(header) + 1 > max_chars:
                        break
                    lines.append(header)
                    used += len(header) + 1
                    chain_header_added = True
                if not _try_add(chain_id, piece, prefix="-"):
                    break
                covered_sessions.add(sid)

    if not lines:
        return "", []
    text = "<memory>\n" + "\n".join(lines) + "\n</memory>"
    return text, memory_ids


async def _insert_memory(
    db: aiosqlite.Connection,
    *,
    workspace_id: str | None,
    mtype: str,
    content: str,
    source_session_id: str | None,
    confidence: float | None = None,
    tags: list[str] | None = None,
) -> str:
    mid = str(uuid.uuid4())
    now = utc_now()
    # confidence 列可能由 migrate 补上
    cols = await _memory_columns(db)
    if "confidence" in cols:
        await db.execute(
            """
            INSERT INTO memories(id, workspace_id, type, content, tags_json, pinned, source_session_id, confidence, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                mid,
                workspace_id,
                mtype,
                content,
                json.dumps(tags or [], ensure_ascii=False),
                0,
                source_session_id,
                confidence,
                now,
                now,
            ),
        )
    else:
        await db.execute(
            """
            INSERT INTO memories(id, workspace_id, type, content, tags_json, pinned, source_session_id, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                mid,
                workspace_id,
                mtype,
                content,
                json.dumps(tags or [], ensure_ascii=False),
                0,
                source_session_id,
                now,
                now,
            ),
        )
    return mid


async def _memory_columns(db: aiosqlite.Connection) -> set[str]:
    cur = await db.execute("PRAGMA table_info(memories)")
    rows = await cur.fetchall()
    return {r["name"] for r in rows}


def _dialogue_excerpt(rows: list) -> str:
    """只保留 user + 最终 assistant（忽略 tool 中间轮）。"""
    parts: list[str] = []
    for r in rows:
        role = r["role"]
        if role == "user":
            parts.append(f"User: {(r['content'] or '')[:800]}")
        elif role == "assistant" and not r["tool_calls_json"]:
            parts.append(f"Assistant: {(r['content'] or '')[:800]}")
    return "\n".join(parts[-12:])


def _rule_fallback_summary(rows: list) -> list[dict[str, Any]]:
    assistants = [r for r in rows if r["role"] == "assistant" and not r["tool_calls_json"]]
    if not assistants:
        return []
    summary = " | ".join((r["content"] or "")[:120] for r in assistants[-3:])
    return [{"type": "session_summary", "content": summary, "confidence": 0.4}]


def _parse_extract_json(text: str) -> list[dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return []
    # 去掉可能的代码围栏
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个 { ... }
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
        else:
            return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        mtype = str(it.get("type") or "fact")
        if mtype not in ("preference", "fact", "session_summary"):
            mtype = "fact"
        content = str(it.get("content") or "").strip()
        if not content:
            continue
        conf = it.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.7
        except (TypeError, ValueError):
            conf_f = 0.7
        out.append({"type": mtype, "content": content[:200], "confidence": conf_f})
    return out


async def extract_from_session(
    db: aiosqlite.Connection,
    session_id: str,
    llm: LLMGateway | None = None,
) -> list[dict]:
    """
    从会话抽取记忆。优先 LLM；失败则规则摘要。
    返回已创建条目列表。
    """
    cur = await db.execute("SELECT workspace_id FROM sessions WHERE id=?", (session_id,))
    sess = await cur.fetchone()
    if not sess:
        return []
    workspace_id = sess["workspace_id"]

    cur = await db.execute(
        """
        SELECT role, content, tool_calls_json FROM messages
        WHERE session_id=? ORDER BY created_at
        """,
        (session_id,),
    )
    rows = await cur.fetchall()
    if not rows:
        return []

    items: list[dict[str, Any]] = []
    if llm is not None:
        excerpt = _dialogue_excerpt(rows)
        if excerpt.strip():
            try:
                resp = await llm.complete(
                    [
                        {"role": "system", "content": _EXTRACT_PROMPT},
                        {"role": "user", "content": excerpt},
                    ]
                )
                items = _parse_extract_json(resp.get("content") or "")
            except Exception as e:  # noqa: BLE001
                logger.warning("memory LLM extract failed: %s", e)
                items = []

    if not items:
        items = _rule_fallback_summary(rows)

    # session_summary 最多一条
    seen_summary = False
    created: list[dict] = []
    for it in items:
        if it["type"] == "session_summary":
            if seen_summary:
                continue
            seen_summary = True
        mid = await _insert_memory(
            db,
            workspace_id=workspace_id,
            mtype=it["type"],
            content=it["content"],
            source_session_id=session_id,
            confidence=it.get("confidence"),
        )
        created.append({"id": mid, "type": it["type"], "content": it["content"]})
    await db.commit()
    return created
