"""知识库对话旁路：绑定 KB 后可读库内路径，无需全局白名单。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.fs import knowledge_access as ka
from app.fs import whitelist as fs


@pytest.mark.asyncio
async def test_bound_knowledge_readable_without_whitelist(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("PSA_DATA_DIR", str(data))
    from app.core.config import settings
    from app.db.database import get_db, init_db, utc_now

    monkeypatch.setattr(settings, "data_dir", data)
    await init_db()
    db = await get_db()
    try:
        bid = "kb-test-1"
        root = data / "knowledge" / "bases" / bid
        root.mkdir(parents=True)
        doc = root / "notes.md"
        doc.write_text("知识库正文内容", encoding="utf-8")
        now = utc_now()
        await db.execute(
            """
            INSERT INTO knowledge_bases(
              id, workspace_id, name, description, root_path, doc_count, state, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (bid, None, "我的知识库", "", str(root), 1, "ready", now, now),
        )
        await db.execute(
            """
            INSERT INTO knowledge_sources(
              id, base_id, workspace_id, name, path, source_type, state, doc_count, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (bid, bid, None, "我的知识库", str(root), "upload", "ready", 1, now),
        )
        await db.commit()

        assert await fs.list_roots(db) == []

        roots = await ka.list_knowledge_roots(db, [bid])
        assert any(Path(r["path"]) == root.resolve() for r in roots)

        listed = await fs.list_dir_for_session(db, str(root), None, knowledge_ids=[bid])
        assert "notes.md" in {e["name"] for e in listed}

        read = await fs.read_text_for_session(db, str(doc), None, knowledge_ids=[bid])
        assert "知识库正文内容" in read["content"]

        with pytest.raises(fs.WhitelistError):
            await fs.read_text_for_session(db, str(doc), None, knowledge_ids=None)
    finally:
        await db.close()
