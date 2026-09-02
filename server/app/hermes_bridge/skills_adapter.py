"""
Hermes skills 适配：slash 堆叠、技能目录、pending 写审批列表（轻量）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SLASH_HEAD = re.compile(r"^(/[a-zA-Z0-9_-]+)(?:\s+(.*))?$", re.S)


async def parse_slash_via_hermes(user_content: str) -> dict[str, Any] | None:
    """
    使用 Hermes skill_commands 解析 /skill（支持堆叠）。
    成功返回 {reminder, remaining_content, skill_ids: [...]}；失败 None。
    """
    from app.hermes_bridge.paths import ensure_hermes_on_syspath

    if not ensure_hermes_on_syspath():
        return None
    text = user_content.strip()
    if not text.startswith("/"):
        return None

    def _parse() -> dict[str, Any] | None:
        try:
            from agent.skill_commands import (  # type: ignore
                build_skill_invocation_message,
                build_stacked_skill_invocation_message,
                resolve_skill_command_key,
                split_stacked_skill_commands,
            )

            # 首 token
            first, _, rest = text.partition(" ")
            key = resolve_skill_command_key(first.lstrip("/"))
            if not key:
                # 尝试带斜杠
                key = resolve_skill_command_key(first)
            if not key:
                return None

            keys, instruction = split_stacked_skill_commands(rest)
            # split 返回后续 skill keys；把第一个并上
            all_keys = [key] + list(keys or [])
            all_keys = all_keys[:5]
            if len(all_keys) > 1:
                built = build_stacked_skill_invocation_message(all_keys, instruction or "")
                if not built:
                    return None
                msg, loaded, skipped = built
                return {
                    "reminder": msg,
                    "remaining_content": instruction or f"(Apply skills {', '.join(all_keys)})",
                    "skill_ids": [k.lstrip("/") for k in loaded or all_keys],
                    "skipped": skipped or [],
                }
            msg = build_skill_invocation_message(all_keys[0], instruction or "")
            if not msg:
                return None
            return {
                "reminder": msg,
                "remaining_content": instruction or f"(Apply skill {all_keys[0]})",
                "skill_ids": [all_keys[0].lstrip("/")],
                "skipped": [],
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("hermes slash parse failed: %s", e)
            return None

    return await asyncio.to_thread(_parse)


async def list_hermes_skill_commands() -> list[dict[str, str]]:
    from app.hermes_bridge.paths import ensure_hermes_on_syspath

    if not ensure_hermes_on_syspath():
        return []

    def _list() -> list[dict[str, str]]:
        try:
            from agent.skill_commands import get_skill_commands, scan_skill_commands  # type: ignore

            scan_skill_commands()
            cmds = get_skill_commands() or {}
            out = []
            for k, meta in cmds.items():
                out.append(
                    {
                        "id": str(k).lstrip("/"),
                        "slash": k if str(k).startswith("/") else f"/{k}",
                        "name": str((meta or {}).get("name") or k),
                        "description": str((meta or {}).get("description") or ""),
                    }
                )
            return out
        except Exception as e:  # noqa: BLE001
            logger.debug("list skill commands failed: %s", e)
            return []

    return await asyncio.to_thread(_list)
