"""预置 LLM Profile（打包后空库首次启动写入）。"""

from __future__ import annotations

import aiosqlite

from app.db.database import fetch_setting, save_setting, utc_now

# 赛题 / 演示用阿里云百炼兼容接口；固定 ID，便于升级时刷新密钥。
PRESET_LLM_PROFILES: list[dict] = [
    {
        "id": "preset-llm-qwen38-max",
        "name": "qwen3.8-max",
        "base_url": "https://ws-zgs22qb92hlvflcg.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "api_key": (
            "sk-ws-H.PMHLHXY.yw0Q.MEUCIHFDyEX3xtPqlhpLjDBn1dm4Mqfy6cy4cr-C-D-pW61uAiEAoqvFlyAmUK30pjdxJdIGj6g3Uhfr4y3i1PJ1UqjjjcY"
        ),
        "model": "qwen3.8-max",
        "temperature": 0.7,
        "max_tokens": 8192,
        "is_default": True,
    },
]


async def _sync_llm_setting(db: aiosqlite.Connection, p: dict) -> None:
    llm_cfg = (await fetch_setting(db, "llm")) or {}
    llm_cfg.update(
        {
            "base_url": p["base_url"],
            "api_key": p["api_key"],
            "model": p["model"],
            "temperature": float(p.get("temperature", 0.7)),
            "max_tokens": int(p.get("max_tokens", 8192)),
            "profile_id": p["id"],
        }
    )
    await save_setting(db, "llm", llm_cfg)


async def ensure_preset_llm_profiles(db: aiosqlite.Connection) -> int:
    """写入预置模型；已存在则刷新 URL/密钥/模型名。

    仅在首次插入且标记 is_default 时抢默认；之后不覆盖用户另选的默认模型。
    """
    now = utc_now()
    touched = 0
    for p in PRESET_LLM_PROFILES:
        cur = await db.execute(
            "SELECT id, is_default FROM llm_profiles WHERE id=?",
            (p["id"],),
        )
        row = await cur.fetchone()
        temp = float(p.get("temperature", 0.7))
        max_tokens = int(p.get("max_tokens", 8192))
        if row:
            await db.execute(
                """
                UPDATE llm_profiles
                SET name=?, base_url=?, api_key=?, model=?, temperature=?, max_tokens=?, updated_at=?
                WHERE id=?
                """,
                (
                    p["name"],
                    p["base_url"],
                    p["api_key"],
                    p["model"],
                    temp,
                    max_tokens,
                    now,
                    p["id"],
                ),
            )
            if int(row["is_default"] or 0) == 1:
                await _sync_llm_setting(db, p)
        else:
            make_default = bool(p.get("is_default"))
            if make_default:
                await db.execute("UPDATE llm_profiles SET is_default=0")
            await db.execute(
                """
                INSERT INTO llm_profiles(
                  id, name, base_url, api_key, model, temperature, max_tokens,
                  is_default, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    p["id"],
                    p["name"],
                    p["base_url"],
                    p["api_key"],
                    p["model"],
                    temp,
                    max_tokens,
                    1 if make_default else 0,
                    now,
                    now,
                ),
            )
            if make_default:
                await _sync_llm_setting(db, p)
        touched += 1
    return touched
