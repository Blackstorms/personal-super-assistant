"""知识舱：对白名单目录建 FTS 索引。"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import aiosqlite

from app.db.database import utc_now
from app.core.config import settings
from app.fs.whitelist import WhitelistError, require_allowed
from app.knowledge.text_extract import INDEXABLE_EXTS, TEXT_EXTS, extract_text_safe

# 兼容旧 import
MAX_INDEX_BYTES = 2_000_000


def _chunk_text(text: str, size: int = 800) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _read_indexable_text(path: Path) -> str | None:
    """读取可建 FTS 的正文；不支持或过大则返回 None。"""
    suffix = path.suffix.lower()
    if suffix not in INDEXABLE_EXTS:
        return None
    return extract_text_safe(path)


async def reindex_source(db: aiosqlite.Connection, source_id: str) -> dict:
    cur = await db.execute("SELECT * FROM knowledge_sources WHERE id=?", (source_id,))
    src = await cur.fetchone()
    if not src:
        raise ValueError("source not found")
    await db.execute(
        "UPDATE knowledge_sources SET state=?, last_error=NULL, updated_at=? WHERE id=?",
        ("indexing", utc_now(), source_id),
    )
    await db.commit()
    source_type = src["source_type"] if "source_type" in src.keys() else "path"
    root_path = Path(src["path"]).expanduser().resolve()
    # 上传资料落在应用数据目录，可直接索引；路径型仍须白名单
    if source_type == "upload":
        knowledge_root = (settings.data_dir / "knowledge").resolve()
        if not root_path.exists():
            await db.execute(
                "UPDATE knowledge_sources SET state=?, last_error=?, updated_at=? WHERE id=?",
                ("error", "upload path missing", utc_now(), source_id),
            )
            await db.commit()
            raise ValueError("upload path missing")
        if not str(root_path).startswith(str(knowledge_root)):
            await db.execute(
                "UPDATE knowledge_sources SET state=?, last_error=?, updated_at=? WHERE id=?",
                ("error", "upload path outside data dir", utc_now(), source_id),
            )
            await db.commit()
            raise ValueError("upload path outside data dir")
        root = root_path
    else:
        try:
            root = await require_allowed(db, src["path"])
        except WhitelistError as e:
            await db.execute(
                "UPDATE knowledge_sources SET state=?, last_error=?, updated_at=? WHERE id=?",
                ("error", str(e), utc_now(), source_id),
            )
            await db.commit()
            raise

    # 清理旧索引
    cur = await db.execute("SELECT id FROM knowledge_documents WHERE source_id=?", (source_id,))
    docs = await cur.fetchall()
    for d in docs:
        await db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (d["id"],))
    await db.execute("DELETE FROM knowledge_documents WHERE source_id=?", (source_id,))

    doc_count = 0
    paths = [root] if root.is_file() else list(root.rglob("*"))
    for path in paths:
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        digest = hashlib.sha256(str(path).encode()).hexdigest()[:16]
        doc_id = str(uuid.uuid4())
        raw = _read_indexable_text(path)
        await db.execute(
            """
            INSERT INTO knowledge_documents(id, source_id, path, content_hash, mtime, indexed_at)
            VALUES(?,?,?,?,?,?)
            """,
            (doc_id, source_id, str(path), digest, str(path.stat().st_mtime), utc_now()),
        )
        if not raw or not raw.strip():
            doc_count += 1
            continue
        content_hash = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        await db.execute(
            "UPDATE knowledge_documents SET content_hash=? WHERE id=?",
            (content_hash, doc_id),
        )
        for i, chunk in enumerate(_chunk_text(raw)):
            chunk_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO knowledge_chunks(id, document_id, chunk_index, content, token_estimate)
                VALUES(?,?,?,?,?)
                """,
                (chunk_id, doc_id, i, chunk, max(1, len(chunk) // 2)),
            )
        doc_count += 1

    await db.execute(
        "UPDATE knowledge_sources SET state=?, doc_count=?, updated_at=? WHERE id=?",
        ("ready", doc_count, utc_now(), source_id),
    )
    await db.commit()
    return {"source_id": source_id, "doc_count": doc_count, "state": "ready"}
