"""MCP JSON 导入解析测试。"""

import pytest

from app.mcp.import_config import parse_mcp_import


def test_parse_mcp_servers_wrapper():
    raw = {
        "mcpServers": {
            "wecom": {
                "command": "npx",
                "args": ["-y", "@china-mcp/wecom-mcp"],
                "env": {"WECOM_WEBHOOK_KEY": "abc"},
            }
        }
    }
    items = parse_mcp_import(raw)
    assert len(items) == 1
    assert items[0]["name"] == "wecom"
    assert items[0]["command"] == "npx"
    assert items[0]["env"]["WECOM_WEBHOOK_KEY"] == "abc"


def test_parse_url_transport():
    items = parse_mcp_import({"name": "remote", "url": "http://localhost:3000/sse"})
    assert items[0]["transport"] == "sse"
    assert items[0]["url"].endswith("/sse")
