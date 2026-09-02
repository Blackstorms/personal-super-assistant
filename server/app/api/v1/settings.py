"""LLM / 白名单 / 多模型 profiles 设置 API。"""

from __future__ import annotations

import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_token
from app.db.database import fetch_setting, save_setting, utc_now
from app.db.deps import db_dep
from app.fs import whitelist as fs
from app.fs.whitelist import WhitelistError
from app.llm.gateway import create_gateway

router = APIRouter(dependencies=[Depends(require_token)])


class LLMSettings(BaseModel):
    base_url: str
    api_key: str | None = None
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    provider: str | None = None


class LLMProfileIn(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    model: str
    temperature: float = 0.7
    max_tokens: int = 2048
    is_default: bool = False


class LLMProfilePatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    is_default: bool | None = None


class WhitelistBody(BaseModel):
    roots: list[str]


class ValidateBody(BaseModel):
    path: str


class WebSearchSettingsIn(BaseModel):
    provider: str | None = None
    api_url: str | None = None
    api_key: str | None = None
    tavily_api_key: str | None = None


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return key[:3] + "***" + key[-2:]


def _profile_row(r: aiosqlite.Row) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "base_url": r["base_url"],
        "model": r["model"],
        "temperature": r["temperature"],
        "max_tokens": r["max_tokens"],
        "is_default": bool(r["is_default"]),
        "api_key_masked": _mask(r["api_key"] or ""),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


async def _sync_legacy_llm(db: aiosqlite.Connection, profile_id: str | None = None) -> None:
    """保持旧 /settings/llm 与默认 profile 同步，兼容旧客户端。"""
    if profile_id:
        cur = await db.execute("SELECT * FROM llm_profiles WHERE id=?", (profile_id,))
    else:
        cur = await db.execute("SELECT * FROM llm_profiles WHERE is_default=1 LIMIT 1")
    r = await cur.fetchone()
    if not r:
        cur = await db.execute("SELECT * FROM llm_profiles ORDER BY updated_at DESC LIMIT 1")
        r = await cur.fetchone()
    if not r:
        return
    await save_setting(
        db,
        "llm",
        {
            "base_url": r["base_url"],
            "api_key": r["api_key"] or "",
            "model": r["model"],
            "temperature": r["temperature"],
            "max_tokens": r["max_tokens"],
            "profile_id": r["id"],
        },
    )


async def _clear_defaults(db: aiosqlite.Connection) -> None:
    await db.execute("UPDATE llm_profiles SET is_default=0")


@router.get("/llm")
async def get_llm(db: aiosqlite.Connection = Depends(db_dep)):
    cfg = await fetch_setting(db, "llm") or {}
    return {
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "temperature": cfg.get("temperature", 0.7),
        "max_tokens": cfg.get("max_tokens", 2048),
        "api_key_masked": _mask(cfg.get("api_key", "")),
        "profile_id": cfg.get("profile_id"),
        "provider": cfg.get("provider") or "",
    }


@router.put("/llm")
async def put_llm(body: LLMSettings, db: aiosqlite.Connection = Depends(db_dep)):
    cfg = await fetch_setting(db, "llm") or {}
    cfg["base_url"] = body.base_url
    cfg["model"] = body.model
    cfg["temperature"] = body.temperature
    cfg["max_tokens"] = body.max_tokens
    if body.provider is not None:
        cfg["provider"] = body.provider
    if body.api_key is not None and body.api_key != "":
        cfg["api_key"] = body.api_key
    await save_setting(db, "llm", cfg)

    # 同步到默认 profile
    cur = await db.execute("SELECT id, api_key FROM llm_profiles WHERE is_default=1 LIMIT 1")
    row = await cur.fetchone()
    api_key = cfg.get("api_key", "")
    if row:
        if body.api_key is None or body.api_key == "":
            api_key = row["api_key"] or ""
        await db.execute(
            """
            UPDATE llm_profiles SET base_url=?, api_key=?, model=?, temperature=?, max_tokens=?, updated_at=?
            WHERE id=?
            """,
            (body.base_url, api_key, body.model, body.temperature, body.max_tokens, utc_now(), row["id"]),
        )
        cfg["profile_id"] = row["id"]
        await save_setting(db, "llm", cfg)
    else:
        pid = str(uuid.uuid4())
        now = utc_now()
        await db.execute(
            """
            INSERT INTO llm_profiles(
              id, name, base_url, api_key, model, temperature, max_tokens, is_default, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (pid, "默认模型", body.base_url, api_key, body.model, body.temperature, body.max_tokens, 1, now, now),
        )
        cfg["profile_id"] = pid
        await save_setting(db, "llm", cfg)
    await db.commit()
    return await get_llm(db)


@router.post("/llm/test")
async def test_llm(body: LLMSettings | None = None, db: aiosqlite.Connection = Depends(db_dep)):
    if body:
        gw = create_gateway(
            base_url=body.base_url,
            api_key=body.api_key or "",
            model=body.model,
            provider=body.provider,
        )
    else:
        cfg = await fetch_setting(db, "llm") or {}
        gw = create_gateway(
            base_url=cfg.get("base_url") or "https://api.openai.com/v1",
            api_key=cfg.get("api_key") or "",
            model=cfg.get("model") or "gpt-4o-mini",
            provider=cfg.get("provider"),
        )
    return await gw.test_connection()


@router.get("/llm/profiles")
async def list_profiles(db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM llm_profiles ORDER BY is_default DESC, updated_at DESC")
    rows = await cur.fetchall()
    return {"items": [_profile_row(r) for r in rows], "total": len(rows)}


@router.post("/llm/profiles")
async def create_profile(body: LLMProfileIn, db: aiosqlite.Connection = Depends(db_dep)):
    pid = str(uuid.uuid4())
    now = utc_now()
    if body.is_default:
        await _clear_defaults(db)
    await db.execute(
        """
        INSERT INTO llm_profiles(
          id, name, base_url, api_key, model, temperature, max_tokens, is_default, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            pid,
            body.name,
            body.base_url,
            body.api_key or "",
            body.model,
            body.temperature,
            body.max_tokens,
            1 if body.is_default else 0,
            now,
            now,
        ),
    )
    if body.is_default:
        await _sync_legacy_llm(db, pid)
    await db.commit()
    cur = await db.execute("SELECT * FROM llm_profiles WHERE id=?", (pid,))
    return _profile_row(await cur.fetchone())


@router.patch("/llm/profiles/{profile_id}")
async def patch_profile(profile_id: str, body: LLMProfilePatch, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM llm_profiles WHERE id=?", (profile_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "profile not found"})
    name = body.name if body.name is not None else r["name"]
    base_url = body.base_url if body.base_url is not None else r["base_url"]
    model = body.model if body.model is not None else r["model"]
    temperature = body.temperature if body.temperature is not None else r["temperature"]
    max_tokens = body.max_tokens if body.max_tokens is not None else r["max_tokens"]
    api_key = r["api_key"] or ""
    if body.api_key is not None and body.api_key != "":
        api_key = body.api_key
    is_default = r["is_default"]
    if body.is_default is not None:
        if body.is_default:
            await _clear_defaults(db)
            is_default = 1
        else:
            is_default = 0
    await db.execute(
        """
        UPDATE llm_profiles SET name=?, base_url=?, api_key=?, model=?, temperature=?, max_tokens=?,
          is_default=?, updated_at=? WHERE id=?
        """,
        (name, base_url, api_key, model, temperature, max_tokens, is_default, utc_now(), profile_id),
    )
    if is_default:
        await _sync_legacy_llm(db, profile_id)
    await db.commit()
    cur = await db.execute("SELECT * FROM llm_profiles WHERE id=?", (profile_id,))
    return _profile_row(await cur.fetchone())


@router.delete("/llm/profiles/{profile_id}")
async def delete_profile(profile_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM llm_profiles WHERE id=?", (profile_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "profile not found"})
    await db.execute("DELETE FROM llm_profiles WHERE id=?", (profile_id,))
    if r["is_default"]:
        cur = await db.execute("SELECT id FROM llm_profiles ORDER BY updated_at DESC LIMIT 1")
        nxt = await cur.fetchone()
        if nxt:
            await db.execute("UPDATE llm_profiles SET is_default=1 WHERE id=?", (nxt["id"],))
            await _sync_legacy_llm(db, nxt["id"])
    await db.commit()
    return {"ok": True}


@router.post("/llm/profiles/{profile_id}/test")
async def test_profile(profile_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    cur = await db.execute("SELECT * FROM llm_profiles WHERE id=?", (profile_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "profile not found"})
    gw = create_gateway(
        base_url=r["base_url"] or "https://api.openai.com/v1",
        api_key=r["api_key"] or "",
        model=r["model"] or "gpt-4o-mini",
        temperature=float(r["temperature"] or 0.7),
        max_tokens=int(r["max_tokens"] or 2048),
    )
    return await gw.test_connection()


@router.get("/whitelist")
async def get_whitelist(db: aiosqlite.Connection = Depends(db_dep)):
    return {"roots": await fs.list_roots(db)}


@router.put("/whitelist")
async def put_whitelist(body: WhitelistBody, db: aiosqlite.Connection = Depends(db_dep)):
    try:
        roots = await fs.set_roots(db, body.roots)
    except WhitelistError as e:
        raise HTTPException(400, detail={"code": "invalid_root", "message": str(e)}) from e
    return {"roots": roots}


@router.post("/whitelist/validate")
async def validate_path(body: ValidateBody, db: aiosqlite.Connection = Depends(db_dep)):
    allowed, resolved = await fs.is_allowed(db, body.path)
    return {"allowed": allowed, "resolved_path": resolved}


def _web_search_public(cfg: dict) -> dict:
    return {
        "provider": cfg.get("provider") or "auto",
        "api_url": cfg.get("api_url") or "",
        "api_key_masked": _mask(cfg.get("api_key") or ""),
        "tavily_api_key_masked": _mask(cfg.get("tavily_api_key") or ""),
        "has_api_key": bool((cfg.get("api_key") or "").strip()),
        "has_tavily_key": bool((cfg.get("tavily_api_key") or "").strip()),
    }


def _apply_web_search_env(cfg: dict) -> None:
    import os

    from app.core.env_load import persist_search_env
    from app.core.config import settings as app_settings

    mapping = {
        "PSA_WEB_SEARCH_PROVIDER": (cfg.get("provider") or "auto").strip() or "auto",
        "PSA_WEB_SEARCH_API_URL": (cfg.get("api_url") or "").strip(),
        "PSA_WEB_SEARCH_API_KEY": (cfg.get("api_key") or "").strip(),
        "TAVILY_API_KEY": (cfg.get("tavily_api_key") or "").strip(),
    }
    for key, val in mapping.items():
        if val:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)
    persist_search_env(app_settings.data_dir, overwrite=True)


@router.get("/web-search")
async def get_web_search(db: aiosqlite.Connection = Depends(db_dep)):
    import os

    stored = await fetch_setting(db, "web_search") or {}
    cfg = {
        "provider": (os.environ.get("PSA_WEB_SEARCH_PROVIDER") or stored.get("provider") or "auto").strip()
        or "auto",
        "api_url": (os.environ.get("PSA_WEB_SEARCH_API_URL") or stored.get("api_url") or "").strip(),
        "api_key": (os.environ.get("PSA_WEB_SEARCH_API_KEY") or stored.get("api_key") or "").strip(),
        "tavily_api_key": (os.environ.get("TAVILY_API_KEY") or stored.get("tavily_api_key") or "").strip(),
    }
    return _web_search_public(cfg)


@router.put("/web-search")
async def put_web_search(body: WebSearchSettingsIn, db: aiosqlite.Connection = Depends(db_dep)):
    stored = await fetch_setting(db, "web_search") or {}
    cfg = {
        "provider": stored.get("provider") or "auto",
        "api_url": stored.get("api_url") or "",
        "api_key": stored.get("api_key") or "",
        "tavily_api_key": stored.get("tavily_api_key") or "",
    }
    if body.provider is not None:
        cfg["provider"] = body.provider.strip() or "auto"
    if body.api_url is not None:
        cfg["api_url"] = body.api_url.strip()
    if body.api_key:
        cfg["api_key"] = body.api_key.strip()
    if body.tavily_api_key:
        cfg["tavily_api_key"] = body.tavily_api_key.strip()
    await save_setting(db, "web_search", cfg)
    _apply_web_search_env(cfg)
    return _web_search_public(cfg)
