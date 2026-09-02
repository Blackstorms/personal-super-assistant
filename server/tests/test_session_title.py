"""会话标题自动生成测试。"""

from app.agent.session_title import DEFAULT_TITLES, fallback_title, sanitize_title


def test_fallback_title_first_line():
    assert fallback_title("帮我整理本周待办\n第二行") == "帮我整理本周待办"


def test_fallback_title_slash():
    assert fallback_title("/my-skill 分析代码结构") == "分析代码结构"


def test_fallback_title_long():
    title = fallback_title("a" * 40)
    assert title.endswith("…")
    assert len(title) <= 25


def test_sanitize_title():
    assert sanitize_title('  "测试标题"  ') == "测试标题"


def test_default_titles():
    assert "新任务" in DEFAULT_TITLES
    assert "新会话" in DEFAULT_TITLES
