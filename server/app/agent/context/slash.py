"""Slash 技能激活：优先 Hermes skill_commands（可堆叠），否则本地 registry。"""

from __future__ import annotations

from typing import Any

from app.skills.registry import SkillRegistry


class SlashActivation:
    def __init__(
        self,
        skill_id: str,
        remaining_content: str,
        reminder: str,
        permissions: list[str] | None = None,
    ):
        self.skill_id = skill_id
        self.remaining_content = remaining_content
        self.reminder = reminder
        self.permissions = permissions or []


async def resolve_slash_activation(
    user_content: str,
    registry: SkillRegistry,
    allowed_skill_ids: set[str] | None,
) -> SlashActivation | None:
    hermes_slash: dict[str, Any] | None = None
    try:
        from app.hermes_bridge.skills_adapter import parse_slash_via_hermes

        hermes_slash = await parse_slash_via_hermes(user_content)
    except Exception:  # noqa: BLE001
        hermes_slash = None

    if hermes_slash:
        sids = hermes_slash.get("skill_ids") or []
        if allowed_skill_ids is not None:
            sids = [s for s in sids if s in allowed_skill_ids]
            if not sids and hermes_slash.get("skill_ids"):
                hermes_slash = None
        if hermes_slash:
            return SlashActivation(
                skill_id=sids[0] if sids else "skill",
                remaining_content=hermes_slash["remaining_content"],
                reminder=hermes_slash["reminder"],
                permissions=[],
            )

    slash = registry.parse_slash(user_content, allowed_skill_ids)
    if not slash:
        return None
    return SlashActivation(
        skill_id=slash.skill_id,
        remaining_content=slash.remaining_content,
        reminder=slash.reminder,
        permissions=list(getattr(slash, "permissions", None) or []),
    )
