"""飞书预置升级与工具面暴露。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.mcp.presets import _should_upgrade_feishu, upgrade_preset_mcps


def test_should_upgrade_old_feishu_package():
    assert _should_upgrade_feishu(["-y", "feishu-mcp@latest", "--stdio"], {})
    assert _should_upgrade_feishu(
        ["-y", "feishu-mcp"],
        {"FEISHU_APP_ID": "x", "FEISHU_ENABLED_MODULES": "message"},
    )
    assert not _should_upgrade_feishu(
        ["-y", "@larksuiteoapi/lark-mcp", "mcp"],
        {"APP_ID": "x"},
    )


def _prepare_db(subdir: str) -> Path:
    data = Path(__file__).resolve().parent / ".testdata" / subdir
    data.mkdir(parents=True, exist_ok=True)
    os.environ["PSA_DATA_DIR"] = str(data)
    from app.core.config import settings

    settings.data_dir = data
    return data


@pytest.mark.asyncio
async def test_upgrade_feishu_preserves_credentials():
    _prepare_db("feishu-upgrade")
    from app.agent.feishu_tools import feishu_tools_for_surface, load_feishu_credentials
    from app.db.database import get_db, init_db

    await init_db()
    db = await get_db()
    try:
        await db.execute(
            """
            UPDATE mcp_servers
            SET enabled=1,
                command='npx',
                args_json=?,
                env_json=?
            WHERE id='preset-mcp-feishu'
            """,
            (
                json.dumps(["-y", "feishu-mcp@latest", "--stdio"]),
                json.dumps(
                    {
                        "FEISHU_APP_ID": "cli_test_id",
                        "FEISHU_APP_SECRET": "secret_test",
                        "FEISHU_AUTH_TYPE": "tenant",
                        "FEISHU_ENABLED_MODULES": "document,task,message",
                    }
                ),
            ),
        )
        await db.commit()
        n = await upgrade_preset_mcps(db)
        assert n == 1
        cur = await db.execute(
            "SELECT args_json, env_json, enabled FROM mcp_servers WHERE id='preset-mcp-feishu'"
        )
        row = dict(await cur.fetchone())
        args = json.loads(row["args_json"])
        env = json.loads(row["env_json"])
        assert "@larksuiteoapi/lark-mcp" in args
        assert env["APP_ID"] == "cli_test_id"
        assert env["APP_SECRET"] == "secret_test"
        assert row["enabled"] == 1

        tools = await feishu_tools_for_surface(
            db, enable_mcp=True, mcp_ids=["preset-mcp-feishu"]
        )
        names = {((t.get("function") or {}).get("name")) for t in tools}
        assert "feishu_send_message" in names
        assert "feishu_lookup_user" in names

        creds = await load_feishu_credentials(db)
        assert creds is not None
        assert creds["app_id"] == "cli_test_id"
        assert creds["app_secret"] == "secret_test"
    finally:
        await db.close()
