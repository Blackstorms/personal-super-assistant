"""
工具输出与上下文预算工具函数。

对齐 deer-flow ToolOutputBudget：防止单次工具结果撑爆上下文。
"""

from __future__ import annotations

import json
from typing import Any

# 单次工具结果字符上限（约 8k）
DEFAULT_TOOL_OUTPUT_MAX = 8000


def truncate_text(text: str, max_chars: int = DEFAULT_TOOL_OUTPUT_MAX) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n...[truncated {omitted} chars]"


def truncate_tool_result(result: Any, max_chars: int = DEFAULT_TOOL_OUTPUT_MAX) -> Any:
    """将工具结果序列化后截断；若已是 dict 且含 error 则原样返回（短错误不截）。"""
    if isinstance(result, str):
        return truncate_text(result, max_chars)
    try:
        raw = json.dumps(result, ensure_ascii=False)
    except (TypeError, ValueError):
        raw = str(result)
    if len(raw) <= max_chars:
        return result
    return {
        "_truncated": True,
        "preview": truncate_text(raw, max_chars),
        "original_chars": len(raw),
    }
