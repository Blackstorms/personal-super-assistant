"""
上下文组装：Slash → DynamicContext → Compress → MemoryInject → SkillCatalog。

静态 system（人设/项目/技能目录）与动态 reminder（记忆/知识/斜杠）分段，
便于 prefix cache（对齐 deer-flow DynamicContext）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from app.agent.compress import compress_history, estimate_tokens
from app.agent.llm_loader import load_llm
from app.db.database import fetch_setting
from app.llm.gateway import LLMGateway
from app.memory import service as memory_service
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_LANGUAGE_HARD_RULE = (
    "【语言硬约束】思考过程（reasoning/thinking）、工具调用说明与最终正文必须全程使用简体中文。"
    "禁止用英文写思考步骤（例如 The user wants… / I will search… / Let me… / Avoid…）。"
    "仅在用户明确要求英文，或代码/专有名词/路径/URL 需保持原文时使用英文。"
)


def _strip_yaml_frontmatter(text: str) -> str:
    """去掉专家/技能文首英文 YAML，避免诱导模型用英文思考。"""
    t = (text or "").lstrip("\ufeff").strip()
    if not t.startswith("---"):
        return text
    rest = t[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end < 0:
        return text
    body = rest[end + 4 :].lstrip("\r\n")
    return body if body else text


def skill_allow_set(resolved_skill_ids: list[str] | None) -> set[str] | None:
    """None=全部技能；[]=禁用；非空=白名单。"""
    if resolved_skill_ids is None:
        return None
    if len(resolved_skill_ids) == 0:
        return set()
    return set(resolved_skill_ids)


async def resolve_session_bindings(
    db: aiosqlite.Connection,
    workspace_id: str | None,
    *,
    expert_id: str | None = None,
    knowledge_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
    mcp_ids: list[str] | None = None,
    model_profile_id: str | None = None,
) -> dict[str, Any]:
    """
    合并请求参数与工作空间/专家默认绑定。

    skill_ids / mcp_ids 语义：
    - 请求显式传入（含空列表）→ 不再继承
    - None → 继承工作空间，再继承专家
    - 最终 None 表示不限制（全部可用）；[] 表示禁用
    """
    project_instructions = None
    resolved_expert = expert_id
    resolved_knowledge = list(knowledge_ids) if knowledge_ids is not None else None
    resolved_skill_ids: list[str] | None = list(skill_ids) if skill_ids is not None else None
    resolved_mcp_ids: list[str] | None = list(mcp_ids) if mcp_ids is not None else None
    resolved_model = model_profile_id

    if workspace_id:
        cur = await db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,))
        ws = await cur.fetchone()
        if ws:
            project_instructions = ws["instructions"]
            if not resolved_expert and "expert_id" in ws.keys():
                resolved_expert = ws["expert_id"]
            if resolved_knowledge is None and "knowledge_ids_json" in ws.keys():
                resolved_knowledge = json.loads(ws["knowledge_ids_json"] or "[]")
            if resolved_skill_ids is None and "skill_ids_json" in ws.keys():
                resolved_skill_ids = json.loads(ws["skill_ids_json"] or "[]")
            if resolved_mcp_ids is None and "mcp_ids_json" in ws.keys():
                resolved_mcp_ids = json.loads(ws["mcp_ids_json"] or "[]")

    if resolved_expert:
        cur = await db.execute(
            """
            SELECT model_profile_id, knowledge_ids_json, skill_ids_json, mcp_ids_json
            FROM experts WHERE id=?
            """,
            (resolved_expert,),
        )
        ex = await cur.fetchone()
        if ex:
            if not resolved_model:
                resolved_model = ex["model_profile_id"]
            if resolved_knowledge is None:
                resolved_knowledge = json.loads(ex["knowledge_ids_json"] or "[]")
            if resolved_skill_ids is None:
                resolved_skill_ids = json.loads(ex["skill_ids_json"] or "[]")
            if resolved_mcp_ids is None:
                resolved_mcp_ids = json.loads(ex["mcp_ids_json"] or "[]")

    return {
        "expert_id": resolved_expert,
        "knowledge_ids": resolved_knowledge,
        "skill_ids": resolved_skill_ids,
        "mcp_ids": resolved_mcp_ids,
        "model_profile_id": resolved_model,
        "project_instructions": project_instructions,
    }


async def build_messages(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    session_id: str,
    user_content: str,
    *,
    enable_skills: bool = True,
    enable_memory: bool = True,
    enable_knowledge: bool = True,
    workspace_id: str | None = None,
    expert_id: str | None = None,
    knowledge_ids: list[str] | None = None,
    project_instructions: str | None = None,
    llm: LLMGateway | None = None,
    slash_reminder: str | None = None,
    content_for_match: str | None = None,
    session_attachments: list[dict] | None = None,
    attachment_mode: bool = False,
    allowed_skill_ids: set[str] | None = None,
    bypass_whitelist: bool = False,
) -> tuple[list[dict], dict]:
    """组装发给模型的 messages，并返回侧车信息（memory/knowledge/compress hints）。"""
    hints: dict[str, Any] = {"memory_ids": [], "knowledge": []}
    match_q = content_for_match if content_for_match is not None else user_content

    system_parts = [
        "你是运行在用户桌面上的个人超级助理。",
        _LANGUAGE_HARD_RULE,
        "回答简洁、可执行。需要时调用工具。",
        "对话默认不写本地文件：攻略、报告、HTML、表格等直接在回复正文中完整输出（优先 Markdown）。"
        "不要调用 fs_write，也不要规划「先写文件再给用户」；除非用户明确要求保存到磁盘且工具面提供了写文件能力。",
        "用户要求创建定时/空闲自动化任务时，调用 schedule_task"
        "（action=create），填写 name、prompt，以及 cron/every/at 之一；不要只口头描述计划。",
        "技能：先用 describe_skill(skill_id) 加载完整指引再执行流程"
        "（用户已用斜杠激活该技能时除外）。",
        "涉及时事、价格、新闻或可能过时的事实时，调用 web_search(query) 并引用标题/链接。"
        "用户本地文档优先 knowledge_search；公开信息优先 web_search。",
        "用户询问现在几点、今天几号、星期几、当前日期或某地当前时间时，必须调用 current_time；"
        "需要其他时区时传入 timezone（如 Asia/Shanghai、纽约、东京）。不要猜测时间，也不要用 web_search 查钟点。",
    ]
    if bypass_whitelist:
        system_parts.append(
            "这是定时/自动化运行：不强制文件白名单。"
            "任务需要时可对任意本地路径使用 fs_list/fs_read。"
            "有绑定知识库时优先 knowledge_search；未绑定则检索全部知识库。"
            "不要要求用户配置白名单根目录。"
        )
    elif attachment_mode and session_attachments:
        system_parts.append(
            "用户在本会话上传了文件。请优先依据下方上传文件内容回答。"
            "全局文件白名单不适用于这些上传；需要更多细节时，"
            "仅对上传附件路径使用 fs_read。"
        )
    elif knowledge_ids:
        system_parts.append(
            "本对话已绑定知识库。优先 knowledge_search(query) 查找文档，"
            "再对返回路径 fs_read 阅读全文。绑定知识库路径可直接 fs_list/fs_read，"
            "无需向用户索要白名单路径。不要要求配置 /、workspace、Documents 等白名单根。"
        )
    else:
        system_parts.append(
            "遵守文件白名单。优先仅在白名单路径下使用 fs_read/fs_list。"
        )

    if not bypass_whitelist:
        from app.fs.whitelist import list_roots

        roots = await list_roots(db)
        ws_roots: list[str] = []
        if workspace_id:
            cur = await db.execute(
                "SELECT root_paths_json FROM workspaces WHERE id=?", (workspace_id,)
            )
            ws = await cur.fetchone()
            if ws and ws["root_paths_json"]:
                try:
                    ws_roots = [
                        p for p in json.loads(ws["root_paths_json"] or "[]") if isinstance(p, str) and p
                    ]
                except json.JSONDecodeError:
                    ws_roots = []
        if roots:
            system_parts.append(
                "当前文件白名单根目录（fs_list/fs_read 的 path 必须落在这些目录下）：\n"
                + "\n".join(f"- {r}" for r in roots)
                + "\n不要对 ''、'.'、相对路径如 'output' 调 fs_list（会失败）；"
                "请使用上述绝对路径，或在其下的子路径。"
            )
        else:
            system_parts.append(
                "当前文件白名单为空：fs_list/fs_read 可能失败。"
                "不要反复尝试 fs_list('')、fs_list('.') 或相对路径。"
                "需要读本地文件时，请用中文提示用户在「设置 → 白名单」添加目录，或用「选择文件夹」作为工作空间。"
                "内容类任务（攻略/报告等）直接在正文输出，不要依赖写文件。"
            )
        if ws_roots:
            system_parts.append(
                "本工作空间绑定的本地根路径：\n" + "\n".join(f"- {r}" for r in ws_roots)
            )

    if expert_id:
        cur = await db.execute("SELECT * FROM experts WHERE id=?", (expert_id,))
        expert = await cur.fetchone()
        if expert and expert["system_prompt"]:
            expert_body = _strip_yaml_frontmatter(expert["system_prompt"])
            system_parts.append(f"专家人设（{expert['name']}）：\n{expert_body}")
            if knowledge_ids is None:
                knowledge_ids = json.loads(expert["knowledge_ids_json"] or "[]") or None

    if project_instructions:
        system_parts.append(f"项目说明：\n{project_instructions}")

    if enable_skills:
        system_parts.append(registry.progressive_prompt(match_q, allowed_skill_ids))

    # 放在 system 末尾：对抗专家/技能文中的英文元数据，强化思考用中文
    system_parts.append(_LANGUAGE_HARD_RULE)

    messages: list[dict] = [{"role": "system", "content": "\n\n".join(system_parts)}]

    if slash_reminder:
        messages.append({"role": "system", "content": slash_reminder})

    if session_attachments:
        attach_lines = []
        for a in session_attachments:
            flag = " (truncated)" if a.get("truncated") else ""
            attach_lines.append(f"### {a['name']}{flag}\n路径: {a['path']}\n{a['content']}")
        messages.append(
            {
                "role": "system",
                "content": "本会话上传文件（优先上下文）：\n\n"
                + "\n\n---\n\n".join(attach_lines),
            }
        )
        hints["attachments"] = [{"name": a["name"], "path": a["path"]} for a in session_attachments]

    if enable_memory:
        mem_text, mem_ids = await memory_service.get_injection(
            db, match_q, workspace_id, session_id=session_id
        )
        if mem_text:
            hints["memory_ids"] = mem_ids
            messages.append({"role": "system", "content": "相关记忆：\n" + mem_text})

    if enable_knowledge and not attachment_mode:
        rows = []
        q = match_q.replace('"', "")
        fts_knowledge_ids = list(knowledge_ids) if knowledge_ids else None
        if bypass_whitelist and not fts_knowledge_ids:
            cur = await db.execute("SELECT id FROM knowledge_bases")
            fts_knowledge_ids = [r["id"] for r in await cur.fetchall()] or None
        try:
            if fts_knowledge_ids:
                placeholders = ",".join("?" * len(fts_knowledge_ids))
                cur = await db.execute(
                    f"""
                    SELECT c.content, d.path, c.id
                    FROM knowledge_chunks_fts f
                    JOIN knowledge_chunks c ON c.rowid = f.rowid
                    JOIN knowledge_documents d ON d.id = c.document_id
                    JOIN knowledge_sources s ON s.id = d.source_id
                    WHERE (s.id IN ({placeholders}) OR s.base_id IN ({placeholders}))
                      AND knowledge_chunks_fts MATCH ?
                    LIMIT 6
                    """,
                    (*fts_knowledge_ids, *fts_knowledge_ids, q),
                )
                rows = await cur.fetchall()
            elif workspace_id:
                cur = await db.execute(
                    """
                    SELECT c.content, d.path, c.id
                    FROM knowledge_chunks_fts f
                    JOIN knowledge_chunks c ON c.rowid = f.rowid
                    JOIN knowledge_documents d ON d.id = c.document_id
                    JOIN knowledge_sources s ON s.id = d.source_id
                    WHERE s.workspace_id = ? AND knowledge_chunks_fts MATCH ?
                    LIMIT 4
                    """,
                    (workspace_id, q),
                )
                rows = await cur.fetchall()
        except Exception:  # noqa: BLE001
            rows = []
        root_scope = fts_knowledge_ids if bypass_whitelist else knowledge_ids
        if root_scope:
            from app.fs import knowledge_access as ka

            roots = await ka.list_knowledge_roots(db, root_scope)
            if roots:
                root_lines = [f"- {r['name']}: {r['path']}" for r in roots]
                label = (
                    "Available knowledge bases (whitelist not enforced this run):\n"
                    if bypass_whitelist
                    else "Bound knowledge bases (fs_list/fs_read allowed on these roots; "
                    "no user whitelist needed):\n"
                )
                messages.append({"role": "system", "content": label + "\n".join(root_lines)})
                hints["knowledge_roots"] = roots
        if rows:
            kn_lines = []
            for r in rows:
                hints["knowledge"].append({"path": r["path"], "snippet": r["content"][:200]})
                kn_lines.append(f"[{r['path']}]\n{r['content'][:500]}")
            messages.append(
                {"role": "system", "content": "知识库命中：\n" + "\n---\n".join(kn_lines)}
            )

    compress_cfg = await fetch_setting(db, "compress") or {
        "max_messages": 40,
        "max_tokens": 32000,
        "keep_messages": 16,
        "llm_summary": True,
    }
    cur = await db.execute(
        "SELECT id, role, content, tool_calls_json, tool_call_id FROM messages "
        "WHERE session_id=? ORDER BY created_at",
        (session_id,),
    )
    history = await cur.fetchall()
    hist_msgs: list[dict] = []
    message_ids: list[str] = []
    for h in history:
        message_ids.append(h["id"])
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

    while hist_msgs and hist_msgs[-1].get("role") == "user":
        hist_msgs.pop()
        if message_ids:
            message_ids.pop()

    total_tokens = sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in hist_msgs)
    max_msg = int(compress_cfg.get("max_messages", 40))
    max_tok = int(compress_cfg.get("max_tokens", 32000))
    if enable_memory and (len(hist_msgs) > max_msg or total_tokens > max_tok):
        try:
            flush_llm = llm or await load_llm(db)
            await memory_service.extract_from_session(db, session_id, llm=flush_llm)
        except Exception as e:  # noqa: BLE001
            logger.warning("pre-compress memory flush failed: %s", e)

    projected, comp_hints = await compress_history(
        db,
        session_id,
        hist_msgs,
        compress_cfg=compress_cfg,
        llm=llm,
        message_ids=message_ids,
    )
    hints.update(comp_hints)

    messages.extend(projected)
    messages.append({"role": "user", "content": user_content})
    return messages, hints
