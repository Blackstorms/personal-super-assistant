"""PyInstaller sidecar 入口。

必须用 app 对象调用 uvicorn.run，不能用 \"app.main:app\" 字符串：
冻结后按模块名再 import 会失败。
"""
from __future__ import annotations

import os

import uvicorn

from app.core.env_load import load_runtime_env

load_runtime_env()

from app.core.config import settings
from app.main import app


def main() -> None:
    host = os.environ.get("PSA_HOST", settings.host)
    port = int(os.environ.get("PSA_PORT", str(settings.port)))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
