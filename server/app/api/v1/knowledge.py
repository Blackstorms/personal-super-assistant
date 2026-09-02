"""资料库 API：两级结构——先建知识库，再在库内添加文件/文件夹。"""

from __future__ import annotations

import base64
import shutil
import uuid
from pathlib import Path

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import require_token
from app.db.database import utc_now
from app.db.deps import db_dep
from app.knowledge.indexer import TEXT_EXTS, reindex_source
from app.knowledge.text_extract import BINARY_DOC_EXTS, INDEXABLE_EXTS

router = APIRouter(dependencies=[Depends(require_token)])

MAX_TEXT_PREVIEW_BYTES = 512_000
MAX_PDF_PREVIEW_BYTES = 10_000_000


def _is_viewable_suffix(suffix: str) -> bool:
    return suffix in TEXT_EXTS or suffix in BINARY_DOC_EXTS


class BaseIn(BaseModel):
    name: str
    description: str | None = None
    workspace_id: str | None = None


class BasePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    workspace_id: str | None = None


class DocumentContentPatch(BaseModel):
    content: str


class AddItemsIn(BaseModel):
    """向已有知识库追加本地文件/文件夹（复制进库目录后重建索引）。"""

    paths: list[str] | None = None
    files: list["UploadFileIn"] | None = None


class UploadFileIn(BaseModel):
    name: str
    content: str
    encoding: str = "utf-8"  # utf-8 | base64


class LinkPathIn(BaseModel):
    """在知识库下挂载白名单目录（不复制，建索引源）。"""

    path: str
    name: str | None = None


class SearchBody(BaseModel):
    workspace_id: str | None = None
    knowledge_ids: list[str] | None = None  # 知识库 id（= 主 source id）
    query: str
    top_k: int = 5


def _safe_name(name: str) -> str:
    base = Path(name).name or "file"
    return base.replace("/", "_").replace("\\", "_")[:200]


def _unique_target(dest: Path, name: str) -> Path:
    target = dest / _safe_name(name)
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    n = 1
    while target.exists():
        target = dest / f"{stem}_{n}{suffix}"
        n += 1
    return target


async def _copy_paths_into_base(dest: Path, paths: list[str]) -> list[str]:
    copied: list[str] = []
    errors: list[str] = []
    for p in paths:
        src = Path(p).expanduser().resolve()
        if not src.exists():
            errors.append(f"路径不存在: {p}")
            continue
        target = dest / src.name
        if target.exists():
            stem, suffix = src.stem, src.suffix if src.is_file() else ""
            n = 1
            while target.exists():
                target = dest / (f"{stem}_{n}{suffix}" if src.is_file() else f"{src.name}_{n}")
                n += 1
        try:
            if src.is_dir():
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
            copied.append(str(target))
        except OSError as e:
            errors.append(f"{src.name}: {e}")
    if not copied and errors:
        raise ValueError("；".join(errors[:5]))
    return copied


def _write_upload_files(dest: Path, files: list[UploadFileIn]) -> list[str]:
    """写入上传文件；同名文件覆盖，避免重复上传产生 _1/_2 副本。"""
    saved: list[str] = []
    for f in files:
        target = dest / _safe_name(f.name)
        if f.encoding == "base64":
            target.write_bytes(base64.b64decode(f.content))
        else:
            target.write_text(f.content, encoding="utf-8")
        saved.append(str(target))
    return saved


def _base_dict(r: aiosqlite.Row) -> dict:
    return {
        "id": r["id"],
        "workspace_id": r["workspace_id"],
        "name": r["name"],
        "description": r["description"],
        "root_path": r["root_path"],
        "doc_count": r["doc_count"],
        "state": r["state"],
        "last_error": r["last_error"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _source_dict(r: aiosqlite.Row) -> dict:
    return {
        "id": r["id"],
        "base_id": r["base_id"] if "base_id" in r.keys() else None,
        "workspace_id": r["workspace_id"],
        "name": r["name"] if "name" in r.keys() else None,
        "path": r["path"],
        "source_type": r["source_type"] if "source_type" in r.keys() else "path",
        "state": r["state"],
        "doc_count": r["doc_count"],
        "last_error": r["last_error"],
        "updated_at": r["updated_at"],
    }


async def _get_base(db: aiosqlite.Connection, base_id: str) -> aiosqlite.Row:
    cur = await db.execute("SELECT * FROM knowledge_bases WHERE id=?", (base_id,))
    r = await cur.fetchone()
    if not r:
        raise HTTPException(404, detail={"code": "not_found", "message": "knowledge base not found"})
    return r


async def _sync_base_stats(db: aiosqlite.Connection, base_id: str) -> None:
    cur = await db.execute(
        "SELECT COALESCE(SUM(doc_count), 0) AS c, MAX(state) AS st FROM knowledge_sources WHERE base_id=?",
        (base_id,),
    )
    row = await cur.fetchone()
    await db.execute(
        "UPDATE knowledge_bases SET doc_count=?, state=?, updated_at=? WHERE id=?",
        (row["c"] or 0, row["st"] or "idle", utc_now(), base_id),
    )


PATH_DOC_PREFIX = "path:"


def _path_doc_id(path: str) -> str:
    return PATH_DOC_PREFIX + uuid.uuid5(uuid.NAMESPACE_URL, path).hex


def _resolve_path_doc_id(root: Path, doc_id: str) -> Path | None:
    if not doc_id.startswith(PATH_DOC_PREFIX):
        return None
    target = doc_id[len(PATH_DOC_PREFIX) :]
    if not root.exists():
        return None
    for fp in root.rglob("*"):
        if not fp.is_file():
            continue
        if uuid.uuid5(uuid.NAMESPACE_URL, str(fp.resolve())).hex == target:
            return fp
    return None


def _index_status_label(path: Path, searchable: bool) -> str:
    if searchable:
        return "indexed"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf_empty"
    if suffix == ".docx":
        return "docx_empty"
    if suffix in INDEXABLE_EXTS:
        return "empty"
    return "unsupported"


async def _build_document_items(db: aiosqlite.Connection, base_id: str) -> list[dict]:
    """合并 DB 索引记录与磁盘实际文件，确保刚上传的文件也会出现在列表中。"""
    base = await _get_base(db, base_id)
    base_root = Path(base["root_path"]).resolve()
    cur = await db.execute(
        """
        SELECT d.id, d.path, d.indexed_at, d.content_hash, s.name AS source_name, s.source_type
        FROM knowledge_documents d
        JOIN knowledge_sources s ON s.id = d.source_id
        WHERE s.base_id = ?
        ORDER BY d.indexed_at DESC
        """,
        (base_id,),
    )
    db_rows = await cur.fetchall()
    db_by_path: dict[str, aiosqlite.Row] = {}
    for r in db_rows:
        db_by_path[str(Path(r["path"]).resolve())] = r

    items: list[dict] = []
    seen: set[str] = set()

    src_cur = await db.execute(
        "SELECT id, path, source_type, name FROM knowledge_sources WHERE base_id=?",
        (base_id,),
    )
    for src in await src_cur.fetchall():
        root = Path(src["path"]).expanduser().resolve()
        if not root.exists():
            continue
        file_paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for fp in file_paths:
            ps = str(fp.resolve())
            if ps in seen:
                continue
            seen.add(ps)
            suffix = fp.suffix.lower()
            row = db_by_path.get(ps)
            if row:
                chunk_cur = await db.execute(
                    "SELECT COUNT(*) AS c FROM knowledge_chunks WHERE document_id=?",
                    (row["id"],),
                )
                chunk_row = await chunk_cur.fetchone()
                chunk_count = int(chunk_row["c"] or 0) if chunk_row else 0
                searchable = chunk_count > 0
                editable = (
                    src["source_type"] == "upload"
                    and fp.exists()
                    and suffix in TEXT_EXTS
                    and str(fp.resolve()).startswith(str(base_root))
                )
                items.append(
                    {
                        "id": row["id"],
                        "name": fp.name,
                        "path": ps,
                        "indexed_at": row["indexed_at"],
                        "source_name": row["source_name"],
                        "source_type": row["source_type"],
                        "viewable": fp.exists() and _is_viewable_suffix(suffix),
                        "editable": editable,
                        "searchable": searchable,
                        "index_status": _index_status_label(fp, searchable),
                    }
                )
            else:
                editable = (
                    src["source_type"] == "upload"
                    and suffix in TEXT_EXTS
                    and str(fp.resolve()).startswith(str(base_root))
                )
                items.append(
                    {
                        "id": _path_doc_id(ps),
                        "name": fp.name,
                        "path": ps,
                        "indexed_at": None,
                        "source_name": src["name"],
                        "source_type": src["source_type"],
                        "viewable": _is_viewable_suffix(suffix),
                        "editable": editable,
                        "searchable": False,
                        "index_status": "pending",
                    }
                )

    for ps, row in db_by_path.items():
        if ps in seen:
            continue
        p = Path(ps)
        chunk_cur = await db.execute(
            "SELECT COUNT(*) AS c FROM knowledge_chunks WHERE document_id=?",
            (row["id"],),
        )
        chunk_row = await chunk_cur.fetchone()
        chunk_count = int(chunk_row["c"] or 0) if chunk_row else 0
        searchable = chunk_count > 0
        suffix = p.suffix.lower()
        editable = (
            row["source_type"] == "upload"
            and p.exists()
            and p.is_file()
            and suffix in TEXT_EXTS
            and str(p.resolve()).startswith(str(base_root))
        )
        items.append(
            {
                "id": row["id"],
                "name": p.name,
                "path": ps,
                "indexed_at": row["indexed_at"],
                "source_name": row["source_name"],
                "source_type": row["source_type"],
                "viewable": p.exists() and p.is_file() and _is_viewable_suffix(suffix),
                "editable": editable,
                "searchable": searchable,
                "index_status": _index_status_label(p, searchable) if p.exists() else "missing",
            }
        )

    items.sort(key=lambda x: (x.get("indexed_at") or "", x.get("name") or ""), reverse=True)
    return items


# —— 知识库（一级）——


@router.get("/bases")
async def list_bases(workspace_id: str | None = None, db: aiosqlite.Connection = Depends(db_dep)):
    if workspace_id:
        cur = await db.execute(
            """
            SELECT * FROM knowledge_bases
            WHERE workspace_id=? OR workspace_id IS NULL
            ORDER BY updated_at DESC
            """,
            (workspace_id,),
        )
    else:
        cur = await db.execute("SELECT * FROM knowledge_bases ORDER BY updated_at DESC")
    return {"items": [_base_dict(r) for r in await cur.fetchall()]}


@router.post("/bases")
async def create_base(body: BaseIn, db: aiosqlite.Connection = Depends(db_dep)):
    """创建空知识库：落盘目录 + 主索引源（id 与 base 相同，便于对话引用）。"""
    bid = str(uuid.uuid4())
    now = utc_now()
    root = settings.data_dir / "knowledge" / "bases" / bid
    root.mkdir(parents=True, exist_ok=True)
    name = (body.name or "").strip() or "未命名知识库"
    await db.execute(
        """
        INSERT INTO knowledge_bases(
          id, workspace_id, name, description, root_path, doc_count, state, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (bid, body.workspace_id, name, body.description, str(root), 0, "idle", now, now),
    )
    await db.execute(
        """
        INSERT INTO knowledge_sources(
          id, base_id, workspace_id, name, path, source_type, state, doc_count, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (bid, bid, body.workspace_id, name, str(root), "upload", "idle", 0, now),
    )
    await db.commit()
    return await get_base(bid, db)


@router.get("/bases/{base_id}")
async def get_base(base_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    return _base_dict(await _get_base(db, base_id))


@router.patch("/bases/{base_id}")
async def patch_base(base_id: str, body: BasePatch, db: aiosqlite.Connection = Depends(db_dep)):
    r = await _get_base(db, base_id)
    name = body.name if body.name is not None else r["name"]
    description = body.description if body.description is not None else r["description"]
    workspace_id = body.workspace_id if body.workspace_id is not None else r["workspace_id"]
    await db.execute(
        "UPDATE knowledge_bases SET name=?, description=?, workspace_id=?, updated_at=? WHERE id=?",
        (name, description, workspace_id, utc_now(), base_id),
    )
    await db.execute(
        "UPDATE knowledge_sources SET name=?, workspace_id=?, updated_at=? WHERE id=?",
        (name, workspace_id, utc_now(), base_id),
    )
    await db.commit()
    return await get_base(base_id, db)


@router.delete("/bases/{base_id}")
async def delete_base(base_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    r = await _get_base(db, base_id)
    await db.execute("DELETE FROM knowledge_sources WHERE base_id=?", (base_id,))
    await db.execute("DELETE FROM knowledge_bases WHERE id=?", (base_id,))
    await db.commit()
    root = Path(r["root_path"])
    knowledge_root = (settings.data_dir / "knowledge").resolve()
    try:
        if str(root.resolve()).startswith(str(knowledge_root)) and root.exists():
            shutil.rmtree(root, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


@router.get("/bases/{base_id}/documents")
async def list_documents(base_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    items = await _build_document_items(db, base_id)
    return {"items": items, "total": len(items)}


@router.get("/bases/{base_id}/documents/{document_id}/content")
async def get_document_content(base_id: str, document_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    """读取库内文档内容（供前端预览）。"""
    p = await _resolve_document_path(db, base_id, document_id)
    suffix = p.suffix.lower()
    if not _is_viewable_suffix(suffix):
        raise HTTPException(
            415,
            detail={"code": "not_viewable", "message": f"暂不支持预览 {suffix or '此类型'} 文件"},
        )
    size = p.stat().st_size
    if suffix == ".pdf":
        if size > MAX_PDF_PREVIEW_BYTES:
            raise HTTPException(413, detail={"code": "too_large", "message": "PDF 过大，暂不支持在线预览（上限 10MB）"})
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return {
            "id": document_id,
            "name": p.name,
            "path": str(p),
            "content": data,
            "encoding": "base64",
            "mime_type": "application/pdf",
        }
    if size > MAX_TEXT_PREVIEW_BYTES:
        raise HTTPException(413, detail={"code": "too_large", "message": "文件过大，暂不支持在线预览"})
    text = p.read_text(encoding="utf-8", errors="replace")
    return {
        "id": document_id,
        "name": p.name,
        "path": str(p),
        "content": text,
        "encoding": "utf-8",
        "mime_type": "text/plain",
    }


async def _resolve_document_path(db: aiosqlite.Connection, base_id: str, document_id: str) -> Path:
    """解析文档磁盘路径（支持 DB 记录与 path: 临时 id）。"""
    base = await _get_base(db, base_id)
    root = Path(base["root_path"]).resolve()

    if document_id.startswith(PATH_DOC_PREFIX):
        fp = _resolve_path_doc_id(root, document_id)
        if not fp or not fp.exists() or not fp.is_file():
            raise HTTPException(404, detail={"code": "not_found", "message": "document not found"})
        return fp

    cur = await db.execute(
        """
        SELECT d.id, d.path, s.base_id
        FROM knowledge_documents d
        JOIN knowledge_sources s ON s.id = d.source_id
        WHERE d.id=? AND s.base_id=?
        """,
        (document_id, base_id),
    )
    doc = await cur.fetchone()
    if not doc:
        raise HTTPException(404, detail={"code": "not_found", "message": "document not found"})
    p = Path(doc["path"])
    if not p.exists() or not p.is_file():
        raise HTTPException(404, detail={"code": "not_found", "message": "file missing on disk"})
    return p


async def _resolve_editable_document_path(
    db: aiosqlite.Connection, base_id: str, document_id: str
) -> tuple[Path, str | None]:
    """返回可编辑文件路径及所属 source_id；挂载外部文件不可编辑。"""
    base = await _get_base(db, base_id)
    root = Path(base["root_path"]).resolve()

    if document_id.startswith(PATH_DOC_PREFIX):
        fp = _resolve_path_doc_id(root, document_id)
        if not fp or not fp.exists() or not fp.is_file():
            raise HTTPException(404, detail={"code": "not_found", "message": "document not found"})
        if not str(fp.resolve()).startswith(str(root)):
            raise HTTPException(
                403, detail={"code": "read_only", "message": "挂载的外部文件不可编辑"}
            )
        cur = await db.execute(
            "SELECT id FROM knowledge_sources WHERE base_id=? AND source_type='upload' LIMIT 1",
            (base_id,),
        )
        src = await cur.fetchone()
        return fp, src["id"] if src else base_id

    cur = await db.execute(
        """
        SELECT d.id, d.path, s.base_id, s.id AS source_id, s.source_type
        FROM knowledge_documents d
        JOIN knowledge_sources s ON s.id = d.source_id
        WHERE d.id=? AND s.base_id=?
        """,
        (document_id, base_id),
    )
    doc = await cur.fetchone()
    if not doc:
        raise HTTPException(404, detail={"code": "not_found", "message": "document not found"})
    if doc["source_type"] != "upload":
        raise HTTPException(
            403, detail={"code": "read_only", "message": "挂载的外部文件不可编辑"}
        )
    p = Path(doc["path"])
    if not p.exists() or not p.is_file():
        raise HTTPException(404, detail={"code": "not_found", "message": "file missing on disk"})
    if not str(p.resolve()).startswith(str(root)):
        raise HTTPException(
            403, detail={"code": "read_only", "message": "该文件不在知识库目录内，不可编辑"}
        )
    return p, doc["source_id"]


@router.patch("/bases/{base_id}/documents/{document_id}/content")
async def patch_document_content(
    base_id: str,
    document_id: str,
    body: DocumentContentPatch,
    db: aiosqlite.Connection = Depends(db_dep),
):
    """保存库内文本文件内容并重建索引。"""
    p, source_id = await _resolve_editable_document_path(db, base_id, document_id)
    suffix = p.suffix.lower()
    if suffix not in TEXT_EXTS:
        raise HTTPException(
            415,
            detail={"code": "not_editable", "message": f"暂不支持编辑 {suffix or '此类型'} 文件"},
        )
    encoded = body.content.encode("utf-8")
    if len(encoded) > 512_000:
        raise HTTPException(413, detail={"code": "too_large", "message": "文件过大，暂不支持在线编辑"})
    p.write_text(body.content, encoding="utf-8")
    if not source_id:
        raise HTTPException(500, detail={"code": "internal", "message": "source not found"})
    try:
        await reindex_source(db, source_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, detail={"code": "reindex_failed", "message": str(e)}) from e
    await _sync_base_stats(db, base_id)
    await db.commit()
    return {
        "ok": True,
        "id": document_id,
        "name": p.name,
        "content": body.content,
        "encoding": "utf-8",
    }


@router.post("/bases/{base_id}/items")
async def add_items(base_id: str, body: AddItemsIn, db: aiosqlite.Connection = Depends(db_dep)):
    """二级：向知识库添加文件或文件夹（本地路径或上传内容）。"""
    base = await _get_base(db, base_id)
    if not body.paths and not body.files:
        raise HTTPException(400, detail={"code": "empty", "message": "paths or files required"})
    dest = Path(base["root_path"])
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    if body.paths:
        try:
            copied.extend(await _copy_paths_into_base(dest, body.paths))
        except ValueError as e:
            raise HTTPException(400, detail={"code": "copy_failed", "message": str(e)}) from e
    if body.files:
        copied.extend(_write_upload_files(dest, body.files))
    if not copied:
        raise HTTPException(400, detail={"code": "empty", "message": "no valid paths or files"})
    try:
        result = await reindex_source(db, base_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, detail={"code": "reindex_failed", "message": str(e)}) from e
    await _sync_base_stats(db, base_id)
    await db.commit()
    documents = await _build_document_items(db, base_id)
    return {
        "ok": True,
        "copied": copied,
        "reindex": result,
        "base": await get_base(base_id, db),
        "documents": documents,
    }


@router.post("/bases/{base_id}/link-path")
async def link_path(base_id: str, body: LinkPathIn, db: aiosqlite.Connection = Depends(db_dep)):
    """二级：在知识库下挂载白名单目录（额外 source）。"""
    base = await _get_base(db, base_id)
    sid = str(uuid.uuid4())
    now = utc_now()
    await db.execute(
        """
        INSERT INTO knowledge_sources(
          id, base_id, workspace_id, name, path, source_type, state, doc_count, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            sid,
            base_id,
            base["workspace_id"],
            body.name or Path(body.path).name,
            body.path,
            "path",
            "idle",
            0,
            now,
        ),
    )
    await db.commit()
    try:
        result = await reindex_source(db, sid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, detail={"code": "reindex_failed", "message": str(e)}) from e
    await _sync_base_stats(db, base_id)
    await db.commit()
    return {"ok": True, "source_id": sid, "reindex": result, "base": await get_base(base_id, db)}


@router.post("/bases/{base_id}/reindex")
async def reindex_base(base_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    await _get_base(db, base_id)
    cur = await db.execute("SELECT id FROM knowledge_sources WHERE base_id=?", (base_id,))
    sources = await cur.fetchall()
    results = []
    for s in sources:
        try:
            results.append(await reindex_source(db, s["id"]))
        except Exception as e:  # noqa: BLE001
            results.append({"source_id": s["id"], "error": str(e)})
    await _sync_base_stats(db, base_id)
    await db.commit()
    return {"ok": True, "results": results, "base": await get_base(base_id, db)}


@router.delete("/bases/{base_id}/documents/{document_id}")
async def delete_document(base_id: str, document_id: str, db: aiosqlite.Connection = Depends(db_dep)):
    base = await _get_base(db, base_id)
    root = Path(base["root_path"]).resolve()
    if document_id.startswith(PATH_DOC_PREFIX):
        fp = _resolve_path_doc_id(root, document_id)
        if fp and fp.exists() and fp.is_file():
            fp.unlink(missing_ok=True)
        try:
            await reindex_source(db, base_id)
        except Exception:  # noqa: BLE001
            pass
        await _sync_base_stats(db, base_id)
        await db.commit()
        return {"ok": True}
    cur = await db.execute(
        """
        SELECT d.id, d.path, d.source_id, s.source_type
        FROM knowledge_documents d
        JOIN knowledge_sources s ON s.id = d.source_id
        WHERE d.id=? AND s.base_id=?
        """,
        (document_id, base_id),
    )
    doc = await cur.fetchone()
    if not doc:
        raise HTTPException(404, detail={"code": "not_found", "message": "document not found"})
    await db.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,))
    await db.execute("DELETE FROM knowledge_documents WHERE id=?", (document_id,))
    await db.commit()
    # 仅删除落在本库目录内的文件
    try:
        p = Path(doc["path"])
        root = Path(base["root_path"]).resolve()
        if str(p.resolve()).startswith(str(root)) and p.exists() and p.is_file():
            p.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        await reindex_source(db, doc["source_id"])
    except Exception:  # noqa: BLE001
        pass
    await _sync_base_stats(db, base_id)
    await db.commit()
    return {"ok": True}


# —— 兼容旧 sources 接口（列表按 base 聚合）——


@router.get("/sources")
async def list_sources(workspace_id: str | None = None, db: aiosqlite.Connection = Depends(db_dep)):
    """兼容：返回知识库列表（每库主 source），供对话/专家下拉选用。"""
    return await list_bases(workspace_id, db)


@router.post("/search")
async def search(body: SearchBody, db: aiosqlite.Connection = Depends(db_dep)):
    q = body.query.replace('"', "")
    try:
        if body.knowledge_ids:
            placeholders = ",".join("?" * len(body.knowledge_ids))
            # knowledge_ids 为知识库 id：匹配主 source id 或 base_id
            cur = await db.execute(
                f"""
                SELECT c.content, d.path
                FROM knowledge_chunks_fts f
                JOIN knowledge_chunks c ON c.rowid=f.rowid
                JOIN knowledge_documents d ON d.id=c.document_id
                JOIN knowledge_sources s ON s.id=d.source_id
                WHERE (s.id IN ({placeholders}) OR s.base_id IN ({placeholders}))
                  AND knowledge_chunks_fts MATCH ?
                LIMIT ?
                """,
                (*body.knowledge_ids, *body.knowledge_ids, q, body.top_k),
            )
        elif body.workspace_id:
            cur = await db.execute(
                """
                SELECT c.content, d.path
                FROM knowledge_chunks_fts f
                JOIN knowledge_chunks c ON c.rowid=f.rowid
                JOIN knowledge_documents d ON d.id=c.document_id
                JOIN knowledge_sources s ON s.id=d.source_id
                JOIN knowledge_bases b ON b.id = s.base_id
                WHERE b.workspace_id=? AND knowledge_chunks_fts MATCH ?
                LIMIT ?
                """,
                (body.workspace_id, q, body.top_k),
            )
        else:
            cur = await db.execute(
                """
                SELECT c.content, d.path
                FROM knowledge_chunks_fts f
                JOIN knowledge_chunks c ON c.rowid=f.rowid
                JOIN knowledge_documents d ON d.id=c.document_id
                WHERE knowledge_chunks_fts MATCH ?
                LIMIT ?
                """,
                (q, body.top_k),
            )
        rows = await cur.fetchall()
    except Exception:  # noqa: BLE001
        like = f"%{body.query}%"
        cur = await db.execute(
            """
            SELECT c.content, d.path FROM knowledge_chunks c
            JOIN knowledge_documents d ON d.id=c.document_id
            WHERE c.content LIKE ?
            LIMIT ?
            """,
            (like, body.top_k),
        )
        rows = await cur.fetchall()
    return {
        "items": [{"path": r["path"], "snippet": r["content"][:300], "score": 1.0} for r in rows]
    }
