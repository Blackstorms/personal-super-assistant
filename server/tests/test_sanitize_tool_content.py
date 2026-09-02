"""sanitize_tool_round_content：工具轮 stub 不落库。"""

from app.agent.tool_loop import sanitize_tool_round_content


def test_drops_short_stub_with_long_reasoning():
    stub = "给出写的把下的 `` 文件夹试试不被我再下面先生"
    reasoning = "先规划行程结构，再搜索门票，最后写 HTML。" * 20
    assert sanitize_tool_round_content(stub, reasoning) == ""


def test_keeps_real_answer():
    content = "这是一份完整的川西六日自驾攻略，包含住宿与路线。"
    reasoning = "简要规划后直接给正文。"
    assert sanitize_tool_round_content(content, reasoning) == content
