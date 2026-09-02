"""从 Hermes 技能导入到 PSA 技能库。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import aiosqlite
import pytest

_TMP = str(Path(__file__).resolve().parent / ".testdata" / "hermes_import")
Path(_TMP).mkdir(parents=True, exist_ok=True)
os.environ["PSA_DATA_DIR"] = _TMP

from app.hermes_bridge.hub_adapter import list_hermes_catalog, resolve_hermes_skill  # noqa: E402
from app.hermes_bridge.paths import hermes_root  # noqa: E402
from app.skills.registry import SkillRegistry  # noqa: E402


def _google_meet_dir() -> Path:
    return hermes_root() / "plugins" / "google_meet"


def test_catalog_includes_plugin_skill():
    items = list_hermes_catalog()
    meet = [x for x in items if x["id"] == "google_meet" or x["name"] == "google_meet"]
    assert meet, f"expected google_meet in catalog, got {[x['id'] for x in items]}"
    assert meet[0]["identifier"].startswith("local:")
    assert meet[0]["source"] == "plugin"


def test_resolve_local_google_meet():
    src = _google_meet_dir()
    assert (src / "SKILL.md").is_file()
    resolved = resolve_hermes_skill(f"local:{src}")
    assert resolved["id"] == "google_meet"
    assert "SKILL.md" not in (resolved.get("extra_files") or {})
    assert "Join a Google Meet" in resolved["description"] or "google_meet" in resolved["content"]


def test_resolve_rejects_path_outside_hermes(tmp_path: Path):
    outside = tmp_path / "evil"
    outside.mkdir()
    (outside / "SKILL.md").write_text(
        "---\nname: evil\ndescription: x\n---\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="拒绝导入"):
        resolve_hermes_skill(f"local:{outside}")


def test_import_from_markdown_writes_skill(tmp_path: Path):
    src = _google_meet_dir()
    resolved = resolve_hermes_skill(f"local:{src}")
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    db_path = tmp_path / "t.db"
    reg = SkillRegistry(skills_dir=skills_dir)

    async def _run():
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            CREATE TABLE skills (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT,
              triggers_json TEXT,
              permissions_json TEXT,
              skill_path TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              version TEXT,
              updated_at TEXT NOT NULL
            )
            """
        )
        await db.commit()
        created = await reg.import_from_markdown(
            db,
            content=resolved["content"],
            skill_id=resolved["id"],
            extra_files=resolved.get("extra_files") or {},
        )
        await db.close()
        return created

    created = asyncio.run(_run())
    assert created.id == "google_meet"
    skill_md = skills_dir / "google_meet" / "SKILL.md"
    assert skill_md.is_file()
    text = skill_md.read_text(encoding="utf-8")
    assert "google_meet" in text
    assert "When to use" in text or "Google Meet" in text
