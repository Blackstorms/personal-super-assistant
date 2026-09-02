"""审计舱中文标签单元测试。"""

from app.audit.labels import build_audit_labels


def test_builtin_fs_read_labels():
    labels = build_audit_labels(
        name="fs_read",
        source="builtin_fs",
        confirm_status="none",
        risk="low",
        is_error=False,
        arguments={"path": "/tmp/demo.txt"},
        result={"content": "hello"},
        duration_ms=15,
    )
    assert labels["tool"]["label"] == "读取文件"
    assert labels["source"]["label"] == "内置文件工具"
    assert labels["confirm_status"]["label"] == "无需确认"
    assert labels["status"]["label"] == "成功"
    assert labels["arguments_hint"][0]["label"] == "文件路径"


def test_current_time_labels():
    labels = build_audit_labels(
        name="current_time",
        source="builtin_time",
        confirm_status="none",
        risk="low",
        is_error=False,
        arguments={"timezone": "Asia/Shanghai"},
        result={"display": "2026年9月2日 星期三 15:00:00"},
        duration_ms=2,
    )
    assert labels["tool"]["label"] == "当前时间"
    assert labels["source"]["label"] == "当前时间"
    assert labels["arguments_hint"][0]["label"] == "时区"


def test_skill_labels_with_meta():
    labels = build_audit_labels(
        name="describe_skill",
        source="skill",
        confirm_status="none",
        risk="low",
        is_error=False,
        arguments={"skill_id": "file-summarize"},
        result={"guidance": "..."},
        duration_ms=8,
        skill_meta={
            "name": "本地文件摘要",
            "description": "对白名单内文本文件做要点摘要",
        },
    )
    assert "本地文件摘要" in labels["tool"]["description"]
    assert labels["source"]["label"] == "技能系统"


def test_rejected_write_labels():
    labels = build_audit_labels(
        name="fs_write",
        source="builtin_fs",
        confirm_status="rejected",
        risk="high",
        is_error=False,
        arguments={"path": "/tmp/out.txt", "content": "x"},
        result={"cancelled": True},
        duration_ms=0,
    )
    assert labels["tool"]["label"] == "写入文件"
    assert labels["confirm_status"]["label"] == "用户已拒绝"
    assert labels["status"]["label"] == "已取消"


def test_mcp_tool_labels():
    labels = build_audit_labels(
        name="mcp__a1b2c3d4__fetch_url",
        source="mcp",
        confirm_status="none",
        risk="low",
        is_error=False,
        arguments={"url": "https://example.com"},
        result={"ok": True},
        duration_ms=120,
        mcp_server_name="网页抓取",
        mcp_tool_desc="获取指定 URL 的页面内容",
    )
    assert labels["tool"]["label"] == "MCP · fetch_url"
    assert "网页抓取" in labels["tool"]["description"]
