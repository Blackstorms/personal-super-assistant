"""Hermes Bridge 冒烟：vendored 路径与 sys.path。"""

from __future__ import annotations

from pathlib import Path

from app.hermes_bridge.paths import ensure_hermes_on_syspath, hermes_exists, hermes_root


def test_hermes_root_is_vendored():
    """根路径必须落在仓库 third_party/hermes-agent。"""
    root = hermes_root()
    assert isinstance(root, Path)
    assert root.name == "hermes-agent"
    assert root.parent.name == "third_party"


def test_hermes_exists_or_graceful():
    assert isinstance(hermes_exists(), bool)


def test_ensure_syspath_when_present():
    if not hermes_exists():
        assert ensure_hermes_on_syspath() is False
        return
    assert ensure_hermes_on_syspath() is True
    import model_tools  # type: ignore  # noqa: F401

    assert Path(hermes_root() / "tools" / "mcp_tool.py").is_file()
