"""飞书开放平台轻量客户端（发消息 / 查用户 open_id）。"""

from __future__ import annotations

import json
from typing import Any

import httpx

FEISHU_API = "https://open.feishu.cn/open-apis"
_TIMEOUT = 20.0


class FeishuApiError(RuntimeError):
    def __init__(self, code: int, msg: str, *, raw: Any = None):
        super().__init__(f"feishu api error code={code}: {msg}")
        self.code = code
        self.msg = msg
        self.raw = raw


def _parse_feishu_response(r: httpx.Response) -> dict[str, Any]:
    """解析飞书 JSON；HTTP 非 2xx 时尽量带出 code/msg，避免只剩 httpx 笼统 400。"""
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        data = {"code": r.status_code, "msg": (r.text or "")[:800]}
    if not isinstance(data, dict):
        data = {"code": r.status_code, "msg": str(data)}
    code = data.get("code")
    if r.status_code >= 400 or (code is not None and code != 0):
        msg = str(data.get("msg") or data.get("error") or r.reason_phrase or "request failed")
        # 权限类错误附带申请指引
        err_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
        helps = err_obj.get("helps") if isinstance(err_obj, dict) else None
        if helps:
            msg = f"{msg}；helps={helps}"
        raise FeishuApiError(int(code if code is not None else r.status_code), msg, raw=data)
    return data


async def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        data = _parse_feishu_response(r)
    token = (data.get("tenant_access_token") or "").strip()
    if not token:
        raise FeishuApiError(-1, "empty tenant_access_token", raw=data)
    return token


async def send_text_message(
    *,
    app_id: str,
    app_secret: str,
    receive_id: str,
    text: str,
    receive_id_type: str = "open_id",
) -> dict[str, Any]:
    token = await get_tenant_access_token(app_id, app_secret)
    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{FEISHU_API}/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        data = _parse_feishu_response(r)
    return data.get("data") or data


async def batch_get_user_ids(
    *,
    app_id: str,
    app_secret: str,
    emails: list[str] | None = None,
    mobiles: list[str] | None = None,
    user_id_type: str = "open_id",
) -> dict[str, Any]:
    token = await get_tenant_access_token(app_id, app_secret)
    body: dict[str, Any] = {}
    if emails:
        body["emails"] = emails
    if mobiles:
        body["mobiles"] = mobiles
    if not body:
        raise ValueError("emails or mobiles required")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{FEISHU_API}/contact/v3/user/batch_get_id",
            params={"user_id_type": user_id_type},
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        data = _parse_feishu_response(r)
    return data.get("data") or data


async def search_users_by_name(
    *,
    user_access_token: str,
    query: str,
    page_size: int = 20,
) -> dict[str, Any]:
    """
    按姓名关键词搜索用户（需 user_access_token + contact:user:search）。
    对应开放接口 GET /search/v1/user，与 lark-cli contact +search-user --as user 同源能力。
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("query required")
    token = (user_access_token or "").strip()
    if not token:
        raise ValueError("user_access_token required for name search")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{FEISHU_API}/search/v1/user",
            params={"query": q, "page_size": max(1, min(int(page_size or 20), 200))},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        data = _parse_feishu_response(r)
    return data.get("data") or data


async def search_users_via_lark_cli(query: str) -> dict[str, Any] | None:
    """若本机已安装并登录 lark-cli，则用 CLI 按姓名搜索（可选降级）。"""
    import asyncio
    import shutil

    q = (query or "").strip()
    if not q:
        return None
    exe = shutil.which("lark-cli")
    if not exe:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            "contact",
            "+search-user",
            "--query",
            q,
            "--as",
            "user",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=30)
    except Exception:  # noqa: BLE001
        return None
    out = (out_b or b"").decode("utf-8", errors="replace").strip()
    err = (err_b or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise FeishuApiError(
            proc.returncode or -1,
            err or out or "lark-cli search-user failed",
            raw={"stdout": out, "stderr": err},
        )
    if not out:
        return {"users": [], "source": "lark-cli"}
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        # CLI 可能输出多行文本，尽量抽取 open_id
        users = []
        name = None
        open_id = None
        for line in out.splitlines():
            s = line.strip()
            if s.startswith("ou_") or "ou_" in s:
                for part in s.replace(",", " ").split():
                    if part.startswith("ou_"):
                        open_id = part
            if "name" in s.lower() or "姓名" in s:
                name = s.split(":", 1)[-1].split("：", 1)[-1].strip() or name
        if open_id:
            users.append({"name": name or q, "open_id": open_id})
        return {"users": users, "raw_text": out, "source": "lark-cli"}
    if isinstance(parsed, dict):
        parsed = dict(parsed)
        parsed.setdefault("source", "lark-cli")
        return parsed
    if isinstance(parsed, list):
        return {"users": parsed, "source": "lark-cli"}
    return {"users": [], "raw": parsed, "source": "lark-cli"}


async def get_user_open_id(user_access_token: str) -> str:
    """通过 user_access_token 获取当前授权用户的 open_id。"""
    token = (user_access_token or "").strip()
    if not token:
        return ""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get(
            f"{FEISHU_API}/authen/v1/user_info",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = _parse_feishu_response(r)
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    return str(payload.get("open_id") or "").strip()


async def create_task(
    *,
    app_id: str,
    app_secret: str,
    summary: str,
    description: str | None = None,
    due_timestamp_ms: str | int | None = None,
    due_is_all_day: bool = False,
    assignee_open_ids: list[str] | None = None,
    follower_open_ids: list[str] | None = None,
    user_access_token: str | None = None,
    user_id_type: str = "open_id",
) -> dict[str, Any]:
    """
    创建飞书任务（task/v2/tasks）。
    优先使用 user_access_token（任务会出现在该用户任务中心）；否则用 tenant_access_token。
    需应用权限 task:task:write / task:task:writeonly。
    """
    title = (summary or "").strip()
    if not title:
        raise ValueError("summary required")
    user_tok = (user_access_token or "").strip()
    if user_tok:
        token = user_tok
    else:
        token = await get_tenant_access_token(app_id, app_secret)

    body: dict[str, Any] = {"summary": title}
    desc = (description or "").strip()
    if desc:
        body["description"] = desc
    if due_timestamp_ms is not None and str(due_timestamp_ms).strip():
        body["due"] = {
            "timestamp": str(due_timestamp_ms).strip(),
            "is_all_day": bool(due_is_all_day),
        }

    members: list[dict[str, str]] = []
    for oid in assignee_open_ids or []:
        oid = str(oid).strip()
        if oid:
            members.append({"id": oid, "type": "user", "role": "assignee"})
    for oid in follower_open_ids or []:
        oid = str(oid).strip()
        if oid:
            members.append({"id": oid, "type": "user", "role": "follower"})
    if members:
        body["members"] = members

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{FEISHU_API}/task/v2/tasks",
            params={"user_id_type": user_id_type},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=body,
        )
        data = _parse_feishu_response(r)
    return data.get("data") or data
