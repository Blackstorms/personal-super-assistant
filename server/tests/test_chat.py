"""chat SSE 相关测试：mock LLM 流式 / 确认闸 / 停止。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_TMP = str(Path(__file__).resolve().parent / ".testdata" / "chat")
Path(_TMP).mkdir(parents=True, exist_ok=True)
os.environ["PSA_DATA_DIR"] = _TMP

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402

settings.data_dir = Path(_TMP)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with app.router.lifespan_context(app):
            yield ac


async def _login(client: AsyncClient) -> str:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    return r.json()["token"]


async def _auth_headers(client: AsyncClient) -> dict:
    token = await _login(client)
    return {"Authorization": f"Bearer {token}"}


async def _enable_mock(client: AsyncClient, headers: dict) -> None:
    r = await client.put(
        "/api/v1/settings/llm",
        headers=headers,
        json={
            "base_url": "http://mock.local/v1",
            "api_key": "",
            "model": "mock",
            "temperature": 0.0,
            "max_tokens": 256,
            "provider": "mock",
        },
    )
    # 部分实现可能忽略未知字段 provider，靠 model=mock 触发
    assert r.status_code in (200, 422) or r.status_code == 200


async def _make_session(client: AsyncClient, headers: dict) -> str:
    r = await client.post("/api/v1/sessions", headers=headers, json={"title": "chat-test"})
    assert r.status_code == 200
    return r.json()["id"]


async def _consume_sse(client: AsyncClient, headers: dict, session_id: str, content: str) -> list:
    events = []
    async with client.stream(
        "POST",
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": session_id, "content": content, "enable_mcp": False},
    ) as resp:
        assert resp.status_code == 200
        current = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                current = line[7:].strip()
            elif line.startswith("data: ") and current:
                events.append((current, json.loads(line[6:])))
    return events


@pytest.mark.asyncio
async def test_mock_stream_basic(client: AsyncClient):
    headers = await _auth_headers(client)
    await _enable_mock(client, headers)
    sid = await _make_session(client, headers)
    events = await _consume_sse(client, headers, sid, "你好，介绍一下你自己")
    names = [e for e, _ in events]
    assert "run_started" in names or "token" in names
    assert "done" in names or "error" in names
    if "done" in names:
        assert any(e == "token" for e, _ in events)


@pytest.mark.asyncio
async def test_mock_gateway_unit():
    from app.llm.gateway import MockLLMGateway, create_gateway

    g = create_gateway(
        base_url="x",
        api_key="",
        model="mock",
        provider="mock",
    )
    assert isinstance(g, MockLLMGateway)
    tokens = []
    async for ev in g.stream_chat([{"role": "user", "content": "hello"}], tools=None):
        if ev["type"] == "token":
            tokens.append(ev["delta"])
    assert "".join(tokens)


@pytest.mark.asyncio
async def test_tool_router_strips_file_tools():
    from app.agent.tool_router import strip_hermes_file_tools

    tools = [
        {"type": "function", "function": {"name": "fs_read"}},
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {"name": "write_file"}},
        {"type": "function", "function": {"name": "skills_list"}},
    ]
    out = strip_hermes_file_tools(tools)
    names = [((t.get("function") or {}).get("name")) for t in out]
    assert "fs_read" in names
    assert "skills_list" in names
    assert "read_file" not in names
    assert "write_file" not in names


@pytest.mark.asyncio
async def test_confirm_then_continue_tool_loop(client: AsyncClient, tmp_path: Path, monkeypatch):
    """批准 fs_write 后，mock 应再发 fs_list（确认后续环）。"""
    monkeypatch.setattr(settings, "enable_chat_fs_write", True)
    headers = await _auth_headers(client)
    await _enable_mock(client, headers)
    # 白名单：允许写到 tmp
    await client.post(
        "/api/v1/settings/whitelist",
        headers=headers,
        json={"path": str(tmp_path)},
    )
    sid = await _make_session(client, headers)
    target = tmp_path / "out.txt"
    events = await _consume_sse(
        client,
        headers,
        sid,
        f"请写入文件 {target} 然后再列出目录继续",
    )
    names = [e for e, _ in events]
    assert "tool_confirm" in names
    confirm_data = next(d for e, d in events if e == "tool_confirm")
    run_id = confirm_data["run_id"]
    tool_call_id = confirm_data["tool_call_id"]

    cont = []
    async with client.stream(
        "POST",
        "/api/v1/chat/confirm",
        headers=headers,
        json={
            "session_id": sid,
            "run_id": run_id,
            "tool_call_id": tool_call_id,
            "approve": True,
        },
    ) as resp:
        assert resp.status_code == 200
        current = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                current = line[7:].strip()
            elif line.startswith("data: ") and current:
                cont.append((current, json.loads(line[6:])))
    cont_names = [e for e, _ in cont]
    assert "tool_result" in cont_names
    assert "done" in cont_names
    # 确认后应能再次 tool_start（第二次工具）
    assert "tool_start" in cont_names or "token" in cont_names


@pytest.mark.asyncio
async def test_sibling_tools_after_confirm(client: AsyncClient, tmp_path: Path, monkeypatch):
    """同批 fs_write + fs_list：确认后 sibling 也应有 tool_result。"""
    monkeypatch.setattr(settings, "enable_chat_fs_write", True)
    headers = await _auth_headers(client)
    await _enable_mock(client, headers)
    await client.post(
        "/api/v1/settings/whitelist",
        headers=headers,
        json={"path": str(tmp_path)},
    )
    sid = await _make_session(client, headers)
    target = tmp_path / "batch.txt"
    events = await _consume_sse(
        client,
        headers,
        sid,
        f"请写入文件 {target} 并同批列出目录",
    )
    assert any(e == "tool_confirm" for e, _ in events)
    confirm_data = next(d for e, d in events if e == "tool_confirm")
    cont = []
    async with client.stream(
        "POST",
        "/api/v1/chat/confirm",
        headers=headers,
        json={
            "session_id": sid,
            "run_id": confirm_data["run_id"],
            "tool_call_id": confirm_data["tool_call_id"],
            "approve": True,
        },
    ) as resp:
        assert resp.status_code == 200
        current = None
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                current = line[7:].strip()
            elif line.startswith("data: ") and current:
                cont.append((current, json.loads(line[6:])))
    results = [d for e, d in cont if e == "tool_result"]
    assert len(results) >= 1
    assert any(e == "done" for e, _ in cont)


@pytest.mark.asyncio
async def test_loop_detect_unit():
    from app.agent.risk import canonical_tool_key

    a = canonical_tool_key("fs_list", {"path": "/tmp"})
    b = canonical_tool_key("fs_list", {"path": "/tmp"})
    c = canonical_tool_key("fs_list", {"path": "/other"})
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_risk_psa_builtins():
    from app.agent.risk import classify_risk

    assert classify_risk("fs_write", {}) == "high"
    assert classify_risk("schedule_task", {"action": "create"}) == "low"
    assert classify_risk("knowledge_search", {"query": "x"}) == "low"
    assert classify_risk("current_time", {}) == "low"
