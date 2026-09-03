"""飞书 OAuth 辅助函数测试。"""

from __future__ import annotations

import pytest

from app.integrations.feishu_oauth import (
    feishu_oauth_callback_url,
    get_feishu_oauth_status,
    start_feishu_oauth,
)


def test_start_feishu_oauth_requires_credentials():
    with pytest.raises(ValueError, match="APP_ID"):
        import asyncio

        asyncio.run(
            start_feishu_oauth(server_id="preset-mcp-feishu", app_id="", app_secret="x")
        )


@pytest.mark.asyncio
async def test_start_feishu_oauth_builds_authorize_url():
    r = await start_feishu_oauth(
        server_id="preset-mcp-feishu",
        app_id="cli_test",
        app_secret="secret",
    )
    assert "authorize_url" in r
    assert "client_id=cli_test" in r["authorize_url"]
    assert "redirect_uri=" in r["authorize_url"]
    assert "localhost" in r["redirect_uri"]
    assert r["state"]
    assert r["redirect_uri"] in r["hint"]
    st = get_feishu_oauth_status(r["state"])
    assert st["status"] == "pending"


def test_callback_url_uses_localhost_loopback():
    url = feishu_oauth_callback_url()
    assert url.startswith("http://localhost:")
    assert url.endswith("/callback")
