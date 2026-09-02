"""本轮绑定的知识库路径：对话中可读/可列，无需全局文件白名单。"""

from __future__ import annotations

import os
from pathlib import Path

import aiosqlite


async def list_knowledge_roots(
    db: aiosqlite.Connection,
    knowledge_ids: list[str] | None,
) -> list[dict[str, str]]:
    """
    返回本轮可访问的知识库根目录。
    knowledge_ids 为知识库 id（= 主 source id）或任意 source id。
    """
    if not knowledge_ids:
        return []
    placeholders = ",".join("?" * len(knowledge_ids))
    roots: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(kid: str, name: str, raw: str | None) -> None:
        if not raw:
            return
        try:
            resolved = str(Path(raw).expanduser().resolve())
        except OSError:
            return
        if resolved in seen or not Path(resolved).exists():
            return
        seen.add(resolved)
        roots.append({"id": kid, "name": name or "知识库", "path": resolved})

    cur = await db.execute(
        f"""
        SELECT id, name, root_path FROM knowledge_bases
        WHERE id IN ({placeholders})
        """,
        (*knowledge_ids,),
    )
    for row in await cur.fetchall():
        _add(row["id"], row["name"], row["root_path"])

    cur = await db.execute(
        f"""
        SELECT s.id, s.name, s.path, s.base_id, b.root_path AS base_root, b.name AS base_name
        FROM knowledge_sources s
        LEFT JOIN knowledge_bases b ON b.id = s.base_id
        WHERE s.id IN ({placeholders}) OR s.base_id IN ({placeholders})
        """,
        (*knowledge_ids, *knowledge_ids),
    )
    for row in await cur.fetchall():
        # upload 主源：优先 base.root_path；path 挂载源用 s.path
        preferred = row["base_root"] or row["path"]
        kid = row["base_id"] or row["id"]
        name = row["base_name"] or row["name"] or "知识库"
        _add(str(kid), str(name), preferred)
        if row["path"] and row["path"] != preferred:
            _add(str(kid), str(name), row["path"])

    return roots


async def is_under_knowledge(
    db: aiosqlite.Connection,
    path: str,
    knowledge_ids: list[str] | None,
) -> tuple[bool, str | None]:
    if not knowledge_ids:
        return False, None
    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError:
        return False, None
    for root in await list_knowledge_roots(db, knowledge_ids):
        root_path = root["path"]
        try:
            if os.path.commonpath([resolved, root_path]) == root_path:
                return True, resolved
        except ValueError:
            continue
    return False, resolved


async def read_knowledge_text(
    db: aiosqlite.Connection,
    path: str,
    knowledge_ids: list[str] | None,
    max_bytes: int = 512_000,
) -> dict:
    from app.fs.whitelist import WhitelistError

    ok, resolved = await is_under_knowledge(db, path, knowledge_ids)
    if not ok or not resolved:
        raise WhitelistError(f"path not in bound knowledge bases: {path}")
    target = Path(resolved)
    if not target.is_file():
        raise WhitelistError("not a file")
    data = target.read_bytes()[:max_bytes]
    return {"path": str(target), "content": data.decode("utf-8", errors="replace")}


async def list_knowledge_dir(
    db: aiosqlite.Connection,
    path: str,
    knowledge_ids: list[str] | None,
) -> list[dict]:
    from app.fs.whitelist import WhitelistError

    ok, resolved = await is_under_knowledge(db, path, knowledge_ids)
    if not ok or not resolved:
        raise WhitelistError(f"path not in bound knowledge bases: {path}")
    target = Path(resolved)
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


async def search_knowledge(
    db: aiosqlite.Connection,
    *,
    query: str,
    knowledge_ids: list[str] | None,
    top_k: int = 8,
) -> list[dict]:
    """在绑定知识库内 FTS 检索；无绑定时返回空。"""
    if not knowledge_ids:
        return []
    q = (query or "").replace('"', "").strip()
    if not q:
        return []
    top_k = max(1, min(int(top_k or 8), 20))
    placeholders = ",".join("?" * len(knowledge_ids))
    try:
        cur = await db.execute(
            f"""
            SELECT c.content, d.path
            FROM knowledge_chunks_fts f
            JOIN knowledge_chunks c ON c.rowid = f.rowid
            JOIN knowledge_documents d ON d.id = c.document_id
            JOIN knowledge_sources s ON s.id = d.source_id
            WHERE (s.id IN ({placeholders}) OR s.base_id IN ({placeholders}))
              AND knowledge_chunks_fts MATCH ?
            LIMIT ?
            """,
            (*knowledge_ids, *knowledge_ids, q, top_k),
        )
        rows = await cur.fetchall()
    except Exception:  # noqa: BLE001
        like = f"%{query}%"
        cur = await db.execute(
            f"""
            SELECT c.content, d.path FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id = c.document_id
            JOIN knowledge_sources s ON s.id = d.source_id
            WHERE (s.id IN ({placeholders}) OR s.base_id IN ({placeholders}))
              AND c.content LIKE ?
            LIMIT ?
            """,
            (*knowledge_ids, *knowledge_ids, like, top_k),
        )
        rows = await cur.fetchall()
    return [{"path": r["path"], "snippet": (r["content"] or "")[:400]} for r in rows]
