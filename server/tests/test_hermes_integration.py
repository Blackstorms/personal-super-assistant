"""Hermes 集成：降级与工具面过滤。"""

from __future__ import annotations

import os
from pathlib import Path

_TMP = str(Path(__file__).resolve().parent / ".testdata" / "hermes_int")
Path(_TMP).mkdir(parents=True, exist_ok=True)
os.environ["PSA_DATA_DIR"] = _TMP


def test_dispatch_unavailable_when_missing(monkeypatch):
    """模拟无 vendored Hermes 时 dispatch 降级。"""
    import app.hermes_bridge.paths as paths

    monkeypatch.setattr(paths, "hermes_exists", lambda: False)
    paths._path_ready = False

    async def _run():
        from app.hermes_bridge.dispatch import dispatch_hermes_tool

        r = await dispatch_hermes_tool("skills_list", {})
        assert isinstance(r, dict)
        assert r.get("error") == "hermes_unavailable" or "error" in r

    import asyncio

    asyncio.run(_run())


def test_diagnose_missing_when_no_vendor(monkeypatch):
    import app.hermes_bridge.paths as paths

    monkeypatch.setattr(paths, "hermes_exists", lambda: False)
    paths._path_ready = False
    missing = paths.diagnose_missing_deps()
    assert "vendored_hermes" in missing


def test_filter_skill_tools_empty_set():
    from app.hermes_bridge.tool_surface import filter_skill_tools

    tools = [
        {"type": "function", "function": {"name": "skills_list"}},
        {"type": "function", "function": {"name": "fs_list"}},
    ]
    out = filter_skill_tools(tools, set())
    names = [((t.get("function") or {}).get("name")) for t in out]
    assert "skills_list" not in names
    assert "fs_list" in names
