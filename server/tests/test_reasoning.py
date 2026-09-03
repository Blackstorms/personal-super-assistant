"""推理 SSE 提取与 think 标签拆分。"""

from __future__ import annotations

import os

from app.llm.gateway import (
    StreamThinkMux,
    ThinkTagSplitter,
    _delta_content,
    _delta_reasoning,
    should_enable_thinking,
    thinking_request_kwargs,
)


def test_delta_reasoning_attr():
    class D:
        reasoning_content = "step1"

    assert _delta_reasoning(D()) == "step1"


def test_delta_reasoning_model_extra():
    class D:
        reasoning_content = None
        model_extra = {"reasoning_content": "from-extra"}

    assert _delta_reasoning(D()) == "from-extra"


def test_delta_reasoning_dict():
    assert _delta_reasoning({"reasoning": "r"}) == "r"
    assert _delta_reasoning({}) == ""
    assert _delta_reasoning(None) == ""


def test_think_tag_splitter_streams():
    s = ThinkTagSplitter()
    parts = s.feed("你好<think>推理中")
    parts += s.feed("间</think>答案")
    parts += s.flush()
    assert ("token", "你好") in parts
    reasoning = "".join(p for k, p in parts if k == "reasoning")
    answer = "".join(p for k, p in parts if k == "token")
    assert "推理中间" in reasoning
    assert answer.endswith("答案")
    assert "<think>" not in answer


def test_think_tag_splitter_passthrough():
    s = ThinkTagSplitter()
    assert s.feed("普通回复") == [("token", "普通回复")]
    assert s.flush() == []


def test_think_tag_orphan_close():
    s = ThinkTagSplitter()
    parts = s.feed("先规划行程</think>最终攻略")
    parts += s.flush()
    reasoning = "".join(p for k, p in parts if k == "reasoning")
    answer = "".join(p for k, p in parts if k == "token")
    assert "先规划行程" in reasoning
    assert answer == "最终攻略"


def test_think_tag_holds_partial_then_opens():
    s = ThinkTagSplitter()
    assert s.feed("<") == []
    parts = s.feed("think>隐秘思考</think>可见答案")
    parts += s.flush()
    reasoning = "".join(p for k, p in parts if k == "reasoning")
    answer = "".join(p for k, p in parts if k == "token")
    assert reasoning == "隐秘思考"
    assert answer == "可见答案"


def test_mux_drops_duplicate_content_during_native_reasoning():
    mux = StreamThinkMux()
    parts = mux.feed_delta("我先规划", "我先规划")
    parts += mux.feed_delta("行程结构", "行程结构")
    parts += mux.feed_delta("", "这是正文答案")
    parts += mux.flush()
    reasoning = "".join(p for k, p in parts if k == "reasoning")
    answer = "".join(p for k, p in parts if k == "token")
    assert reasoning == "我先规划行程结构"
    assert answer == "这是正文答案"


def test_mux_keeps_short_content_chars_even_if_in_reasoning():
    """回归：单字/短帧若因「出现在思考里」被丢，正文会挖成天书。"""
    mux = StreamThinkMux()
    reasoning = (
        "用户想去北京旅游，4天，2人。关键信息：出发地、出行日期、预算档位、偏好。"
        "先简短回应并提问，例如人均 ¥300-500。"
    )
    parts = mux.feed_delta(reasoning, "")
    # 模拟流式逐字输出正文（许多字也出现在思考里）
    final = "收到！自由行完全没问题。人均 ¥300-500，喜欢松弛别赶路。"
    for ch in final:
        parts += mux.feed_delta("", ch)
    parts += mux.flush()
    answer = "".join(p for k, p in parts if k == "token")
    assert answer == final
    assert "¥300-500" in answer
    assert "自由行" in answer


def test_mux_splits_think_tags_even_after_native_reasoning():
    mux = StreamThinkMux()
    parts = mux.feed_delta("内部推理", "<think>内部推理</think>\n\n给用户的答案")
    parts += mux.flush()
    reasoning = "".join(p for k, p in parts if k == "reasoning")
    answer = "".join(p for k, p in parts if k == "token")
    assert reasoning == "内部推理"
    assert "给用户的答案" in answer
    assert "<think>" not in answer


def test_delta_content_skips_thinking_parts():
    class D:
        content = [
            {"type": "thinking", "thinking": "隐秘"},
            {"type": "text", "text": "可见"},
        ]

    assert _delta_content(D()) == "可见"
    assert _delta_reasoning(D()) == "隐秘"


def test_should_enable_thinking_auto(monkeypatch):
    monkeypatch.delenv("PSA_LLM_THINKING", raising=False)
    assert should_enable_thinking("deepseek-v4-flash") is True
    assert should_enable_thinking("gpt-4o") is False


def test_thinking_request_kwargs(monkeypatch):
    monkeypatch.setenv("PSA_LLM_THINKING", "enabled")
    monkeypatch.setenv("PSA_LLM_REASONING_EFFORT", "high")
    kw = thinking_request_kwargs("any-model")
    assert kw["reasoning_effort"] == "high"
    assert kw["extra_body"]["thinking"]["type"] == "enabled"
    monkeypatch.setenv("PSA_LLM_THINKING", "disabled")
    assert thinking_request_kwargs("deepseek-v4-flash") == {}
    # cleanup for other tests
    os.environ.pop("PSA_LLM_THINKING", None)
    os.environ.pop("PSA_LLM_REASONING_EFFORT", None)
