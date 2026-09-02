"""清单标题语义生成：规则回退。"""

from __future__ import annotations

from app.checklists.parser import fallback_title_from_text, parse_checklist_items, sanitize_title


def test_fallback_from_heading():
    text = """## 本周发布准备

- [ ] 合并 PR
- [ ] 跑回归
- [ ] 写公告
"""
    items = parse_checklist_items(text)
    assert fallback_title_from_text(text, items) == "本周发布准备"


def test_fallback_from_prefix_line():
    text = """待办：客户跟进

1. 打电话确认需求
2. 发方案
"""
    items = parse_checklist_items(text)
    title = fallback_title_from_text(text, items)
    assert "客户跟进" in title


def test_fallback_from_user_intent():
    items = ["写周报", "同步进度"]
    title = fallback_title_from_text(
        "- 写周报\n- 同步进度",
        items,
        user_content="帮我整理一下本周工作待办",
    )
    assert "本周" in title or "工作" in title
    assert title != "从对话生成的清单"


def test_fallback_from_items():
    items = ["买菜", "做饭", "洗碗"]
    title = fallback_title_from_text("", items)
    assert "买菜" in title
    assert title != "从对话生成的清单"


def test_sanitize_title():
    assert sanitize_title('  「周报」  ') == "周报"
    assert len(sanitize_title("x" * 100)) <= 40
