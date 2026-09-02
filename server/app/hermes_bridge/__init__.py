"""
Hermes Agent 适配层。

源码已 vendored 至仓库 `third_party/hermes-agent/`（MIT），经本包适配接入
FastAPI Agent Runtime；不依赖本机外部 Hermes 路径。
"""

from __future__ import annotations

from app.hermes_bridge.lifecycle import (
    get_bridge_status,
    hermes_available,
    shutdown_hermes,
    startup_hermes,
)

__all__ = [
    "get_bridge_status",
    "hermes_available",
    "shutdown_hermes",
    "startup_hermes",
]
