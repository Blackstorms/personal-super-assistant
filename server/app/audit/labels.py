"""审计舱中文标签：为工具调用记录补充易读的中文名称与说明。"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

# 内置工具：id -> (中文名称, 中文说明)
BUILTIN_TOOLS: dict[str, tuple[str, str]] = {
    "fs_list": ("列出目录", "查看白名单路径下的文件与文件夹"),
    "fs_read": ("读取文件", "读取白名单内文本文件的内容"),
    "fs_write": ("写入文件", "向白名单路径写入或覆盖文本文件（高风险，需用户确认）"),
    "knowledge_search": ("检索资料库", "在绑定的资料库中按关键词检索文档片段"),
    "web_search": ("联网搜索", "检索公网网页标题、链接与摘要（默认 DuckDuckGo）"),
    "current_time": ("当前时间", "读取本机或指定时区的真实日期与时间"),
    "schedule_task": ("调度任务", "创建或管理定时/自动化任务"),
    "describe_skill": ("加载技能说明", "按技能 ID 读取 SKILL.md 全文指引，供模型遵循工作流"),
    "run_skill": ("运行技能", "将用户输入交给指定技能的工作流处理"),
}

SOURCES: dict[str, tuple[str, str]] = {
    "builtin_fs": ("内置文件工具", "本地白名单内的 fs_list / fs_read / fs_write"),
    "builtin_knowledge": ("资料库检索", "对本机资料库的 knowledge_search"),
    "builtin_web": ("联网搜索", "公网 web_search（DuckDuckGo / Tavily）"),
    "builtin_time": ("当前时间", "本机或指定时区的 current_time"),
    "builtin_schedule": ("任务调度", "定时与自动化 schedule_task"),
    "builtin": ("内置工具", "PSA 内置能力"),
    "skill": ("技能系统", "来自 skills/ 目录的 SKILL.md 技能包"),
    "mcp": ("MCP 连接器", "通过 Model Context Protocol 接入的外部工具"),
    "error": ("执行异常", "工具执行过程中抛出未捕获异常"),
}

CONFIRM_STATUS: dict[str, tuple[str, str]] = {
    "none": ("无需确认", "只读或低风险操作，直接执行"),
    "approved": ("用户已确认", "高风险写操作经用户明确同意后执行"),
    "rejected": ("用户已拒绝", "用户取消高风险写操作，未改动文件"),
}

RISK: dict[str, tuple[str, str]] = {
    "low": ("低风险", "只读或不会改变本地文件"),
    "high": ("高风险", "可能修改本地文件，需用户确认"),
}

ARG_KEYS: dict[str, str] = {
    "path": "文件路径",
    "content": "文件内容",
    "skill_id": "技能 ID",
    "input": "输入内容",
    "query": "搜索词",
    "timezone": "时区",
    "max_results": "结果条数",
    "top_k": "返回条数",
}

EXEC_STATUS: dict[str, str] = {
    "ok": "成功",
    "error": "失败",
    "cancelled": "已取消",
}


def _mcp_parts(name: str) -> tuple[str | None, str | None]:
    if not name.startswith("mcp__"):
        return None, None
    parts = name.split("__", 2)
    if len(parts) != 3:
        return None, None
    return parts[1], parts[2]


def _exec_status(is_error: bool, result: Any, confirm_status: str) -> str:
    if confirm_status == "rejected":
        return EXEC_STATUS["cancelled"]
    if is_error:
        return EXEC_STATUS["error"]
    if isinstance(result, dict) and result.get("cancelled"):
        return EXEC_STATUS["cancelled"]
    if isinstance(result, dict) and result.get("error"):
        return EXEC_STATUS["error"]
    return EXEC_STATUS["ok"]


def _tool_labels(
    name: str,
    arguments: dict[str, Any],
    *,
    skill_meta: dict[str, str] | None = None,
    mcp_server_name: str | None = None,
    mcp_tool_desc: str | None = None,
) -> dict[str, str]:
    skill_id = str(arguments.get("skill_id") or "")
    mcp_sid8, mcp_tool = _mcp_parts(name)

    if name in BUILTIN_TOOLS:
        label, desc = BUILTIN_TOOLS[name]
        if skill_id and skill_meta:
            skill_name = skill_meta.get("name") or skill_id
            skill_desc = skill_meta.get("description") or ""
            if name == "describe_skill":
                desc = f"加载技能「{skill_name}」的完整指引"
                if skill_desc:
                    desc += f"：{skill_desc}"
            elif name == "run_skill":
                desc = f"按技能「{skill_name}」的工作流处理输入"
                if skill_desc:
                    desc += f"（{skill_desc}）"
        return {"id": name, "label": label, "description": desc}

    if mcp_sid8 and mcp_tool:
        server = mcp_server_name or f"连接器 {mcp_sid8}"
        label = f"MCP · {mcp_tool}"
        desc = f"通过 MCP 连接器「{server}」调用工具 {mcp_tool}"
        if mcp_tool_desc:
            desc += f"：{mcp_tool_desc}"
        return {"id": name, "label": label, "description": desc}

    return {
        "id": name,
        "label": name,
        "description": "未注册的内置或扩展工具",
    }


def _argument_hints(arguments: dict[str, Any]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    for key, value in arguments.items():
        key_label = ARG_KEYS.get(key, key)
        if key == "path":
            hints.append({"key": key, "label": key_label, "value": str(value)})
        elif key == "skill_id":
            hints.append({"key": key, "label": key_label, "value": str(value)})
        elif key == "content":
            text = str(value)
            preview = text if len(text) <= 120 else text[:120] + "…"
            hints.append({"key": key, "label": key_label, "value": preview})
        elif key == "input":
            text = str(value)
            preview = text if len(text) <= 120 else text[:120] + "…"
            hints.append({"key": key, "label": key_label, "value": preview})
        else:
            hints.append({"key": key, "label": key_label, "value": str(value)[:200]})
    return hints


def build_audit_labels(
    *,
    name: str,
    source: str,
    confirm_status: str,
    risk: str,
    is_error: bool,
    arguments: dict[str, Any],
    result: Any,
    duration_ms: int,
    skill_meta: dict[str, str] | None = None,
    mcp_server_name: str | None = None,
    mcp_tool_desc: str | None = None,
) -> dict[str, Any]:
    """为单条审计记录生成中文标签（纯函数，便于单测）。"""
    src = SOURCES.get(source, (source, "未知来源"))
    confirm = CONFIRM_STATUS.get(confirm_status, (confirm_status, ""))
    risk_info = RISK.get(risk, (risk, ""))
    tool = _tool_labels(
        name,
        arguments,
        skill_meta=skill_meta,
        mcp_server_name=mcp_server_name,
        mcp_tool_desc=mcp_tool_desc,
    )
    status = _exec_status(is_error, result, confirm_status)

    parts = [tool["label"], src[0], confirm[0], status]
    if duration_ms:
        parts.append(f"{duration_ms}ms")
    summary = " · ".join(parts)

    return {
        "tool": tool,
        "source": {"id": source, "label": src[0], "description": src[1]},
        "confirm_status": {"id": confirm_status, "label": confirm[0], "description": confirm[1]},
        "risk": {"id": risk, "label": risk_info[0], "description": risk_info[1]},
        "status": {"label": status},
        "summary": summary,
        "arguments_hint": _argument_hints(arguments),
    }


async def _load_skill_meta(db: aiosqlite.Connection, skill_ids: set[str]) -> dict[str, dict[str, str]]:
    if not skill_ids:
        return {}
    placeholders = ",".join("?" * len(skill_ids))
    cur = await db.execute(
        f"SELECT id, name, description FROM skills WHERE id IN ({placeholders})",
        tuple(skill_ids),
    )
    return {
        r["id"]: {"name": r["name"] or r["id"], "description": r["description"] or ""}
        for r in await cur.fetchall()
    }


async def _load_mcp_meta(db: aiosqlite.Connection) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """sid8 -> 连接器名称；(server_id, tool_name) -> 工具描述。"""
    cur = await db.execute("SELECT id, name FROM mcp_servers")
    sid8_to_name: dict[str, str] = {}
    id_to_name: dict[str, str] = {}
    for r in await cur.fetchall():
        id_to_name[r["id"]] = r["name"]
        sid8_to_name[r["id"].replace("-", "")[:8]] = r["name"]

    cur = await db.execute("SELECT server_id, name, description FROM mcp_tools_cache")
    tool_desc: dict[tuple[str, str], str] = {}
    for r in await cur.fetchall():
        if r["description"]:
            tool_desc[(r["server_id"], r["name"])] = r["description"]
    return sid8_to_name, tool_desc


def _collect_refs(rows: list[Any]) -> tuple[set[str], set[str]]:
    skill_ids: set[str] = set()
    mcp_sid8s: set[str] = set()
    for r in rows:
        args = json.loads(r["arguments_json"] or "{}")
        if sid := args.get("skill_id"):
            skill_ids.add(str(sid))
        sid8, _ = _mcp_parts(r["name"])
        if sid8:
            mcp_sid8s.add(sid8)
    return skill_ids, mcp_sid8s


def _resolve_mcp_desc(
    name: str,
    sid8_to_name: dict[str, str],
    tool_desc: dict[tuple[str, str], str],
) -> tuple[str | None, str | None]:
    sid8, tool = _mcp_parts(name)
    if not sid8:
        return None, None
    server_name = sid8_to_name.get(sid8)
    desc = None
    if tool:
        for (server_id, tname), d in tool_desc.items():
            if server_id.replace("-", "")[:8] == sid8 and tname == tool:
                desc = d
                break
    return server_name, desc


def enrich_audit_record(
    row: dict[str, Any],
    *,
    skill_meta: dict[str, dict[str, str]] | None = None,
    sid8_to_name: dict[str, str] | None = None,
    mcp_tool_desc: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    arguments = row.get("arguments")
    if arguments is None:
        arguments = json.loads(row.get("arguments_json") or "{}")
    result = row.get("result")
    if result is None and "result_json" in row:
        result = json.loads(row.get("result_json") or "null")

    skill_id = str(arguments.get("skill_id") or "")
    skill = (skill_meta or {}).get(skill_id) if skill_id else None
    mcp_server, mcp_desc = _resolve_mcp_desc(
        row["name"],
        sid8_to_name or {},
        mcp_tool_desc or {},
    )

    labels = build_audit_labels(
        name=row["name"],
        source=row.get("source") or "",
        confirm_status=row.get("confirm_status") or "none",
        risk=row.get("risk") or "low",
        is_error=bool(row.get("is_error")),
        arguments=arguments if isinstance(arguments, dict) else {},
        result=result,
        duration_ms=int(row.get("duration_ms") or 0),
        skill_meta=skill,
        mcp_server_name=mcp_server,
        mcp_tool_desc=mcp_desc,
    )
    out = {k: v for k, v in row.items() if not k.endswith("_json")}
    out["labels"] = labels
    return out


async def enrich_audit_records(db: aiosqlite.Connection, rows: list[Any]) -> list[dict[str, Any]]:
    if not rows:
        return []
    skill_ids, _ = _collect_refs(rows)
    skill_meta = await _load_skill_meta(db, skill_ids)
    sid8_to_name, tool_desc = await _load_mcp_meta(db)

    items: list[dict[str, Any]] = []
    for r in rows:
        base = {
            **dict(r),
            "arguments": json.loads(r["arguments_json"] or "{}"),
            "result": json.loads(r["result_json"] or "null"),
            "is_error": bool(r["is_error"]),
        }
        items.append(
            enrich_audit_record(
                base,
                skill_meta=skill_meta,
                sid8_to_name=sid8_to_name,
                mcp_tool_desc=tool_desc,
            )
        )
    return items
