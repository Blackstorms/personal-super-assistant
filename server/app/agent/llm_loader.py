"""按 profile 加载 LLM 网关。"""

from __future__ import annotations

import aiosqlite

from app.db.database import fetch_setting
from app.llm.gateway import LLMGateway, create_gateway


async def load_llm(db: aiosqlite.Connection, profile_id: str | None = None) -> LLMGateway:
    """按 profile 加载模型；无 profile 时回退默认或旧 llm 设置。支持 provider=mock。"""
    row = None
    if profile_id:
        cur = await db.execute("SELECT * FROM llm_profiles WHERE id=?", (profile_id,))
        row = await cur.fetchone()
    if row is None:
        cur = await db.execute("SELECT * FROM llm_profiles WHERE is_default=1 LIMIT 1")
        row = await cur.fetchone()
    if row is not None:
        provider = None
        try:
            provider = row["provider"]
        except (KeyError, IndexError):
            provider = None
        return create_gateway(
            base_url=row["base_url"] or "https://api.openai.com/v1",
            api_key=row["api_key"] or "",
            model=row["model"] or "gpt-4o-mini",
            temperature=float(row["temperature"] or 0.7),
            max_tokens=int(row["max_tokens"] or 2048),
            provider=provider,
        )
    cfg = await fetch_setting(db, "llm") or {}
    return create_gateway(
        base_url=cfg.get("base_url") or "https://api.openai.com/v1",
        api_key=cfg.get("api_key") or "",
        model=cfg.get("model") or "gpt-4o-mini",
        temperature=float(cfg.get("temperature", 0.7)),
        max_tokens=int(cfg.get("max_tokens", 2048)),
        provider=cfg.get("provider"),
    )
