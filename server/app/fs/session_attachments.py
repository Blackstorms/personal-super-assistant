"""
会话附件：用户上传/选择的文件复制到 data_dir，对话时可跳过全局白名单。

安全边界：仅允许读取/列出本会话附件目录内的路径。
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import aiosqlite

from app.core.config import settings
from app.db.database import utc_now
from app.knowledge.text_extract import INDEXABLE_EXTS, TEXT_EXTS, TextExtractError, extract_text

MAX_FILE_BYTES = 512_000
MAX_TOTAL_CONTEXT_BYTES = 2_000_000

TEXT_SUFFIXES = TEXT_EXTS


def session_dir(session_id: str) -> Path:
    root = settings.data_dir / "session_attachments" / session_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_under_session(session_id: str, path: str) -> tuple[bool, str | None]:
    try:
        resolved = str(Path(path).expanduser().resolve())
    except OSError:
        return False, None
    root = str(session_dir(session_id).resolve())
    if resolved == root or resolved.startswith(root.rstrip("/") + "/"):
        return True, resolved
    return False, resolved


def _safe_name(name: str) -> str:
    base = Path(name).name or "file"
    return base.replace("/", "_").replace("\\", "_")[:200]


def _unique_target(dest_dir: Path, name: str) -> Path:
    target = dest_dir / _safe_name(name)
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    n = 1
    while target.exists():
        target = dest_dir / f"{stem}_{n}{suffix}"
        n += 1
    return target


def _read_text_file(path: Path, max_bytes: int = MAX_FILE_BYTES) -> str:
    suffix = path.suffix.lower()
    if suffix in INDEXABLE_EXTS and suffix not in TEXT_EXTS:
        return extract_text(path, max_bytes=max_bytes)
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


async def _insert_row(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    name: str,
    path: str,
    size_bytes: int,
    mime_type: str | None = None,
) -> dict:
    aid = str(uuid.uuid4())
    now = utc_now()
    await db.execute(
        """
        INSERT INTO session_attachments(id, session_id, name, path, size_bytes, mime_type, created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (aid, session_id, name, path, size_bytes, mime_type, now),
    )
    await db.commit()
    return {
        "id": aid,
        "session_id": session_id,
        "name": name,
        "path": path,
        "size_bytes": size_bytes,
        "mime_type": mime_type,
        "created_at": now,
    }


async def ingest_paths(
    db: aiosqlite.Connection,
    session_id: str,
    paths: list[str],
) -> list[dict]:
    """从任意本地路径复制文件/目录到会话附件区（不要求白名单）。"""
    dest_root = session_dir(session_id)
    created: list[dict] = []
    for raw in paths:
        src = Path(raw).expanduser().resolve()
        if not src.exists():
            continue
        if src.is_dir():
            for child in sorted(src.rglob("*")):
                if not child.is_file():
                    continue
                rel = child.relative_to(src)
                target = _unique_target(dest_root, str(rel))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, target)
                st = target.stat()
                created.append(
                    await _insert_row(
                        db,
                        session_id=session_id,
                        name=str(rel),
                        path=str(target),
                        size_bytes=st.st_size,
                    )
                )
        else:
            target = _unique_target(dest_root, src.name)
            shutil.copy2(src, target)
            st = target.stat()
            created.append(
                await _insert_row(
                    db,
                    session_id=session_id,
                    name=src.name,
                    path=str(target),
                    size_bytes=st.st_size,
                )
            )
    return created


async def ingest_text_files(
    db: aiosqlite.Connection,
    session_id: str,
    files: list[dict],
) -> list[dict]:
    """浏览器上传的文本内容写入会话附件区。"""
    dest_root = session_dir(session_id)
    created: list[dict] = []
    for item in files:
        name = _safe_name(str(item.get("name") or "upload.txt"))
        content = str(item.get("content") or "")
        encoding = str(item.get("encoding") or "utf-8")
        target = _unique_target(dest_root, name)
        if encoding == "base64":
            import base64

            data = base64.b64decode(content)
            target.write_bytes(data[:MAX_FILE_BYTES])
        else:
            target.write_text(content[:MAX_FILE_BYTES], encoding="utf-8")
        st = target.stat()
        created.append(
            await _insert_row(
                db,
                session_id=session_id,
                name=name,
                path=str(target),
                size_bytes=st.st_size,
            )
        )
    return created


async def list_attachments(db: aiosqlite.Connection, session_id: str) -> list[dict]:
    cur = await db.execute(
        "SELECT * FROM session_attachments WHERE session_id=? ORDER BY created_at",
        (session_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def load_context_snippets(db: aiosqlite.Connection, session_id: str) -> list[dict]:
    """读取会话附件文本，供模型上下文注入。"""
    rows = await list_attachments(db, session_id)
    snippets: list[dict] = []
    total = 0
    for row in rows:
        path = Path(row["path"])
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        is_indexable = suffix in INDEXABLE_EXTS or path.suffix == ""
        if not is_indexable:
            snippets.append(
                {
                    "name": row["name"],
                    "path": row["path"],
                    "content": f"[二进制文件 {row['name']}，大小 {row['size_bytes']} 字节]",
                    "truncated": False,
                }
            )
            continue
        remaining = MAX_TOTAL_CONTEXT_BYTES - total
        if remaining <= 0:
            break
        cap = min(MAX_FILE_BYTES, remaining)
        try:
            text = _read_text_file(path, max_bytes=cap)
        except TextExtractError as exc:
            snippets.append(
                {
                    "name": row["name"],
                    "path": row["path"],
                    "content": f"[无法解析 {row['name']}: {exc}]",
                    "truncated": False,
                }
            )
            continue
        truncated = path.stat().st_size > cap
        total += len(text.encode("utf-8", errors="replace"))
        snippets.append(
            {
                "name": row["name"],
                "path": row["path"],
                "content": text,
                "truncated": truncated,
            }
        )
    return snippets


async def read_attachment_text(
    db: aiosqlite.Connection,
    session_id: str,
    path: str,
    max_bytes: int = MAX_FILE_BYTES,
) -> dict:
    ok, resolved = is_under_session(session_id, path)
    if not ok or not resolved:
        from app.fs.whitelist import WhitelistError

        raise WhitelistError(f"path not in session attachments: {path}")
    target = Path(resolved)
    if not target.is_file():
        from app.fs.whitelist import WhitelistError

        raise WhitelistError("not a file")
    return {"path": str(target), "content": _read_text_file(target, max_bytes=max_bytes)}


async def list_attachment_dir(
    db: aiosqlite.Connection,
    session_id: str,
    path: str,
) -> list[dict]:
    ok, resolved = is_under_session(session_id, path)
    if not ok or not resolved:
        from app.fs.whitelist import WhitelistError

        raise WhitelistError(f"path not in session attachments: {path}")
    target = Path(resolved)
    if not target.is_dir():
        from app.fs.whitelist import WhitelistError

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


def delete_session_files(session_id: str) -> None:
    """删除会话附件目录（数据库 CASCADE 后清理磁盘）。"""
    root = settings.data_dir / "session_attachments" / session_id
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
