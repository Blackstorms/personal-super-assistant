"""技能 ID 白名单过滤。"""

from __future__ import annotations

from pathlib import Path

from app.skills.registry import SkillRegistry


def _load_registry() -> SkillRegistry:
    reg = SkillRegistry()
    root = Path(__file__).resolve().parents[2] / "skills"
    reg.skills_dir = root
    for child in root.iterdir():
        md = child / "SKILL.md"
        if md.exists():
            meta = reg._parse_skill(child.name, md)
            if meta:
                reg._cache[meta.id] = meta
    return reg


def test_catalog_filtered_by_allowed_ids():
    reg = _load_registry()
    prompt = reg.progressive_prompt("摘要", allowed_ids={"file-summarize"})
    assert "file-summarize" in prompt
    all_ids = {s.id for s in reg.list_enabled()}
    if len(all_ids) > 1:
        others = all_ids - {"file-summarize"}
        for oid in others:
            assert f"/{oid}" not in prompt


def test_describe_rejects_outside_allowlist():
    reg = _load_registry()
    allowed = {"file-summarize"}
    ok = reg.describe("file-summarize", allowed)
    assert ok.get("error") is None
    bad = reg.describe("other-skill", allowed)
    assert bad.get("error") and "not allowed" in bad["error"]


def test_slash_respects_allowlist():
    reg = _load_registry()
    assert reg.parse_slash("/file-summarize hi", {"file-summarize"}) is not None
    assert reg.parse_slash("/file-summarize hi", set()) is None


def test_filter_openai_tools_empty_mcp_ids():
    from app.mcp.manager import MCPManager

    mgr = MCPManager()
    tools = [
        {"type": "function", "function": {"name": "mcp__abcd1234__tool", "description": "x"}},
        {"type": "function", "function": {"name": "fs_read", "description": "y"}},
    ]
    filtered = mgr.filter_openai_tools(tools, [])
    names = [t["function"]["name"] for t in filtered]
    assert names == ["fs_read"]
