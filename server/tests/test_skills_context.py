"""Skills：目录渐进注入、斜杠激活、describe_skill。"""

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


def test_catalog_not_full_body():
    reg = _load_registry()
    prompt = reg.progressive_prompt("请帮我做文件摘要")
    assert "file-summarize" in prompt
    assert "可用技能" in prompt or "可能相关的技能" in prompt
    # 渐进：目录/提示，不应把整份工作流步骤全文灌进（正文含「提炼出 3-7」）
    assert "提炼出 3-7" not in prompt


def test_describe_skill():
    reg = _load_registry()
    d = reg.describe("file-summarize")
    assert d["skill_id"] == "file-summarize"
    assert "fs_read" in d["body"] or "摘要" in d["body"]
    assert d.get("error") is None


def test_slash_activation():
    reg = _load_registry()
    act = reg.parse_slash("/file-summarize 请总结 /tmp/a.txt")
    assert act is not None
    assert act.skill_id == "file-summarize"
    assert "请总结" in act.remaining_content
    assert "slash_skill_activation" in act.reminder
    assert "提炼出" in act.reminder or "摘要" in act.reminder


def test_slash_unknown():
    reg = _load_registry()
    assert reg.parse_slash("/no-such-skill hi") is None


def test_allowed_tools_in_frontmatter():
    reg = _load_registry()
    skill = reg.get("file-summarize")
    assert skill is not None
    assert "fs_read" in skill.permissions


def test_openai_tools_include_describe():
    reg = _load_registry()
    names = [t["function"]["name"] for t in reg.to_openai_tools()]
    assert "describe_skill" in names
    assert "run_skill" in names
