"""
统一工具面构建与分发（Hermes 一等公民 + 内置降级）。

热路径约定（禁止双写）：
- Hermes on：Skills / MCP / toolsets **只**经 hermes_bridge；
  自研 SkillRegistry / mcp.manager.openai_tools 不并入对话工具表。
- Hermes off：才用 SkillRegistry + 官方 MCP SDK 缓存降级。
- PSA 始终独占：fs_* / knowledge_search / web_search / current_time / schedule_task / 确认闸 / SSE。
- 新 Skills/MCP 能力优先接到 Hermes 侧，禁止在 registry 与 bridge 各实现一份。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import aiosqlite

from app.agent.risk import classify_risk, classify_source
from app.agent.web_search import WEB_SEARCH_TOOL, handle_web_search
from app.agent.current_time import CURRENT_TIME_TOOL, handle_current_time
from app.agent.feishu_tools import (
    FEISHU_TOOL_NAMES,
    feishu_tools_for_surface,
    handle_feishu_tool,
)
from app.fs import whitelist as fs
from app.hermes_bridge.dispatch import dispatch_hermes_tool
from app.hermes_bridge.lifecycle import hermes_available
from app.hermes_bridge.tool_surface import (
    filter_by_mcp_ids,
    filter_skill_tools,
    get_openai_tools,
)
from app.skills.registry import SkillRegistry
from app.scheduler.tool import SCHEDULE_TASK_TOOL, handle_schedule_task

logger = logging.getLogger(__name__)

# Hermes 文件类工具与 PSA fs_* 冲突，默认从工具面剔除
HERMES_FILE_TOOLS = frozenset(
    {
        "read_file",
        "write_file",
        "search_files",
        "patch",
        "apply_patch",
        "edit_file",
        "create_file",
        "delete_file",
        "ls",
        "list_dir",
    }
)

PSA_BUILTIN_NAMES = frozenset(
    {
        "fs_list",
        "fs_read",
        "fs_write",
        "knowledge_search",
        "web_search",
        "current_time",
        "schedule_task",
        "feishu_send_message",
        "feishu_lookup_user",
        "feishu_create_task",
    }
)

BUILTIN_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "fs_list",
            "description": "列出白名单或已绑定知识库根目录下的文件夹内容。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_read",
            "description": "读取白名单或已绑定知识库路径下的文本文件。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fs_write",
            "description": (
                "在白名单路径下写入文本文件。"
                "需要保存文件时直接调用本工具；应用界面会在真正写入前弹出确认。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目标文件路径"},
                    "content": {"type": "string", "description": "文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": (
                "在本对话绑定的知识库中检索。"
                "优先使用本工具，不要猜测文件系统路径。"
                "返回路径与摘要后，再用 fs_read 读取全文。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词"},
                    "top_k": {"type": "integer", "description": "最多返回条数（默认 8）"},
                },
                "required": ["query"],
            },
        },
    },
    WEB_SEARCH_TOOL,
    CURRENT_TIME_TOOL,
    SCHEDULE_TASK_TOOL,
]


def _tool_name(t: dict) -> str:
    return ((t.get("function") or {}).get("name") or "")


def strip_hermes_file_tools(tools: list[dict]) -> list[dict]:
    return [t for t in tools if _tool_name(t) not in HERMES_FILE_TOOLS]


async def _enabled_toolsets(db: aiosqlite.Connection) -> list[str] | None:
    try:
        cur = await db.execute("SELECT toolset, enabled FROM hermes_toolset_settings")
        rows = await cur.fetchall()
        if not rows:
            return None
        return [r["toolset"] for r in rows if r["enabled"]]
    except Exception:  # noqa: BLE001
        return None


async def _fallback_surface(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    *,
    enable_skills: bool,
    enable_mcp: bool,
    allowed_skill_ids: set[str] | None,
    mcp_ids: list[str] | None,
    mcp_manager: Any | None,
) -> list[dict]:
    """Hermes 不可用或 tool_surface 失败时的只读降级。"""
    tools: list[dict] = []
    if enable_skills and allowed_skill_ids != set():
        tools.extend(registry.to_openai_tools())
    if enable_mcp and mcp_manager is not None:
        mcp_tools = await mcp_manager.openai_tools(db, prefer_hermes=False)
        if mcp_ids is not None:
            mcp_tools = mcp_manager.filter_openai_tools(mcp_tools, mcp_ids)
        tools.extend(mcp_tools)
    return tools


async def build_tool_surface(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    *,
    enable_skills: bool = True,
    enable_mcp: bool = True,
    enable_fs_write: bool = False,
    allowed_skill_ids: set[str] | None = None,
    mcp_ids: list[str] | None = None,
    mcp_manager: Any | None = None,
    slash_permissions: list[str] | None = None,
) -> list[dict]:
    """
    单一工具面入口。
    始终包含 PSA BUILTIN_TOOLS（对话默认不含 fs_write，避免卡在写文件确认）；
    Hermes on 时追加 bridge tools（剔除文件类）；
    off 时用 registry + MCP 缓存。Hermes on 时绝不把 mcp_manager.openai_tools 并入热路径。
    """
    tools: list[dict] = [
        t for t in BUILTIN_TOOLS if enable_fs_write or _tool_name(t) != "fs_write"
    ]
    tools.extend(
        await feishu_tools_for_surface(db, enable_mcp=enable_mcp, mcp_ids=mcp_ids)
    )

    if hermes_available():
        enabled = await _enabled_toolsets(db)
        ts = ["skills"] if enable_skills else []
        if enabled is not None:
            ts = [t for t in enabled if t] or (["skills"] if enable_skills else [])
            if enable_skills and "skills" not in ts:
                ts.append("skills")
        try:
            hermes_tools = await get_openai_tools(
                enabled_toolsets=ts if ts else None,
                include_skills=enable_skills and allowed_skill_ids != set(),
                include_mcp=enable_mcp,
            )
            hermes_tools = strip_hermes_file_tools(hermes_tools)
            if enable_skills and allowed_skill_ids is not None:
                hermes_tools = filter_skill_tools(hermes_tools, allowed_skill_ids)
            if enable_mcp and mcp_ids is not None and mcp_manager is not None:
                hermes_tools = mcp_manager.filter_openai_tools(hermes_tools, mcp_ids)
            elif enable_mcp and mcp_ids is not None:
                hermes_tools = filter_by_mcp_ids(hermes_tools, mcp_ids)
            elif not enable_mcp:
                hermes_tools = [t for t in hermes_tools if not _tool_name(t).startswith("mcp__")]
            tools.extend(hermes_tools)
            # Hermes skills 工具偶发缺依赖时，保留 PSA describe_skill / run_skill 作为可靠回退
            if enable_skills and allowed_skill_ids != set():
                tools.extend(registry.to_openai_tools())
        except Exception as e:  # noqa: BLE001
            logger.warning("hermes tool surface failed, falling back: %s", e)
            tools.extend(
                await _fallback_surface(
                    db,
                    registry,
                    enable_skills=enable_skills,
                    enable_mcp=enable_mcp,
                    allowed_skill_ids=allowed_skill_ids,
                    mcp_ids=mcp_ids,
                    mcp_manager=mcp_manager,
                )
            )
    else:
        tools.extend(
            await _fallback_surface(
                db,
                registry,
                enable_skills=enable_skills,
                enable_mcp=enable_mcp,
                allowed_skill_ids=allowed_skill_ids,
                mcp_ids=mcp_ids,
                mcp_manager=mcp_manager,
            )
        )

    if slash_permissions:
        tools = registry.filter_tools_for_permissions(tools, slash_permissions)

    seen: set[str] = set()
    deduped: list[dict] = []
    for t in tools:
        n = _tool_name(t)
        if not n or n in seen:
            continue
        seen.add(n)
        deduped.append(t)
    return deduped


async def dispatch(
    db: aiosqlite.Connection,
    registry: SkillRegistry,
    name: str,
    arguments: dict,
    mcp_manager: Any | None = None,
    session_id: str | None = None,
    allowed_skill_ids: set[str] | None = None,
    knowledge_ids: list[str] | None = None,
    bypass_whitelist: bool = False,
) -> tuple[Any, str, str]:
    """
    执行工具，返回 (result, source, risk)。
    Hermes on：非 PSA 内置一律走 Bridge；fs_* 始终走白名单。
    Hermes off：describe_skill/run_skill + mcp_manager。
    """
    if name == "fs_list":
        return (
            await fs.list_dir_for_session(
                db,
                arguments["path"],
                session_id,
                knowledge_ids=knowledge_ids,
                bypass_whitelist=bypass_whitelist,
            ),
            "builtin_fs",
            "low",
        )
    if name == "fs_read":
        return (
            await fs.read_text_for_session(
                db,
                arguments["path"],
                session_id,
                knowledge_ids=knowledge_ids,
                bypass_whitelist=bypass_whitelist,
            ),
            "builtin_fs",
            "low",
        )
    if name == "fs_write":
        return (
            await fs.write_text(
                db,
                arguments["path"],
                arguments.get("content", ""),
                bypass_whitelist=bypass_whitelist,
            ),
            "builtin_fs",
            "high",
        )
    if name == "knowledge_search":
        from app.fs import knowledge_access as ka

        scope_ids = knowledge_ids
        if not scope_ids and bypass_whitelist:
            cur = await db.execute("SELECT id FROM knowledge_bases")
            scope_ids = [r["id"] for r in await cur.fetchall()]
        if not scope_ids:
            return {
                "error": "no knowledge base bound to this chat; ask user to attach one",
                "items": [],
            }, "builtin_knowledge", "low"
        items = await ka.search_knowledge(
            db,
            query=str(arguments.get("query") or ""),
            knowledge_ids=scope_ids,
            top_k=int(arguments.get("top_k") or 8),
        )
        return {"items": items, "count": len(items)}, "builtin_knowledge", "low"
    if name == "web_search":
        result = await handle_web_search(arguments or {})
        return result, "builtin_web", "low"
    if name == "current_time":
        result = handle_current_time(arguments or {})
        return result, "builtin_time", "low"
    if name == "schedule_task":
        result = await handle_schedule_task(
            db, arguments or {}, registry=registry, mcp_manager=mcp_manager
        )
        return result, "builtin_schedule", "low"
    if name in FEISHU_TOOL_NAMES:
        result = await handle_feishu_tool(db, name, arguments or {})
        return result, "builtin_feishu", "low"

    # PSA 技能工具优先：不依赖 Hermes plugin 子系统
    if name == "describe_skill":
        skill_id = arguments.get("skill_id", "") or arguments.get("name", "")
        return registry.describe(skill_id, allowed_skill_ids), "skill", "low"
    if name == "run_skill":
        skill_id = arguments.get("skill_id", "") or arguments.get("name", "")
        if allowed_skill_ids is not None and skill_id not in allowed_skill_ids:
            return {"error": f"skill not allowed in this session: {skill_id}"}, "skill", "low"
        skill = registry.get(skill_id)
        if not skill or not skill.enabled:
            raise ValueError(f"skill not found: {skill_id}")
        result = {
            "skill": skill.name,
            "guidance": skill.body[:2000],
            "input": arguments.get("input", ""),
            "note": "Skill context loaded; apply the guidance to the input.",
        }
        return result, "skill", "low"

    if name in HERMES_FILE_TOOLS:
        path_arg = (
            arguments.get("path")
            or arguments.get("file_path")
            or arguments.get("target")
            or ""
        )
        if name in {"read_file", "search_files"} and path_arg:
            return (
                await fs.read_text_for_session(
                    db,
                    str(path_arg),
                    session_id,
                    knowledge_ids=knowledge_ids,
                    bypass_whitelist=bypass_whitelist,
                ),
                "builtin_fs",
                "low",
            )
        if name in {"write_file", "patch", "apply_patch", "edit_file", "create_file"} and path_arg:
            content = (
                arguments.get("content")
                or arguments.get("new_content")
                or arguments.get("patch")
                or ""
            )
            return (
                await fs.write_text(
                    db, str(path_arg), str(content), bypass_whitelist=bypass_whitelist
                ),
                "builtin_fs",
                "high",
            )
        if name in {"ls", "list_dir"} and path_arg:
            return (
                await fs.list_dir_for_session(
                    db,
                    str(path_arg),
                    session_id,
                    knowledge_ids=knowledge_ids,
                    bypass_whitelist=bypass_whitelist,
                ),
                "builtin_fs",
                "low",
            )
        return {"error": f"unsupported or missing path for {name}"}, "builtin_fs", "low"

    # Hermes 技能工具在嵌入环境下常缺依赖；统一走 PSA 技能注册表
    if name == "skills_list":
        items = [
            {"id": s.id, "name": s.name, "description": (s.description or "")[:200]}
            for s in registry.list_enabled(allowed_skill_ids)
        ]
        return {"success": True, "skills": items, "count": len(items)}, "skill", "low"
    if name == "skill_view":
        sid = str(arguments.get("name") or arguments.get("skill_id") or "")
        return registry.describe(sid, allowed_skill_ids), "skill", "low"
    if name == "skill_manage":
        return {
            "error": "skill_manage is not supported in Personal Super Assistant; edit skills in the plugin market",
        }, "skill", "low"

    if hermes_available() and name not in PSA_BUILTIN_NAMES:
        if name.startswith("web_"):
            if not (
                os.environ.get("FIRECRAWL_API_KEY")
                or os.environ.get("NOUS_API_KEY")
                or os.environ.get("OPENROUTER_API_KEY")
            ):
                return {
                    "error": "web tools gated: set FIRECRAWL_API_KEY or NOUS_API_KEY",
                    "tool": name,
                }, "hermes", "low"
        result = await dispatch_hermes_tool(name, arguments or {}, session_id=session_id)
        return result, classify_source(name), classify_risk(name, arguments)

    if name.startswith("mcp__") and mcp_manager is not None:
        from app.hermes_bridge.config_mapper import hermes_server_key

        parts = name.split("__", 2)
        if len(parts) != 3:
            raise ValueError("invalid mcp tool name")
        _, sid8, tool_name = parts
        full_id = mcp_manager.resolve_server_id(sid8)
        if len(full_id) <= 8 or full_id == sid8:
            cur = await db.execute("SELECT id, name FROM mcp_servers")
            for r in await cur.fetchall():
                if hermes_server_key(dict(r)) == sid8 or r["id"].replace("-", "")[:8] == sid8:
                    full_id = r["id"]
                    break
        result = await mcp_manager.call_tool(
            db, full_id, tool_name, arguments, prefer_hermes=False
        )
        return result, "mcp", "low"

    raise ValueError(f"unknown tool: {name}")


# 兼容旧名
execute_tool = dispatch
