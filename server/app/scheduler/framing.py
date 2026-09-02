"""定时任务触发时的 prompt framing（Cherry #15574）。"""

from __future__ import annotations


def frame_scheduled_prompt(*, name: str, prompt: str) -> str:
    """将用户任务指令包装为自动化触发上下文，避免视角反转。"""
    title = (name or "Scheduled Task").strip() or "Scheduled Task"
    body = (prompt or "").strip()
    return (
        f"[Scheduled Task: {title}]\n"
        "This is an automated scheduled execution, not a live user message.\n"
        "Filesystem whitelist is not enforced for this run; use fs tools, knowledge_search, "
        "and web_search as needed.\n"
        "Execute the following instruction on behalf of the user:\n\n"
        f"{body}"
    )


def framing_preview(*, name: str, prompt: str) -> str:
    """供前端展示 framing 预览。"""
    return frame_scheduled_prompt(name=name, prompt=prompt or "（任务指令）")
