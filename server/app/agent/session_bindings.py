"""会话 composer 绑定（专家 / 技能 / MCP / 资料库）持久化与读写。"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from app.db.database import utc_now

BindingPayload = dict[str, Any]


def normalize_bindings(
    *,
    expert_id: str | None = None,
    skill_ids: list[str] | None = None,
    mcp_ids: list[str] | None = None,
    knowledge_ids: list[str] | None = None,
    model_profile_id: str | None = None,
) -> BindingPayload:
    """
    序列化前规范化。
    list 字段保留 None（表示未显式选择 / 继承）与 []（显式清空）语义。
    """
    return {
        "expert_id": expert_id or None,
        "skill_ids": list(skill_ids) if skill_ids is not None else None,
        "mcp_ids": list(mcp_ids) if mcp_ids is not None else None,
        "knowledge_ids": list(knowledge_ids) if knowledge_ids is not None else None,
        "model_profile_id": model_profile_id or None,
    }


def parse_bindings_json(raw: str | None) -> BindingPayload | None:
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return normalize_bindings(
        expert_id=data.get("expert_id"),
        skill_ids=data.get("skill_ids"),
        mcp_ids=data.get("mcp_ids"),
        knowledge_ids=data.get("knowledge_ids"),
        model_profile_id=data.get("model_profile_id"),
    )


def session_row_with_bindings(row: dict) -> dict:
    """把 sessions 行中的 composer_bindings_json 展开为 composer_bindings。"""
    out = dict(row)
    raw = out.pop("composer_bindings_json", None)
    out["composer_bindings"] = parse_bindings_json(raw if isinstance(raw, str) else None)
    return out


async def save_session_composer_bindings(
    db: aiosqlite.Connection,
    session_id: str,
    bindings: BindingPayload,
) -> None:
    payload = normalize_bindings(
        expert_id=bindings.get("expert_id"),
        skill_ids=bindings.get("skill_ids"),
        mcp_ids=bindings.get("mcp_ids"),
        knowledge_ids=bindings.get("knowledge_ids"),
        model_profile_id=bindings.get("model_profile_id"),
    )
    await db.execute(
        """
        UPDATE sessions
        SET composer_bindings_json=?, updated_at=?
        WHERE id=?
        """,
        (json.dumps(payload, ensure_ascii=False), utc_now(), session_id),
    )
    await db.commit()
