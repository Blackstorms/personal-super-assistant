"""SQLite 连接与初始化。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from app.core.config import settings

# 与 migrate_schema 能力对齐的 schema 版本；升级时递增并写 PRAGMA user_version
SCHEMA_VERSION = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_db() -> aiosqlite.Connection:
    """获取带外键与 WAL 的数据库连接（调用方负责关闭，或使用依赖注入）。"""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA journal_mode = WAL")
    return db


async def _column_names(db: aiosqlite.Connection, table: str) -> set[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return {r["name"] for r in rows}


async def _column_notnull(db: aiosqlite.Connection, table: str, column: str) -> bool | None:
    cur = await db.execute(f"PRAGMA table_info({table})")
    for r in await cur.fetchall():
        if r["name"] == column:
            return bool(r["notnull"])
    return None


async def _migrate_knowledge_sources_nullable_workspace(db: aiosqlite.Connection) -> None:
    """旧库 knowledge_sources.workspace_id 为 NOT NULL 时，重建表以允许全局知识库（无项目）。"""
    if await _column_notnull(db, "knowledge_sources", "workspace_id") is not True:
        return
    await db.execute("PRAGMA foreign_keys=OFF")
    await db.executescript(
        """
        CREATE TABLE knowledge_sources_new (
          id TEXT PRIMARY KEY,
          base_id TEXT REFERENCES knowledge_bases(id) ON DELETE CASCADE,
          workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
          name TEXT,
          path TEXT NOT NULL,
          source_type TEXT NOT NULL DEFAULT 'path',
          state TEXT NOT NULL DEFAULT 'idle',
          doc_count INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          updated_at TEXT NOT NULL
        );
        INSERT INTO knowledge_sources_new(
          id, base_id, workspace_id, name, path, source_type, state, doc_count, last_error, updated_at
        )
        SELECT
          id, base_id, workspace_id, name, path,
          COALESCE(source_type, 'path'), state, doc_count, last_error, updated_at
        FROM knowledge_sources;
        DROP TABLE knowledge_sources;
        ALTER TABLE knowledge_sources_new RENAME TO knowledge_sources;
        """
    )
    await db.execute("PRAGMA foreign_keys=ON")


async def migrate_schema(db: aiosqlite.Connection) -> None:
    """对已有库增量补列（schema.sql 的 CREATE IF NOT EXISTS 不会 ALTER）。"""
    ws_cols = await _column_names(db, "workspaces")
    for col, decl in [
        ("instructions", "TEXT"),
        ("expert_id", "TEXT"),
        ("skill_ids_json", "TEXT"),
        ("mcp_ids_json", "TEXT"),
        ("knowledge_ids_json", "TEXT"),
    ]:
        if col not in ws_cols:
            await db.execute(f"ALTER TABLE workspaces ADD COLUMN {col} {decl}")

    sess_cols = await _column_names(db, "sessions")
    for col, decl in [
        ("summary_text", "TEXT"),
        ("summary_upto_id", "TEXT"),
        ("composer_bindings_json", "TEXT"),
    ]:
        if col not in sess_cols:
            await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {decl}")

    run_cols = await _column_names(db, "chat_runs")
    if "pending_json" not in run_cols:
        await db.execute("ALTER TABLE chat_runs ADD COLUMN pending_json TEXT")

    mem_cols = await _column_names(db, "memories")
    if "confidence" not in mem_cols:
        await db.execute("ALTER TABLE memories ADD COLUMN confidence REAL")

    ks_cols = await _column_names(db, "knowledge_sources")
    for col, decl in [
        ("name", "TEXT"),
        ("source_type", "TEXT NOT NULL DEFAULT 'path'"),
        ("base_id", "TEXT"),
    ]:
        if col not in ks_cols:
            await db.execute(f"ALTER TABLE knowledge_sources ADD COLUMN {col} {decl}")

    await _migrate_knowledge_sources_nullable_workspace(db)

    msg_cols = await _column_names(db, "messages")
    if "reasoning_content" not in msg_cols:
        await db.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT")

    # Hermes 融入：MCP / skills 扩展列与新表（oauth_meta_json 已废弃，不再新增）
    mcp_cols = await _column_names(db, "mcp_servers")
    for col, decl in [
        ("headers_json", "TEXT"),
        ("tools_policy_json", "TEXT"),
        ("timeout", "INTEGER"),
        ("connect_timeout", "INTEGER"),
        ("supports_parallel", "INTEGER NOT NULL DEFAULT 0"),
        ("auth_type", "TEXT"),
    ]:
        if col not in mcp_cols:
            await db.execute(f"ALTER TABLE mcp_servers ADD COLUMN {col} {decl}")

    skill_cols = await _column_names(db, "skills")
    for col, decl in [
        ("category", "TEXT"),
        ("source", "TEXT"),
        ("platforms_json", "TEXT"),
        ("metadata_json", "TEXT"),
        ("content_hash", "TEXT"),
    ]:
        if col not in skill_cols:
            await db.execute(f"ALTER TABLE skills ADD COLUMN {col} {decl}")

    for ddl in [
        """
        CREATE TABLE IF NOT EXISTS skill_bundles (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          description TEXT,
          skills_json TEXT NOT NULL,
          instruction TEXT,
          updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pending_skill_writes (
          id TEXT PRIMARY KEY,
          skill_id TEXT NOT NULL,
          action TEXT NOT NULL,
          diff_text TEXT,
          payload_json TEXT,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS hermes_toolset_settings (
          id TEXT PRIMARY KEY,
          toolset TEXT NOT NULL UNIQUE,
          enabled INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        )
        """,
    ]:
        await db.execute(ddl)

    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='session_attachments'"
    )
    if not await cur.fetchone():
        await db.execute(
            """
            CREATE TABLE session_attachments (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              path TEXT NOT NULL,
              size_bytes INTEGER NOT NULL DEFAULT 0,
              mime_type TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_session_attachments_session ON session_attachments(session_id, created_at)"
        )
        await db.commit()

    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='scheduled_jobs'"
    )
    if not await cur.fetchone():
        await db.execute(
            """
            CREATE TABLE scheduled_jobs (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              prompt TEXT NOT NULL,
              schedule_raw TEXT NOT NULL,
              schedule_kind TEXT NOT NULL,
              interval_seconds INTEGER,
              next_run_at TEXT,
              repeat_mode TEXT NOT NULL DEFAULT 'forever',
              repeat_limit INTEGER,
              repeat_done INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              state TEXT NOT NULL DEFAULT 'active',
              workspace_id TEXT REFERENCES workspaces(id) ON DELETE SET NULL,
              model_profile_id TEXT,
              expert_id TEXT,
              knowledge_ids_json TEXT,
              skill_ids_json TEXT,
              mcp_ids_json TEXT,
              delivery_mode TEXT NOT NULL DEFAULT 'new_session',
              target_session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
              last_run_at TEXT,
              last_status TEXT,
              last_error TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_next_run ON scheduled_jobs(enabled, next_run_at)"
        )
        await db.execute(
            """
            CREATE TABLE scheduled_job_runs (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL REFERENCES scheduled_jobs(id) ON DELETE CASCADE,
              session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
              run_id TEXT,
              status TEXT NOT NULL DEFAULT 'running',
              started_at TEXT NOT NULL,
              finished_at TEXT,
              output_preview TEXT,
              error_message TEXT
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_job ON scheduled_job_runs(job_id, started_at DESC)"
        )
        await db.commit()

    # 将无归属的旧 source 迁成知识库（一源一库）
    cur = await db.execute(
        """
        SELECT id, workspace_id, name, path, source_type, state, doc_count, last_error, updated_at
        FROM knowledge_sources
        WHERE base_id IS NULL OR base_id = ''
        """
    )
    orphans = await cur.fetchall()
    for s in orphans:
        bid = s["id"]
        now = s["updated_at"] or utc_now()
        await db.execute(
            """
            INSERT OR IGNORE INTO knowledge_bases(
              id, workspace_id, name, description, root_path, doc_count, state, last_error, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                bid,
                s["workspace_id"],
                s["name"] or Path(s["path"]).name,
                None,
                s["path"],
                s["doc_count"] or 0,
                s["state"] or "idle",
                s["last_error"],
                now,
                now,
            ),
        )
        await db.execute("UPDATE knowledge_sources SET base_id=? WHERE id=?", (bid, bid))

    # FTS 外链内容表同步触发器（旧库 schema.sql 可能尚未包含）
    for ddl in (
        """
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
          INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
          INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
          INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
          INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ai AFTER INSERT ON knowledge_chunks BEGIN
          INSERT INTO knowledge_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS knowledge_chunks_ad AFTER DELETE ON knowledge_chunks BEGIN
          INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, content)
            VALUES('delete', old.rowid, old.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS knowledge_chunks_au AFTER UPDATE OF content ON knowledge_chunks BEGIN
          INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts, rowid, content)
            VALUES('delete', old.rowid, old.content);
          INSERT INTO knowledge_chunks_fts(rowid, content) VALUES (new.rowid, new.content);
        END
        """,
    ):
        await db.execute(ddl)

    await _upgrade_compress_max_tokens(db)


async def _upgrade_compress_max_tokens(db: aiosqlite.Connection) -> None:
    """旧默认 8k 过小，工具结果很容易顶破保留窗口；升级到当前 32k 默认。"""
    cur = await db.execute("SELECT value_json FROM app_settings WHERE key='compress'")
    row = await cur.fetchone()
    if not row:
        return
    try:
        cfg = json.loads(row["value_json"] or "{}")
    except json.JSONDecodeError:
        return
    if int(cfg.get("max_tokens") or 0) != 8000:
        return
    cfg["max_tokens"] = int(settings.compress_max_tokens)
    await db.execute(
        "UPDATE app_settings SET value_json=?, updated_at=? WHERE key='compress'",
        (json.dumps(cfg, ensure_ascii=False), utc_now()),
    )


async def _ensure_default_llm_profile(db: aiosqlite.Connection) -> None:
    """从旧 llm 设置或空配置迁移出默认 profile。"""
    cur = await db.execute("SELECT COUNT(*) AS c FROM llm_profiles")
    count = (await cur.fetchone())["c"]
    if count > 0:
        return
    cfg = await fetch_setting(db, "llm") or {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    now = utc_now()
    await db.execute(
        """
        INSERT INTO llm_profiles(
          id, name, base_url, api_key, model, temperature, max_tokens, is_default, created_at, updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            str(uuid.uuid4()),
            "默认模型",
            cfg.get("base_url") or "https://api.openai.com/v1",
            cfg.get("api_key") or "",
            cfg.get("model") or "gpt-4o-mini",
            float(cfg.get("temperature", 0.7)),
            int(cfg.get("max_tokens", 2048)),
            1,
            now,
            now,
        ),
    )


async def init_db() -> None:
    """执行 schema.sql，并确保 local_token / 默认 LLM 配置存在。"""
    schema = settings.schema_path.read_text(encoding="utf-8")
    db = await get_db()
    try:
        await db.executescript(schema)
        await migrate_schema(db)
        await db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        await db.commit()
        token = settings.ensure_token()
        # 持久化 token，便于 Electron 与后端对齐
        await db.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at)
            VALUES('local_token', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (json.dumps({"token": token}), utc_now()),
        )
        # 默认 LLM 配置（空 key，用户在设置页填写）
        cur = await db.execute("SELECT value_json FROM app_settings WHERE key='llm'")
        row = await cur.fetchone()
        if row is None:
            await db.execute(
                """
                INSERT INTO app_settings(key, value_json, updated_at)
                VALUES('llm', ?, ?)
                """,
                (
                    json.dumps(
                        {
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "",
                            "model": "gpt-4o-mini",
                            "temperature": 0.7,
                            "max_tokens": 2048,
                        }
                    ),
                    utc_now(),
                ),
            )
        await db.execute(
            """
            INSERT INTO app_settings(key, value_json, updated_at)
            VALUES('compress', ?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (
                json.dumps(
                    {
                        "max_messages": settings.compress_max_messages,
                        "max_tokens": settings.compress_max_tokens,
                        "keep_messages": 16,
                        "llm_summary": True,
                    }
                ),
                utc_now(),
            ),
        )
        await _ensure_default_llm_profile(db)
        from app.experts.presets import ensure_preset_experts
        from app.mcp.presets import ensure_preset_mcps, upgrade_preset_mcps

        await ensure_preset_mcps(db)
        await upgrade_preset_mcps(db)
        await ensure_preset_experts(db)
        await _seed_hermes_toolsets(db)
        await _seed_web_search_settings(db)
        await db.commit()
    finally:
        await db.close()


DEFAULT_DISABLED_TOOLSETS = (
    "terminal",
    "code_execution",
    "delegation",
    "browser",
    "cronjob",
)


async def _seed_hermes_toolsets(db: aiosqlite.Connection) -> None:
    """首次启动写入危险 toolset 默认 disabled=0。"""
    now = utc_now()
    for name in DEFAULT_DISABLED_TOOLSETS:
        await db.execute(
            """
            INSERT INTO hermes_toolset_settings(id, toolset, enabled, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(toolset) DO NOTHING
            """,
            (str(uuid.uuid4()), name, 0, now),
        )
    # skills 默认启用
    await db.execute(
        """
        INSERT INTO hermes_toolset_settings(id, toolset, enabled, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(toolset) DO NOTHING
        """,
        (str(uuid.uuid4()), "skills", 1, now),
    )


async def _seed_web_search_settings(db: aiosqlite.Connection) -> None:
    """把开发态 .env 中的搜索 Key 写入 SQLite / 用户目录，打包后仍可用。"""
    import os

    from app.core.env_load import persist_search_env

    stored = await fetch_setting(db, "web_search") or {}
    cfg = {
        "provider": (os.environ.get("PSA_WEB_SEARCH_PROVIDER") or stored.get("provider") or "auto").strip()
        or "auto",
        "api_url": (os.environ.get("PSA_WEB_SEARCH_API_URL") or stored.get("api_url") or "").strip(),
        "api_key": (os.environ.get("PSA_WEB_SEARCH_API_KEY") or stored.get("api_key") or "").strip(),
        "tavily_api_key": (os.environ.get("TAVILY_API_KEY") or stored.get("tavily_api_key") or "").strip(),
    }
    if not cfg["api_key"] and not cfg["tavily_api_key"] and not stored:
        return
    await save_setting(db, "web_search", cfg)
    if cfg["api_key"] and not (os.environ.get("PSA_WEB_SEARCH_API_KEY") or "").strip():
        os.environ["PSA_WEB_SEARCH_API_KEY"] = cfg["api_key"]
    if cfg["api_url"] and not (os.environ.get("PSA_WEB_SEARCH_API_URL") or "").strip():
        os.environ["PSA_WEB_SEARCH_API_URL"] = cfg["api_url"]
    if cfg["provider"] and not (os.environ.get("PSA_WEB_SEARCH_PROVIDER") or "").strip():
        os.environ["PSA_WEB_SEARCH_PROVIDER"] = cfg["provider"]
    if cfg["tavily_api_key"] and not (os.environ.get("TAVILY_API_KEY") or "").strip():
        os.environ["TAVILY_API_KEY"] = cfg["tavily_api_key"]
    persist_search_env(settings.data_dir)


async def fetch_setting(db: aiosqlite.Connection, key: str) -> dict | None:
    cur = await db.execute("SELECT value_json FROM app_settings WHERE key=?", (key,))
    row = await cur.fetchone()
    if not row:
        return None
    return json.loads(row["value_json"])


async def save_setting(db: aiosqlite.Connection, key: str, value: dict) -> None:
    await db.execute(
        """
        INSERT INTO app_settings(key, value_json, updated_at)
        VALUES(?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False), utc_now()),
    )
    await db.commit()
