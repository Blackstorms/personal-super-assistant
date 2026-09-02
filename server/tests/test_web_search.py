"""联网搜索内置工具：provider 解析、DDG/Bing/Tavily 分发、工具面注册。"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

_TMP = str(Path(__file__).resolve().parent / ".testdata" / "web_search")
Path(_TMP).mkdir(parents=True, exist_ok=True)
os.environ["PSA_DATA_DIR"] = _TMP


def test_resolve_provider_auto_and_explicit(monkeypatch):
    from app.agent.web_search import resolve_provider

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("PSA_WEB_SEARCH_API_KEY", raising=False)
    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "auto")
    assert resolve_provider() == "auto"

    monkeypatch.setenv("PSA_WEB_SEARCH_API_KEY", "test-key")
    assert resolve_provider() == "api"

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "ddg")
    assert resolve_provider() == "ddg"

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "api")
    assert resolve_provider() == "api"

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "tavily")
    assert resolve_provider() == "tavily"


@pytest.mark.asyncio
async def test_handle_web_search_api_mocked(monkeypatch):
    from app.agent import web_search as ws

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "api")
    monkeypatch.setenv("PSA_WEB_SEARCH_API_KEY", "test-key")

    with patch.object(
        ws,
        "_api_search",
        return_value=[{"title": "API Hit", "url": "https://api.example", "content": "body"}],
    ):
        out = await ws.handle_web_search({"query": "news"})

    assert out["provider"] == "api"
    assert out["results"][0]["title"] == "API Hit"


def test_api_search_parses_syncotech_payload(monkeypatch):
    from app.agent import web_search as ws

    monkeypatch.setenv("PSA_WEB_SEARCH_API_KEY", "k")
    monkeypatch.setenv("PSA_WEB_SEARCH_API_URL", "https://example.test/search")

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": 0,
                "data": {
                    "webPageList": [
                        {
                            "title": "标题",
                            "url": "https://news.example/a",
                            "content": "摘要",
                            "hostname": "示例站",
                            "publishedDate": "2026-09-01",
                        }
                    ]
                },
            }

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            assert url.endswith("/search")
            assert headers["Authorization"] == "k"
            assert json == [{"queyContext": "q"}]
            return FakeResp()

    with patch.object(ws, "_http_client", return_value=FakeClient()):
        rows = ws._api_search("q", 5)

    assert len(rows) == 1
    assert rows[0]["url"] == "https://news.example/a"
    assert "摘要" in rows[0]["content"]
    assert "示例站" in rows[0]["content"]


@pytest.mark.asyncio
async def test_handle_web_search_empty_query():
    from app.agent.web_search import handle_web_search

    out = await handle_web_search({"query": "  "})
    assert out["error"]
    assert out["results"] == []


@pytest.mark.asyncio
async def test_handle_web_search_ddg_mocked(monkeypatch):
    from app.agent import web_search as ws

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "ddg")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with patch.object(
        ws,
        "_ddg_search",
        return_value=[{"title": "Hello", "url": "https://example.com", "content": "world"}],
    ):
        out = await ws.handle_web_search({"query": "hello", "max_results": 3})

    assert out["provider"] == "ddg"
    assert out["total_results"] == 1
    assert out["results"][0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_auto_falls_back_to_bing(monkeypatch):
    from app.agent import web_search as ws

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("PSA_WEB_SEARCH_API_KEY", raising=False)

    with (
        patch.object(ws, "_ddg_search", return_value=[]),
        patch.object(
            ws,
            "_bing_html_search",
            return_value=[{"title": "Bing", "url": "https://bing.example", "content": "x"}],
        ),
    ):
        out = await ws.handle_web_search({"query": "news"})

    assert out["provider"] == "bing"
    assert out["results"][0]["title"] == "Bing"


@pytest.mark.asyncio
async def test_auto_falls_back_to_ddg_when_bing_empty(monkeypatch):
    from app.agent import web_search as ws

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("PSA_WEB_SEARCH_API_KEY", raising=False)

    with (
        patch.object(ws, "_bing_html_search", return_value=[]),
        patch.object(
            ws,
            "_ddg_search",
            return_value=[{"title": "DDG", "url": "https://ddg.example", "content": "x"}],
        ),
    ):
        out = await ws.handle_web_search({"query": "news"})

    assert out["provider"] == "ddg"


def test_persist_search_env_fills_missing(tmp_path: Path, monkeypatch):
    from app.core import env_load

    monkeypatch.setenv("PSA_WEB_SEARCH_API_KEY", "from-env")
    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "api")
    target = env_load.persist_search_env(tmp_path)
    assert target is not None
    text = target.read_text(encoding="utf-8")
    assert "PSA_WEB_SEARCH_API_KEY=from-env" in text

    monkeypatch.setenv("PSA_WEB_SEARCH_API_KEY", "newer")
    env_load.persist_search_env(tmp_path)  # 默认不覆盖
    assert "PSA_WEB_SEARCH_API_KEY=from-env" in target.read_text(encoding="utf-8")

    env_load.persist_search_env(tmp_path, overwrite=True)
    assert "PSA_WEB_SEARCH_API_KEY=newer" in target.read_text(encoding="utf-8")


def test_ddg_html_parses_results():
    from app.agent import web_search as ws

    html = """
    <html><body>
    <a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example Title</a>
    <td class="result-snippet">A short snippet about example.</td>
    <a rel="nofollow" href="https://other.test/x">Other</a>
    <td class="result-snippet">Second hit</td>
    </body></html>
    """

    class FakeResp:
        text = html

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return FakeResp()

    with patch.object(ws, "_http_client", return_value=FakeClient()):
        rows = ws._ddg_html_search("example", 5)

    assert len(rows) == 2
    assert rows[0]["url"] == "https://example.com/page"
    assert "Example Title" in rows[0]["title"]


@pytest.mark.asyncio
async def test_handle_web_search_tavily_mocked(monkeypatch):
    from app.agent import web_search as ws

    monkeypatch.setenv("PSA_WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    with patch.object(
        ws,
        "_tavily_search",
        return_value=[{"title": "Tavily Hit", "url": "https://tavily.example", "content": "snippet"}],
    ):
        out = await ws.handle_web_search({"query": "news"})

    assert out["provider"] == "tavily"
    assert out["results"][0]["title"] == "Tavily Hit"


@pytest.mark.asyncio
async def test_web_search_on_tool_surface(monkeypatch):
    import app.hermes_bridge.lifecycle as life
    from app.agent.risk import classify_risk, classify_source
    from app.agent.tool_router import build_tool_surface, dispatch
    from app.core.config import settings
    from app.db.database import get_db, init_db
    from app.skills.registry import SkillRegistry

    assert classify_risk("web_search", {"query": "x"}) == "low"
    assert classify_source("web_search") == "builtin_web"

    monkeypatch.setattr(life, "hermes_available", lambda: False)
    settings.data_dir = Path(_TMP) / "surface"
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    db = await get_db()
    try:
        reg = SkillRegistry(settings.data_dir / "skills")
        tools = await build_tool_surface(db, reg, enable_skills=False, enable_mcp=False)
        names = {((t.get("function") or {}).get("name") or "") for t in tools}
        assert "web_search" in names

        with patch(
            "app.agent.tool_router.handle_web_search",
            return_value={"provider": "ddg", "query": "q", "results": [], "total_results": 0},
        ):
            result, source, risk = await dispatch(db, reg, "web_search", {"query": "q"})
        assert source == "builtin_web"
        assert risk == "low"
        assert result["provider"] == "ddg"
    finally:
        await db.close()
