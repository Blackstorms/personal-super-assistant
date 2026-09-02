"""预置 MCP 连接器（约 20 个常用包，默认未启用，需用户填凭证后启用）。"""

from __future__ import annotations

import json

import aiosqlite

from app.db.database import utc_now
from app.mcp.manager import mcp_manager

# 固定 ID，重启时 INSERT OR IGNORE，不覆盖用户已改配置。
# category / description / badge / icon 供市场 UI；icon 为色值提示。
PRESET_MCPS: list[dict] = [
    # —— 办公协作 ——
    {
        "id": "preset-mcp-wecom",
        "name": "企业微信",
        "description": "发送消息、管理通讯录与应用，连接企业内部协作。",
        "category": "办公协作",
        "badge": None,
        "icon": "wecom",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@china-mcp/wecom-mcp"],
        "env": {
            "WECOM_WEBHOOK_KEY": "",
            "WECOM_CORP_ID": "",
            "WECOM_CORP_SECRET": "",
            "WECOM_AGENT_ID": "",
        },
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-feishu",
        "name": "飞书",
        "description": "官方 OpenAPI：发消息、创建任务、查群/通讯录。支持 OAuth 用户授权（USER_ACCESS_TOKEN）。",
        "category": "办公协作",
        "badge": None,
        "icon": "feishu",
        "transport": "stdio",
        "command": "npx",
        # 官方 @larksuiteoapi/lark-mcp：IM + 任务；凭证走 APP_ID/APP_SECRET
        "args": [
            "-y",
            "@larksuiteoapi/lark-mcp",
            "mcp",
            "-t",
            "preset.im.default,preset.task.default,contact.v3.user.batchGetId",
            "-l",
            "zh",
            "--oauth",
            "--token-mode",
            "user_access_token",
        ],
        "env": {
            "APP_ID": "",
            "APP_SECRET": "",
            "USER_ACCESS_TOKEN": "",
            "REFRESH_USER_ACCESS_TOKEN": "",
            "DEFAULT_RECEIVE_ID": "",
            "DEFAULT_RECEIVE_ID_TYPE": "open_id",
        },
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-qqmail",
        "name": "QQ邮箱",
        "description": "通过 IMAP/SMTP 读写 QQ 邮箱，起草与检索邮件。",
        "category": "办公协作",
        "badge": None,
        "icon": "mail",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-email"],
        "env": {
            "EMAIL_TYPE": "qq",
            "EMAIL_ADDRESS": "",
            "EMAIL_PASSWORD": "",
        },
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-slack",
        "name": "Slack",
        "description": "频道消息、搜索与工作区协作，连接团队沟通。",
        "category": "办公协作",
        "badge": None,
        "icon": "slack",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {"SLACK_BOT_TOKEN": "", "SLACK_TEAM_ID": ""},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-notion",
        "name": "Notion",
        "description": "读写 Notion 页面与数据库，沉淀知识与项目笔记。",
        "category": "办公协作",
        "badge": None,
        "icon": "notion",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server"],
        "env": {"NOTION_TOKEN": ""},
        "url": None,
        "enabled": 0,
    },
    # —— 开发者工具 ——
    {
        "id": "preset-mcp-filesystem",
        "name": "文件系统",
        "description": "在指定目录内安全读写文件，辅助本地工程操作。",
        "category": "开发者工具",
        "badge": "本地",
        "icon": "fs",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-github",
        "name": "GitHub",
        "description": "仓库、Issue、PR 与代码搜索，连接开发工作流。",
        "category": "开发者工具",
        "badge": "编程套餐",
        "icon": "github",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-git",
        "name": "Git",
        "description": "本地仓库状态、diff 与提交辅助（只读为主）。",
        "category": "开发者工具",
        "badge": None,
        "icon": "git",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-git"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-postgres",
        "name": "PostgreSQL",
        "description": "只读查询 PostgreSQL，辅助数据探查与排错。",
        "category": "开发者工具",
        "badge": None,
        "icon": "db",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
        "env": {"POSTGRES_CONNECTION_STRING": ""},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-sqlite",
        "name": "SQLite",
        "description": "查询本地 SQLite 数据库文件。",
        "category": "开发者工具",
        "badge": "本地",
        "icon": "db",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "./data.db"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-playwright",
        "name": "Playwright 浏览器",
        "description": "浏览器自动化：打开页面、点击、填表与截图。",
        "category": "开发者工具",
        "badge": "编程套餐",
        "icon": "browser",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-puppeteer",
        "name": "Puppeteer",
        "description": "无头 Chrome 自动化，适合抓取与端到端验证。",
        "category": "开发者工具",
        "badge": None,
        "icon": "browser",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-sequential",
        "name": "顺序思考",
        "description": "分步推理与问题拆解，提升复杂任务规划质量。",
        "category": "开发者工具",
        "badge": None,
        "icon": "think",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-memory",
        "name": "知识图谱记忆",
        "description": "持久化实体关系记忆，跨会话召回关键事实。",
        "category": "开发者工具",
        "badge": None,
        "icon": "memory",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    # —— 生产力 / 搜索 ——
    {
        "id": "preset-mcp-fetch",
        "name": "网页抓取",
        "description": "按 URL 拉取网页正文，辅助阅读与摘要。",
        "category": "生产力",
        "badge": None,
        "icon": "fetch",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-brave",
        "name": "Brave 搜索",
        "description": "隐私友好的网页搜索，补充实时信息。",
        "category": "生产力",
        "badge": None,
        "icon": "search",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env": {"BRAVE_API_KEY": ""},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-time",
        "name": "时间与时区",
        "description": "当前时间、时区转换与日程相关计算。",
        "category": "生产力",
        "badge": None,
        "icon": "time",
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-time"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-google-maps",
        "name": "Google Maps",
        "description": "地点搜索、路线与地理编码。",
        "category": "生产力",
        "badge": None,
        "icon": "maps",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-google-maps"],
        "env": {"GOOGLE_MAPS_API_KEY": ""},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-everything",
        "name": "Everything 示例",
        "description": "官方示例服务器，演示资源 / 提示 / 工具协议能力。",
        "category": "生产力",
        "badge": "示例",
        "icon": "demo",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-everything"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
    {
        "id": "preset-mcp-context7",
        "name": "Context7 文档",
        "description": "按需拉取最新库文档，减少过时 API 幻觉。",
        "category": "生产力",
        "badge": "编程套餐",
        "icon": "docs",
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "env": {},
        "url": None,
        "enabled": 0,
    },
]

_PRESET_BY_ID = {p["id"]: p for p in PRESET_MCPS}


def preset_meta(server_id: str) -> dict | None:
    """返回市场用元数据（不含 command 等运行配置）。"""
    p = _PRESET_BY_ID.get(server_id)
    if not p:
        return None
    return {
        "description": p.get("description") or "",
        "category": p.get("category") or "其他",
        "badge": p.get("badge"),
        "icon": p.get("icon") or "default",
    }


def preset_json_template() -> dict:
    """返回 Cursor/Claude 风格的示例 JSON（含全部预置）。"""
    mcp_servers: dict = {}
    for p in PRESET_MCPS:
        key = p["id"].replace("preset-mcp-", "")
        entry: dict = {"command": p["command"], "args": p["args"]}
        if p.get("env"):
            entry["env"] = p["env"]
        if p.get("url"):
            entry["url"] = p["url"]
        mcp_servers[key] = entry
    return {"mcpServers": mcp_servers}


async def ensure_preset_mcps(db: aiosqlite.Connection) -> int:
    """首次启动写入预置 MCP；已存在则跳过。"""
    inserted = 0
    now = utc_now()
    for p in PRESET_MCPS:
        cur = await db.execute("SELECT id FROM mcp_servers WHERE id=?", (p["id"],))
        if await cur.fetchone():
            mcp_manager.register_server_id(p["id"])
            continue
        await db.execute(
            """
            INSERT INTO mcp_servers(id, name, transport, command, args_json, env_json, url, enabled, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                p["id"],
                p["name"],
                p["transport"],
                p["command"],
                json.dumps(p["args"], ensure_ascii=False),
                json.dumps(p.get("env") or {}, ensure_ascii=False),
                p["url"],
                p["enabled"],
                now,
                now,
            ),
        )
        mcp_manager.register_server_id(p["id"])
        inserted += 1
    if inserted:
        await db.commit()
    return inserted


_LARK_MCP_PKG = "@larksuiteoapi/lark-mcp"


def _should_upgrade_feishu(args: list, env: dict) -> bool:
    joined = " ".join(str(a) for a in args)
    if _LARK_MCP_PKG in joined:
        return False
    if "feishu-mcp" in joined:
        return True
    # 旧预置 env 特征
    if "FEISHU_ENABLED_MODULES" in env or ("FEISHU_APP_ID" in env and "APP_ID" not in env):
        return True
    return False


async def upgrade_preset_mcps(db: aiosqlite.Connection) -> int:
    """
    升级已知错误预置（如飞书旧包无发消息能力）。
    保留用户已填凭证；不改 enabled / name。
    """
    feishu = _PRESET_BY_ID.get("preset-mcp-feishu")
    if not feishu:
        return 0
    cur = await db.execute("SELECT * FROM mcp_servers WHERE id=?", (feishu["id"],))
    row = await cur.fetchone()
    if not row:
        return 0
    data = dict(row)
    args = json.loads(data.get("args_json") or "[]")
    env = json.loads(data.get("env_json") or "{}")
    if not isinstance(args, list):
        args = []
    if not isinstance(env, dict):
        env = {}
    if not _should_upgrade_feishu(args, env):
        # 已是官方包：补齐任务工具集 / OAuth 参数 / env 字段
        joined = " ".join(str(a) for a in args)
        if _LARK_MCP_PKG not in joined:
            return 0

        app_id = str(env.get("APP_ID") or env.get("FEISHU_APP_ID") or "").strip()
        app_secret = str(env.get("APP_SECRET") or env.get("FEISHU_APP_SECRET") or "").strip()
        merged_env = {
            "APP_ID": app_id,
            "APP_SECRET": app_secret,
            "USER_ACCESS_TOKEN": str(
                env.get("USER_ACCESS_TOKEN")
                or env.get("FEISHU_USER_ACCESS_TOKEN")
                or env.get("LARK_USER_ACCESS_TOKEN")
                or ""
            ).strip(),
            "REFRESH_USER_ACCESS_TOKEN": str(
                env.get("REFRESH_USER_ACCESS_TOKEN")
                or env.get("FEISHU_REFRESH_USER_ACCESS_TOKEN")
                or ""
            ).strip(),
            "DEFAULT_RECEIVE_ID": str(
                env.get("DEFAULT_RECEIVE_ID")
                or env.get("FEISHU_DEFAULT_RECEIVE_ID")
                or env.get("FEISHU_DEFAULT_CHAT_ID")
                or ""
            ).strip(),
            "DEFAULT_RECEIVE_ID_TYPE": str(
                env.get("DEFAULT_RECEIVE_ID_TYPE")
                or env.get("FEISHU_DEFAULT_RECEIVE_ID_TYPE")
                or "open_id"
            ).strip()
            or "open_id",
        }
        need_task = "preset.task.default" not in joined and "task.v2.task.create" not in joined
        need_oauth = "--oauth" not in joined
        env_changed = merged_env != env or "REFRESH_USER_ACCESS_TOKEN" not in env
        if not need_task and not need_oauth and not env_changed:
            return 0

        new_args = list(feishu["args"]) if need_task or need_oauth else list(args)
        now = utc_now()
        await db.execute(
            """
            UPDATE mcp_servers
            SET args_json=?, env_json=?, updated_at=?
            WHERE id=?
            """,
            (
                json.dumps(new_args, ensure_ascii=False),
                json.dumps(merged_env, ensure_ascii=False),
                now,
                feishu["id"],
            ),
        )
        await db.execute("DELETE FROM mcp_tools_cache WHERE server_id=?", (feishu["id"],))
        await db.commit()
        try:
            await mcp_manager.close_session(feishu["id"])
        except Exception:  # noqa: BLE001
            pass
        return 1

    app_id = str(env.get("APP_ID") or env.get("FEISHU_APP_ID") or "").strip()
    app_secret = str(env.get("APP_SECRET") or env.get("FEISHU_APP_SECRET") or "").strip()
    default_receive = str(
        env.get("DEFAULT_RECEIVE_ID")
        or env.get("FEISHU_DEFAULT_RECEIVE_ID")
        or env.get("FEISHU_DEFAULT_CHAT_ID")
        or ""
    ).strip()
    default_type = str(
        env.get("DEFAULT_RECEIVE_ID_TYPE") or env.get("FEISHU_DEFAULT_RECEIVE_ID_TYPE") or "open_id"
    ).strip() or "open_id"
    new_env = {
        "APP_ID": app_id,
        "APP_SECRET": app_secret,
        "USER_ACCESS_TOKEN": str(
            env.get("USER_ACCESS_TOKEN")
            or env.get("FEISHU_USER_ACCESS_TOKEN")
            or env.get("LARK_USER_ACCESS_TOKEN")
            or ""
        ).strip(),
        "REFRESH_USER_ACCESS_TOKEN": str(
            env.get("REFRESH_USER_ACCESS_TOKEN")
            or env.get("FEISHU_REFRESH_USER_ACCESS_TOKEN")
            or ""
        ).strip(),
        "DEFAULT_RECEIVE_ID": default_receive,
        "DEFAULT_RECEIVE_ID_TYPE": default_type,
    }
    now = utc_now()
    await db.execute(
        """
        UPDATE mcp_servers
        SET command=?, args_json=?, env_json=?, updated_at=?
        WHERE id=?
        """,
        (
            feishu["command"],
            json.dumps(feishu["args"], ensure_ascii=False),
            json.dumps(new_env, ensure_ascii=False),
            now,
            feishu["id"],
        ),
    )
    await db.execute("DELETE FROM mcp_tools_cache WHERE server_id=?", (feishu["id"],))
    await db.commit()
    try:
        await mcp_manager.close_session(feishu["id"])
    except Exception:  # noqa: BLE001
        pass
    return 1
