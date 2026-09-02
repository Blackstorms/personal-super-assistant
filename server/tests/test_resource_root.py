"""打包态资源根路径：schema.sql 必须落在 sys._MEIPASS 下。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def test_resource_root_dev_points_at_repo():
    from app.core.config import resource_root, settings

    root = resource_root()
    assert (root / "resources" / "db" / "schema.sql").is_file()
    assert settings.schema_path.is_file()


def test_resource_root_uses_meipass(tmp_path: Path, monkeypatch):
    schema = tmp_path / "resources" / "db"
    schema.mkdir(parents=True)
    (schema / "schema.sql").write_text("-- bundled\n", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    from app.core import config as cfg

    assert cfg.resource_root() == tmp_path
    assert cfg.settings.schema_path == tmp_path / "resources" / "db" / "schema.sql"
    assert cfg.settings.schema_path.is_file()


def test_ensure_gui_path_prepends_existing_dirs(tmp_path: Path, monkeypatch):
    extra = tmp_path / "bin"
    extra.mkdir()
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr("app.core.env_load.extra_gui_path_dirs", lambda: [extra])
    from app.core.env_load import ensure_gui_path

    merged = ensure_gui_path()
    parts = merged.split(os.pathsep)
    assert str(extra) in parts
    assert parts[0] == str(extra)
