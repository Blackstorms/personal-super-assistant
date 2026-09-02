"""专家提示清洗与语言约束。"""

from app.agent.context_builder import _LANGUAGE_HARD_RULE, _strip_yaml_frontmatter


def test_strip_yaml_frontmatter_removes_english_meta():
    raw = """---
name: travel-planner
description: "Senior travel planning expert"
---

# 旅行规划专家

你是途远。
"""
    out = _strip_yaml_frontmatter(raw)
    assert "Senior travel" not in out
    assert "旅行规划专家" in out
    assert out.strip().startswith("#")


def test_language_hard_rule_mentions_thinking_zh():
    assert "思考" in _LANGUAGE_HARD_RULE
    assert "简体中文" in _LANGUAGE_HARD_RULE
