"""高风险确认事件参数预览：勿把大文件全文塞进 SSE。"""

from app.agent.tool_loop import preview_confirm_arguments


def test_fs_write_preview_truncates_content():
    args = {
        "path": "output/guide.html",
        "content": "<html>" + ("x" * 5000) + "</html>",
    }
    preview = preview_confirm_arguments("fs_write", args)
    assert preview["path"] == "output/guide.html"
    assert preview["content_chars"] == len(args["content"])
    assert "content" not in preview or len(str(preview.get("content", ""))) < 500
    assert len(preview["content_preview"]) < 400
    assert "共" in preview["content_preview"]


def test_preview_keeps_small_fields():
    preview = preview_confirm_arguments("schedule_task", {"name": "日常", "cron": "0 9 * * *"})
    assert preview["name"] == "日常"
    assert preview["cron"] == "0 9 * * *"
