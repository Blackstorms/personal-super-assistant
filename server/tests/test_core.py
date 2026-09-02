"""后端测试：白名单、技能匹配、清单解析、健康与设置 API。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# 测试隔离数据目录（放在仓库内，避免沙箱无法写 /tmp）
_TMP = str(Path(__file__).resolve().parent / ".testdata" / "core")
Path(_TMP).mkdir(parents=True, exist_ok=True)
os.environ["PSA_DATA_DIR"] = _TMP

from app.main import app  # noqa: E402
from app.checklists.parser import parse_checklist_items  # noqa: E402
from app.skills.registry import SkillRegistry  # noqa: E402
from app.core.config import settings  # noqa: E402

settings.data_dir = Path(_TMP)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 触发 lifespan
        async with app.router.lifespan_context(app):
            yield ac


async def _login(client: AsyncClient) -> str:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    tok = await _login(client)
    assert tok
    bad = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db_ok"] is True
    assert body["version"]


@pytest.mark.asyncio
async def test_token_and_llm_settings(client: AsyncClient):
    tok = await _login(client)
    headers = {"Authorization": f"Bearer {tok}"}
    r = await client.get("/api/v1/settings/llm", headers=headers)
    assert r.status_code == 200
    assert "api_key_masked" in r.json()
    r = await client.put(
        "/api/v1/settings/llm",
        headers=headers,
        json={"base_url": "http://127.0.0.1:9/v1", "model": "demo", "api_key": "sk-test"},
    )
    assert r.status_code == 200
    assert r.json()["api_key_masked"]  # masked, not empty
    assert "sk-test" not in r.json()["api_key_masked"]


@pytest.mark.asyncio
async def test_web_search_settings_roundtrip(client: AsyncClient):
    tok = await _login(client)
    headers = {"Authorization": f"Bearer {tok}"}
    r = await client.get("/api/v1/settings/web-search", headers=headers)
    assert r.status_code == 200
    r = await client.put(
        "/api/v1/settings/web-search",
        headers=headers,
        json={
            "provider": "api",
            "api_url": "https://example.test/search",
            "api_key": "search-secret",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "api"
    assert body["has_api_key"] is True
    assert "search-secret" not in body["api_key_masked"]
    assert os.environ.get("PSA_WEB_SEARCH_API_KEY") == "search-secret"


@pytest.mark.asyncio
async def test_whitelist_escape(client: AsyncClient, tmp_path: Path):
    tok = await _login(client)
    headers = {"Authorization": f"Bearer {tok}"}
    root = tmp_path / "safe"
    root.mkdir()
    (root / "a.txt").write_text("hello", encoding="utf-8")
    r = await client.put("/api/v1/settings/whitelist", headers=headers, json={"roots": [str(root)]})
    assert r.status_code == 200
    # 越权路径应失败
    outside = tmp_path / "other" / "x.txt"
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")
    r = await client.get("/api/v1/fs/read", headers=headers, params={"path": str(outside)})
    assert r.status_code == 403


def test_parse_checklist():
    text = """计划如下：
1. 写周报
2. 发邮件
- [ ] 更新文档
* 整理会议室
"""
    items = parse_checklist_items(text)
    assert "写周报" in items
    assert "发邮件" in items
    assert "更新文档" in items
    assert "整理会议室" in items


def test_parse_checklist_filters_non_actionable():
    text = """## 背景分析
- 项目周期较长
- 例如人力不足

## 待办
- [ ] 提交方案
- 跟进客户反馈
- 记得明天催进度

## 总结
- 整体可行
- 风险可控
"""
    items = parse_checklist_items(text)
    assert "提交方案" in items
    assert "跟进客户反馈" in items
    assert "记得明天催进度" in items
    assert "项目周期较长" not in items
    assert "例如人力不足" not in items
    assert "整体可行" not in items
    assert "风险可控" not in items


@pytest.mark.asyncio
async def test_skills_reload(client: AsyncClient):
    tok = await _login(client)
    headers = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/api/v1/skills/reload", headers=headers)
    assert r.status_code == 200
    assert r.json()["loaded"] >= 1
    r = await client.get("/api/v1/skills", headers=headers)
    assert len(r.json()["items"]) >= 1


@pytest.mark.asyncio
async def test_workspace_session(client: AsyncClient):
    tok = await _login(client)
    headers = {"Authorization": f"Bearer {tok}"}
    w = await client.post("/api/v1/workspaces", headers=headers, json={"name": "W1"})
    assert w.status_code == 200
    wid = w.json()["id"]
    s = await client.post("/api/v1/sessions", headers=headers, json={"title": "S1", "workspace_id": wid})
    assert s.status_code == 200
    summary = await client.get(f"/api/v1/workspaces/{wid}/summary", headers=headers)
    assert summary.json()["session_count"] == 1


def test_skill_match():
    reg = SkillRegistry()
    # 同步扫描磁盘（不写 DB）
    root = Path(__file__).resolve().parents[2] / "skills"
    reg.skills_dir = root
    for child in root.iterdir():
        md = child / "SKILL.md"
        if md.exists():
            meta = reg._parse_skill(child.name, md)
            if meta:
                reg._cache[meta.id] = meta
    matched = reg.match("请帮我做文件摘要")
    assert any(s.id == "file-summarize" for s, _ in matched)
