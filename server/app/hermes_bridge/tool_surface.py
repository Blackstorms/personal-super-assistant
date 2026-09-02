"""
收集 Hermes OpenAI tools schema，并按会话 skill/mcp/toolset 过滤。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent.risk import HERMES_DANGEROUS_TOOLSETS

logger = logging.getLogger(__name__)


def _safe_import_model_tools():
    from app.hermes_bridge.paths import ensure_hermes_on_syspath

    if not ensure_hermes_on_syspath():
        return None
    try:
        import model_tools  # type: ignore

        return model_tools
    except Exception as e:  # noqa: BLE001
        logger.warning("import model_tools failed: %s", e)
        return None


async def list_toolsets() -> dict[str, Any]:
    mt = _safe_import_model_tools()
    if not mt:
        return {}
    try:
        return await asyncio.to_thread(mt.get_available_toolsets)
    except Exception as e:  # noqa: BLE001
        logger.warning("get_available_toolsets failed: %s", e)
        return {}


async def get_openai_tools(
    *,
    enabled_toolsets: list[str] | None = None,
    disabled_toolsets: list[str] | None = None,
    include_skills: bool = True,
    include_mcp: bool = True,
) -> list[dict]:
    """
    从 Hermes 拉取 tool definitions。
    默认启用 skills + 动态 MCP toolset；内置危险 toolset 可按设置裁剪。
    """
    mt = _safe_import_model_tools()
    if not mt:
        return []

    toolsets = list(enabled_toolsets or [])
    if not toolsets:
        # 桌面助理默认面：skills + web(若可用) + 已注册 MCP
        toolsets = ["skills"]
        if include_mcp:
            # MCP 工具通过 registry 动态挂入，名称以 mcp__ 开头；
            # get_tool_definitions(None) 会收集所有已注册工具。
            pass

    disabled = list(disabled_toolsets or [])
    # 默认关闭终端/代码执行等需沙箱的能力，除非用户在设置中打开
    for risky in HERMES_DANGEROUS_TOOLSETS:
        if risky not in disabled and (not enabled_toolsets or risky not in enabled_toolsets):
            disabled.append(risky)

    def _collect() -> list[dict]:
        if enabled_toolsets:
            return mt.get_tool_definitions(
                enabled_toolsets=enabled_toolsets,
                disabled_toolsets=disabled or None,
                quiet_mode=True,
            )
        # 无显式 toolset：取 skills + 当前 registry 中全部（含 MCP）
        base = mt.get_tool_definitions(
            enabled_toolsets=["skills"] if include_skills else [],
            disabled_toolsets=disabled,
            quiet_mode=True,
        )
        if not include_skills:
            base = [t for t in base if not _is_skill_tool(t)]
        # 再拉一次全量以便带上 MCP（quiet）
        try:
            from tools.registry import registry  # type: ignore

            all_names = set(registry.list_tools() if hasattr(registry, "list_tools") else [])
            if not all_names and hasattr(registry, "tools"):
                all_names = set(getattr(registry, "tools", {}).keys())
            mcp_names = {n for n in all_names if str(n).startswith("mcp__")}
            if include_mcp and mcp_names:
                mcp_defs = registry.get_definitions(mcp_names, quiet=True)
                seen = {((t.get("function") or {}).get("name")) for t in base}
                for d in mcp_defs:
                    n = (d.get("function") or {}).get("name")
                    if n and n not in seen:
                        base.append(d)
        except Exception as e:  # noqa: BLE001
            logger.debug("append mcp defs failed: %s", e)
        return base

    try:
        return await asyncio.to_thread(_collect)
    except Exception as e:  # noqa: BLE001
        logger.warning("get_openai_tools failed: %s", e)
        return []


def _is_skill_tool(t: dict) -> bool:
    name = ((t.get("function") or {}).get("name") or "")
    return name in {"skills_list", "skill_view", "skill_manage", "describe_skill", "run_skill"}


def filter_by_mcp_ids(
    tools: list[dict],
    mcp_ids: list[str] | None,
    *,
    id_to_keys: dict[str, str] | None = None,
) -> list[dict]:
    """
    mcp_ids=None 不过滤；[] 去掉全部 mcp__*；
    非空时按 Hermes server key / sid8 / uuid 匹配。
    """
    if mcp_ids is None:
        return tools
    non_mcp = [t for t in tools if not ((t.get("function") or {}).get("name") or "").startswith("mcp__")]
    if len(mcp_ids) == 0:
        return non_mcp

    allowed_keys: set[str] = set()
    for mid in mcp_ids:
        allowed_keys.add(mid)
        allowed_keys.add(mid.replace("-", "")[:8])
        if id_to_keys and mid in id_to_keys:
            allowed_keys.add(id_to_keys[mid])

    out = list(non_mcp)
    for t in tools:
        name = ((t.get("function") or {}).get("name") or "")
        if not name.startswith("mcp__"):
            continue
        parts = name.split("__", 2)
        if len(parts) >= 2 and parts[1] in allowed_keys:
            out.append(t)
            continue
        # 键可能是 name_sid8
        if len(parts) >= 2:
            server_part = parts[1]
            for ak in allowed_keys:
                if server_part.endswith(ak) or ak in server_part:
                    out.append(t)
                    break
    return out


def filter_skill_tools(tools: list[dict], allowed_skill_ids: set[str] | None) -> list[dict]:
    """技能工具始终保留；allowed 为空集合时去掉 skills_*。"""
    if allowed_skill_ids is None:
        return tools
    if len(allowed_skill_ids) == 0:
        return [t for t in tools if not _is_skill_tool(t)]
    return tools
