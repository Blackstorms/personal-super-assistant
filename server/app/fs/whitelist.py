"""
本地文件白名单守卫。

安全约束：
- 默认：业务文件路径必须 resolve 后落在 whitelist_roots 之内
- 定时任务执行可 bypass_whitelist，跳过白名单校验
- 拒绝无效路径（通过 resolve）
"""

from __future__ import annotations

import uuid
from pathlib import Path

import aiosqlite

from app.db.database import utc_now


class WhitelistError(Exception):
    """路径未授权或非法。"""


async def list_roots(db: aiosqlite.Connection) -> list[str]:
    cur = await db.execute("SELECT path FROM whitelist_roots ORDER BY created_at")
    rows = await cur.fetchall()
    return [r["path"] for r in rows]


async def set_roots(db: aiosqlite.Connection, roots: list[str]) -> list[str]:
    """覆盖写入白名单（规范化绝对路径）。"""
    normalized: list[str] = []
    for r in roots:
        p = Path(r).expanduser().resolve()
        if not p.exists() or not p.is_dir():
            raise WhitelistError(f"root not a directory: {r}")
        normalized.append(str(p))
    await db.execute("DELETE FROM whitelist_roots")
    for path in normalized:
        await db.execute(
            "INSERT INTO whitelist_roots(id, path, created_at) VALUES(?,?,?)",
            (str(uuid.uuid4()), path, utc_now()),
        )
    await db.commit()
    return normalized


async def is_allowed(db: aiosqlite.Connection, path: str) -> tuple[bool, str | None]:
    """返回 (是否允许, resolve 后路径)。使用 commonpath 防前缀伪造。"""
    import os

    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError:
        return False, None
    roots = await list_roots(db)
    for root in roots:
        try:
            if os.path.commonpath([resolved, root]) == root:
                return True, resolved
        except ValueError:
            continue
    return False, resolved


async def require_allowed(db: aiosqlite.Connection, path: str) -> Path:
    ok, resolved = await is_allowed(db, path)
    if not ok or resolved is None:
        raise WhitelistError(f"path not in whitelist: {path}")
    return Path(resolved)


def _resolve_existing(path: str) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError as e:
        raise WhitelistError(f"invalid path: {path}") from e


async def list_dir(db: aiosqlite.Connection, path: str, *, bypass_whitelist: bool = False) -> list[dict]:
    target = _resolve_existing(path) if bypass_whitelist else await require_allowed(db, path)
    if not target.is_dir():
        raise WhitelistError("not a directory")
    entries = []
    for child in sorted(target.iterdir()):
        entries.append(
            {
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size": child.stat().st_size if child.is_file() else None,
            }
        )
    return entries


async def read_text(
    db: aiosqlite.Connection,
    path: str,
    max_bytes: int = 512_000,
    *,
    bypass_whitelist: bool = False,
) -> dict:
    target = _resolve_existing(path) if bypass_whitelist else await require_allowed(db, path)
    if not target.is_file():
        raise WhitelistError("not a file")
    data = target.read_bytes()[:max_bytes]
    return {"path": str(target), "content": data.decode("utf-8", errors="replace")}


async def read_text_for_session(
    db: aiosqlite.Connection,
    path: str,
    session_id: str | None,
    max_bytes: int = 512_000,
    knowledge_ids: list[str] | None = None,
    *,
    bypass_whitelist: bool = False,
) -> dict:
    """白名单路径、会话附件、绑定知识库路径可读；定时任务可跳过白名单。"""
    if bypass_whitelist:
        return await read_text(db, path, max_bytes=max_bytes, bypass_whitelist=True)
    if session_id:
        from app.fs import session_attachments as sa

        ok, _ = sa.is_under_session(session_id, path)
        if ok:
            return await sa.read_attachment_text(db, session_id, path, max_bytes=max_bytes)
    if knowledge_ids:
        from app.fs import knowledge_access as ka

        ok, _ = await ka.is_under_knowledge(db, path, knowledge_ids)
        if ok:
            return await ka.read_knowledge_text(db, path, knowledge_ids, max_bytes=max_bytes)
    return await read_text(db, path, max_bytes=max_bytes)


async def list_dir_for_session(
    db: aiosqlite.Connection,
    path: str,
    session_id: str | None,
    knowledge_ids: list[str] | None = None,
    *,
    bypass_whitelist: bool = False,
) -> list[dict]:
    if bypass_whitelist:
        return await list_dir(db, path, bypass_whitelist=True)
    if session_id:
        from app.fs import session_attachments as sa

        ok, _ = sa.is_under_session(session_id, path)
        if ok:
            return await sa.list_attachment_dir(db, session_id, path)
    if knowledge_ids:
        from app.fs import knowledge_access as ka

        ok, _ = await ka.is_under_knowledge(db, path, knowledge_ids)
        if ok:
            return await ka.list_knowledge_dir(db, path, knowledge_ids)
    return await list_dir(db, path)


async def write_text(
    db: aiosqlite.Connection,
    path: str,
    content: str,
    *,
    bypass_whitelist: bool = False,
) -> dict:
    """高风险写操作：调用方应先走确认闸（定时任务可跳过白名单）。"""
    target = _resolve_existing(path) if bypass_whitelist else await require_allowed(db, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target)}
