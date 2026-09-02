"""
工具风险分类（表驱动）。

PSA 内置名优先；Hermes 危险工具/toolset 与 MCP 名黑名单统一在此维护。
hermes_bridge.dispatch 复用本模块，避免双份启发式。
"""

from __future__ import annotations

from typing import Any

# PSA 独占：明确高/低
PSA_HIGH_TOOLS: frozenset[str] = frozenset({"fs_write"})
PSA_LOW_TOOLS: frozenset[str] = frozenset(
    {
        "fs_list",
        "fs_read",
        "knowledge_search",
        "web_search",
        "current_time",
        "schedule_task",
        "feishu_send_message",
        "feishu_lookup_user",
        "feishu_create_task",
        "describe_skill",
        "run_skill",
    }
)

# Hermes 高风险工具名（与默认关闭的危险 toolset 对齐）
HERMES_HIGH_TOOLS: frozenset[str] = frozenset(
    {
        "fs_write",
        "write_file",
        "patch",
        "execute_code",
        "terminal",
        "delegate_task",
        "browser_navigate",
        "browser_click",
        "browser_type",
        "cronjob",
    }
)

# 危险 Hermes toolset（默认禁用；若仍暴露工具则按高风险）
HERMES_DANGEROUS_TOOLSETS: frozenset[str] = frozenset(
    {
        "terminal",
        "code_execution",
        "delegation",
        "browser",
        "cronjob",
    }
)

# MCP 工具名子串黑名单（仅匹配 mcp__*）
MCP_HIGH_NAME_SUBSTRINGS: tuple[str, ...] = (
    "delete",
    "remove",
    "drop",
    "rm_",
    "write",
    "create_",
    "exec",
    "shell",
    "run_command",
)

# skill_manage 视为高风险的 action
SKILL_MANAGE_HIGH_ACTIONS: frozenset[str] = frozenset(
    {
        "create",
        "edit",
        "patch",
        "delete",
        "write_file",
        "remove_file",
    }
)


def classify_risk(name: str, arguments: dict[str, Any] | None = None) -> str:
    if name in PSA_HIGH_TOOLS:
        return "high"
    if name in PSA_LOW_TOOLS:
        return "low"
    if name in HERMES_HIGH_TOOLS:
        return "high"
    if name == "skill_manage":
        action = str((arguments or {}).get("action") or "")
        if action in SKILL_MANAGE_HIGH_ACTIONS:
            return "high"
    if name.startswith("mcp__"):
        lower = name.lower()
        for bad in MCP_HIGH_NAME_SUBSTRINGS:
            if bad in lower:
                return "high"
    # toolset 名作为工具前缀时（少数 Hermes 命名）
    root = name.split("__", 1)[0].lower()
    if root in HERMES_DANGEROUS_TOOLSETS:
        return "high"
    return "low"


def classify_source(name: str) -> str:
    if name.startswith("mcp__"):
        return "mcp"
    if name in {
        "skills_list",
        "skill_view",
        "skill_manage",
        "describe_skill",
        "run_skill",
    }:
        return "skill"
    if name.startswith("fs_") or name in {
        "knowledge_search",
        "web_search",
        "current_time",
        "schedule_task",
        "feishu_send_message",
        "feishu_lookup_user",
        "feishu_create_task",
    }:
        if name.startswith("fs_"):
            return "builtin_fs"
        if name == "web_search":
            return "builtin_web"
        if name == "current_time":
            return "builtin_time"
        if name.startswith("feishu_"):
            return "builtin_feishu"
        return "builtin"
    if name in {"read_file", "write_file", "search_files", "patch"}:
        return "builtin_fs"
    return "hermes"


def canonical_tool_key(name: str, arguments: dict[str, Any] | None) -> str:
    """循环检测用稳定键。"""
    import json

    try:
        args = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        args = str(arguments)
    return f"{name}|{args}"
