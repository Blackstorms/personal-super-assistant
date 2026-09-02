"""PSA 内置飞书 IM 工具：绑定/启用飞书连接器且填好凭证后可用。"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from app.integrations.feishu import (
    FeishuApiError,
    batch_get_user_ids,
    create_task,
    get_user_open_id,
    search_users_by_name,
    search_users_via_lark_cli,
    send_text_message,
)
from app.mcp.manager import short_server_id

FEISHU_SEND_TOOL = {
    "type": "function",
    "function": {
        "name": "feishu_send_message",
        "description": (
            "通过已配置的飞书应用向用户或群发送文本消息。"
            "receive_id 可为 open_id / chat_id / email / user_id；"
            "若省略且连接器配置了 DEFAULT_RECEIVE_ID，则发往该默认接收方。"
            "若只有姓名，先调用 feishu_lookup_user(query=姓名) 查 open_id；"
            "若只有手机号或邮箱，用 feishu_lookup_user 的 emails/mobiles。"
            "应用需具备 im:message 等权限，且机器人对目标用户/群可见。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要发送的文本内容"},
                "receive_id": {
                    "type": "string",
                    "description": "接收方 ID（open_id / chat_id / email / user_id）；可省略以使用默认接收方",
                },
                "receive_id_type": {
                    "type": "string",
                    "enum": ["open_id", "chat_id", "email", "user_id", "union_id"],
                    "description": "receive_id 类型，默认 open_id",
                },
            },
            "required": ["text"],
        },
    },
}

FEISHU_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "feishu_lookup_user",
        "description": (
            "查找飞书用户 open_id，供 feishu_send_message / feishu_create_task 使用。"
            "优先：query=姓名关键词（需 USER_ACCESS_TOKEN 或本机已登录 lark-cli）。"
            "备选：emails / mobiles（租户凭证即可）。"
            "应用需开通 contact:user:search（姓名搜索）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "按姓名/用户名关键词搜索，例如「苏潇宇」",
                },
                "emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "企业邮箱列表",
                },
                "mobiles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "手机号列表（可带国家码）",
                },
            },
        },
    },
}

FEISHU_CREATE_TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "feishu_create_task",
        "description": (
            "在飞书任务中心创建一条任务（标题、描述、截止时间、负责人/关注人）。"
            "已配置 USER_ACCESS_TOKEN 时会以当前用户身份创建，并自动将你设为负责人（出现在「我负责的」）。"
            "也可传 assignee_open_ids / assignee_name 指定他人。"
            "应用需开通 task:task:write 或 task:task:writeonly。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "任务标题（必填）"},
                "description": {"type": "string", "description": "任务描述"},
                "due": {
                    "type": "string",
                    "description": "截止时间：Unix 毫秒时间戳，或 ISO8601（如 2026-09-02T18:00:00+08:00）",
                },
                "due_is_all_day": {
                    "type": "boolean",
                    "description": "是否全天截止，默认 false",
                },
                "assignee_open_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "负责人 open_id 列表",
                },
                "follower_open_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关注人 open_id 列表",
                },
                "assignee_name": {
                    "type": "string",
                    "description": "负责人姓名；若未给 open_id，将先按姓名查找（需用户搜索能力）",
                },
            },
            "required": ["summary"],
        },
    },
}

FEISHU_TOOLS = [FEISHU_LOOKUP_TOOL, FEISHU_SEND_TOOL, FEISHU_CREATE_TASK_TOOL]
FEISHU_TOOL_NAMES = frozenset(
    {"feishu_send_message", "feishu_lookup_user", "feishu_create_task"}
)


def _extract_creds(env: dict[str, Any]) -> tuple[str, str]:
    app_id = str(env.get("APP_ID") or env.get("FEISHU_APP_ID") or "").strip()
    app_secret = str(env.get("APP_SECRET") or env.get("FEISHU_APP_SECRET") or "").strip()
    return app_id, app_secret


def _extract_user_token(env: dict[str, Any]) -> str:
    return str(
        env.get("USER_ACCESS_TOKEN")
        or env.get("FEISHU_USER_ACCESS_TOKEN")
        or env.get("LARK_USER_ACCESS_TOKEN")
        or ""
    ).strip()


def _looks_like_feishu(row: dict) -> bool:
    sid = str(row.get("id") or "")
    name = str(row.get("name") or "").lower()
    return (
        sid == "preset-mcp-feishu"
        or "feishu" in sid.lower()
        or "feishu" in name
        or "飞书" in str(row.get("name") or "")
        or "lark" in name
    )


async def load_feishu_credentials(db: aiosqlite.Connection) -> dict[str, str] | None:
    """从已启用的飞书 MCP 行读取 App 凭证。"""
    cur = await db.execute("SELECT * FROM mcp_servers WHERE enabled=1")
    rows = await cur.fetchall()
    for r in rows:
        d = dict(r)
        if not _looks_like_feishu(d):
            continue
        env = json.loads(d.get("env_json") or "{}")
        if not isinstance(env, dict):
            continue
        app_id, app_secret = _extract_creds(env)
        if app_id and app_secret:
            default_receive = str(
                env.get("DEFAULT_RECEIVE_ID")
                or env.get("FEISHU_DEFAULT_RECEIVE_ID")
                or env.get("FEISHU_DEFAULT_CHAT_ID")
                or ""
            ).strip()
            default_type = str(
                env.get("DEFAULT_RECEIVE_ID_TYPE") or env.get("FEISHU_DEFAULT_RECEIVE_ID_TYPE") or "open_id"
            ).strip() or "open_id"
            return {
                "server_id": str(d["id"]),
                "app_id": app_id,
                "app_secret": app_secret,
                "user_access_token": _extract_user_token(env),
                "default_receive_id": default_receive,
                "default_receive_id_type": default_type,
            }
    return None


def _mcp_ids_allow(mcp_ids: list[str] | None, server_id: str) -> bool:
    if mcp_ids is None:
        return True
    if not mcp_ids:
        return False
    sid8 = short_server_id(server_id)
    allowed = {str(x) for x in mcp_ids}
    if server_id in allowed or sid8 in allowed:
        return True
    for mid in allowed:
        if sid8 in mid or mid in server_id or mid in sid8:
            return True
    return False


async def feishu_tools_for_surface(
    db: aiosqlite.Connection,
    *,
    enable_mcp: bool,
    mcp_ids: list[str] | None,
) -> list[dict]:
    """启用飞书连接器且本会话允许该 MCP 时，暴露内置发消息工具。"""
    if not enable_mcp:
        return []
    creds = await load_feishu_credentials(db)
    if not creds:
        return []
    if not _mcp_ids_allow(mcp_ids, creds["server_id"]):
        return []
    return list(FEISHU_TOOLS)


def _normalize_search_users(data: dict[str, Any]) -> list[dict[str, str]]:
    users_raw = data.get("users") or data.get("items") or []
    out: list[dict[str, str]] = []
    if not isinstance(users_raw, list):
        return out
    for u in users_raw:
        if not isinstance(u, dict):
            continue
        open_id = str(u.get("open_id") or u.get("openId") or u.get("id") or "").strip()
        name = str(u.get("name") or u.get("user_name") or "").strip()
        user_id = str(u.get("user_id") or u.get("userId") or "").strip()
        if open_id or user_id:
            item = {"name": name, "open_id": open_id}
            if user_id:
                item["user_id"] = user_id
            out.append(item)
    return out


async def _lookup_by_name(creds: dict[str, str], query: str) -> dict[str, Any]:
    q = query.strip()
    user_token = creds.get("user_access_token") or ""
    errors: list[str] = []

    if user_token:
        try:
            data = await search_users_by_name(user_access_token=user_token, query=q)
            users = _normalize_search_users(data if isinstance(data, dict) else {})
            return {
                "ok": True,
                "query": q,
                "users": users,
                "source": "search_v1_user",
                "hint": "取 users[].open_id 作为 feishu_send_message 的 receive_id（receive_id_type=open_id）",
            }
        except Exception as e:  # noqa: BLE001
            errors.append(f"API: {e}")

    try:
        cli_data = await search_users_via_lark_cli(q)
        if cli_data is not None:
            users = _normalize_search_users(cli_data if isinstance(cli_data, dict) else {})
            return {
                "ok": True,
                "query": q,
                "users": users,
                "source": "lark-cli",
                "raw": cli_data,
                "hint": "取 users[].open_id 作为 feishu_send_message 的 receive_id（receive_id_type=open_id）",
            }
    except Exception as e:  # noqa: BLE001
        errors.append(f"lark-cli: {e}")

    return {
        "ok": False,
        "query": q,
        "error": (
            "按姓名搜索需要用户身份。"
            "请在飞书连接器 env 填写 USER_ACCESS_TOKEN（user_access_token），"
            "或安装并登录 lark-cli 后使用："
            f'lark-cli contact +search-user --query "{q}" --as user；'
            "同时确保应用已开通 contact:user:search。"
        ),
        "detail": errors or None,
    }


def _as_str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _parse_due_to_ms(due: str | int | float | None) -> str | None:
    if due is None:
        return None
    if isinstance(due, (int, float)):
        n = int(due)
        # 秒级时间戳 → 毫秒
        if n < 10_000_000_000:
            n *= 1000
        return str(n)
    s = str(due).strip()
    if not s:
        return None
    if s.isdigit():
        n = int(s)
        if n < 10_000_000_000:
            n *= 1000
        return str(n)
    from datetime import datetime

    try:
        # 支持 2026-09-02T18:00:00+08:00 / 2026-09-02 18:00:00
        normalized = s.replace(" ", "T", 1) if " " in s and "T" not in s else s
        dt = datetime.fromisoformat(normalized)
        return str(int(dt.timestamp() * 1000))
    except ValueError:
        return None


async def handle_feishu_tool(
    db: aiosqlite.Connection,
    name: str,
    arguments: dict[str, Any] | None,
) -> Any:
    creds = await load_feishu_credentials(db)
    if not creds:
        return {
            "ok": False,
            "error": "未找到已启用的飞书连接器凭证，请在连接器中填写 APP_ID / APP_SECRET 并启用。",
        }
    args = arguments or {}
    try:
        if name == "feishu_lookup_user":
            query = str(args.get("query") or args.get("name") or "").strip()
            emails = args.get("emails") or []
            mobiles = args.get("mobiles") or []
            if isinstance(emails, str):
                emails = [emails]
            if isinstance(mobiles, str):
                mobiles = [mobiles]
            emails = [str(x).strip() for x in emails if str(x).strip()]
            mobiles = [str(x).strip() for x in mobiles if str(x).strip()]

            if query:
                return await _lookup_by_name(creds, query)
            if not emails and not mobiles:
                return {
                    "ok": False,
                    "error": "请提供 query（姓名）或 emails/mobiles 之一。",
                }
            data = await batch_get_user_ids(
                app_id=creds["app_id"],
                app_secret=creds["app_secret"],
                emails=emails,
                mobiles=mobiles,
            )
            return {"ok": True, "data": data, "source": "batch_get_id"}
        if name == "feishu_send_message":
            text = str(args.get("text") or "").strip()
            receive_id = str(args.get("receive_id") or "").strip() or creds.get(
                "default_receive_id", ""
            )
            receive_id_type = (
                str(args.get("receive_id_type") or "").strip()
                or creds.get("default_receive_id_type")
                or "open_id"
            )
            if not text:
                return {"ok": False, "error": "text 为必填"}
            if not receive_id:
                return {
                    "ok": False,
                    "error": (
                        "缺少 receive_id。若只有姓名，请先 feishu_lookup_user(query=姓名) 获取 open_id；"
                        "或提供邮箱/手机号查询；或在连接器 env 配置 DEFAULT_RECEIVE_ID。"
                    ),
                }
            data = await send_text_message(
                app_id=creds["app_id"],
                app_secret=creds["app_secret"],
                receive_id=receive_id,
                text=text,
                receive_id_type=receive_id_type,
            )
            return {"ok": True, "data": data}
        if name == "feishu_create_task":
            summary = str(args.get("summary") or args.get("title") or "").strip()
            if not summary:
                return {"ok": False, "error": "summary（任务标题）为必填"}
            description = str(args.get("description") or "").strip() or None
            due_raw = args.get("due") or args.get("due_timestamp") or args.get("deadline")
            due_ms = _parse_due_to_ms(due_raw)
            if due_raw and not due_ms:
                return {
                    "ok": False,
                    "error": f"无法解析截止时间 due={due_raw!r}，请传毫秒时间戳或 ISO8601。",
                }
            assignees = _as_str_list(args.get("assignee_open_ids") or args.get("assignees"))
            followers = _as_str_list(args.get("follower_open_ids") or args.get("followers"))
            assignee_name = str(args.get("assignee_name") or "").strip()
            if assignee_name and not assignees:
                looked = await _lookup_by_name(creds, assignee_name)
                if not looked.get("ok"):
                    return looked
                users = looked.get("users") or []
                if not users:
                    return {
                        "ok": False,
                        "error": f"未找到名为「{assignee_name}」的飞书用户，无法指定负责人。",
                        "lookup": looked,
                    }
                if len(users) > 1:
                    return {
                        "ok": False,
                        "error": f"姓名「{assignee_name}」匹配到多人，请指定精确 open_id。",
                        "users": users,
                    }
                oid = str(users[0].get("open_id") or "").strip()
                if not oid:
                    return {"ok": False, "error": "查到用户但缺少 open_id", "users": users}
                assignees = [oid]

            user_tok = creds.get("user_access_token") or ""
            auto_assigned = False
            if not assignees and user_tok:
                self_oid = await get_user_open_id(user_tok)
                if self_oid:
                    assignees = [self_oid]
                    auto_assigned = True

            data = await create_task(
                app_id=creds["app_id"],
                app_secret=creds["app_secret"],
                summary=summary,
                description=description,
                due_timestamp_ms=due_ms,
                due_is_all_day=bool(args.get("due_is_all_day") or False),
                assignee_open_ids=assignees,
                follower_open_ids=followers,
                user_access_token=user_tok or None,
            )
            task = (data.get("task") if isinstance(data, dict) else None) or data
            task_url = (task or {}).get("url") if isinstance(task, dict) else None
            task_guid = (task or {}).get("guid") if isinstance(task, dict) else None
            hint_parts = ["已创建飞书任务"]
            if auto_assigned:
                hint_parts.append("已自动将你设为负责人，可在飞书「任务 → 我负责的」查看")
            else:
                hint_parts.append("可在飞书任务中心查看")
            if task_url:
                hint_parts.append(f"链接：{task_url}")
            return {
                "ok": True,
                "data": data,
                "task_guid": task_guid,
                "task_url": task_url,
                "assignee_auto": auto_assigned,
                "hint": "；".join(hint_parts) + "。",
            }
    except FeishuApiError as e:
        err = {
            "ok": False,
            "error": str(e),
            "code": e.code,
            "detail": e.raw,
        }
        if e.code == 99991672 or "task:task:write" in str(e.msg):
            err["hint"] = (
                "飞书应用未开通任务权限。请到开放平台 → 权限管理，申请 "
                "task:task:write 或 task:task:writeonly，管理员审批并发布版本后再试。"
            )
        return err
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": f"unknown feishu tool: {name}"}
