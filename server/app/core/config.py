"""
全局配置。

说明：
- 默认仅绑定回环地址，避免暴露到局域网
- 数据目录优先使用环境变量 PSA_DATA_DIR，便于测试隔离
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_data_dir() -> Path:
    home = Path.home() / ".personal-super-assistant"
    home.mkdir(parents=True, exist_ok=True)
    return home


def resource_root() -> Path:
    """项目根目录；PyInstaller onefile 为 sys._MEIPASS。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if isinstance(meipass, str) and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """运行时配置（可由环境变量覆盖）。"""

    model_config = SettingsConfigDict(env_prefix="PSA_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 18765
    data_dir: Path = Field(default_factory=_default_data_dir)
    local_token: str = ""
    admin_username: str = "admin"
    admin_password: str = "admin"
    skills_dir: Optional[Path] = None
    compress_max_messages: int = 40
    compress_max_tokens: int = 32_000
    # 对话是否暴露 fs_write（默认关：攻略等直接正文输出，避免卡在写文件确认）
    enable_chat_fs_write: bool = False
    # 飞书 OAuth 环回回调（与 lark-mcp 官方一致，非 API 服务端口）
    feishu_oauth_host: str = "localhost"
    feishu_oauth_port: int = 3000
    feishu_oauth_path: str = "/callback"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def schema_path(self) -> Path:
        """schema.sql 位于 resources/db/（开发态项目根，打包态 _MEIPASS）。"""
        return resource_root() / "resources" / "db" / "schema.sql"

    def ensure_token(self) -> str:
        if not self.local_token:
            self.local_token = secrets.token_urlsafe(24)
        return self.local_token


settings = Settings()
