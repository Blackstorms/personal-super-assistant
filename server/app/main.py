"""
Personal Super Assistant - FastAPI 后端入口。

职责：
- 启动时初始化 SQLite、扫描技能包、生成本地 Bearer Token
- 挂载 /api/v1 全部业务路由
- 仅监听 127.0.0.1，供 Electron 本地代理调用
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.env_load import load_runtime_env

# 开发态读 server/.env；打包态读 ~/.personal-super-assistant/.env（不覆盖已有环境变量）
load_runtime_env()

from app.api.v1 import router as api_v1_router
from app.core.config import settings
from app.db.database import init_db
from app.skills.registry import SkillRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：先让 HTTP 就绪，再后台启动 Hermes（避免阻塞健康检查）。"""
    import asyncio
    import logging

    log = logging.getLogger("psa.lifespan")
    await init_db()
    registry = SkillRegistry()
    await registry.reload()
    app.state.skill_registry = registry
    app.state.hermes_status = {
        "available": False,
        "booting": True,
        "error": None,
        "model_tools_loaded": False,
        "mcp_tools": [],
        "mcp_tools_count": 0,
    }

    async def _boot_hermes() -> None:
        from app.db.database import get_db
        from app.hermes_bridge import startup_hermes

        db = await get_db()
        try:
            status = await startup_hermes(db)
            status["booting"] = False
            app.state.hermes_status = status
            log.info(
                "Hermes boot done available=%s error=%s",
                status.get("available"),
                status.get("error"),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Hermes boot failed: %s", e)
            app.state.hermes_status = {
                "available": False,
                "booting": False,
                "error": str(e),
                "model_tools_loaded": False,
                "mcp_tools": [],
                "mcp_tools_count": 0,
            }
        finally:
            await db.close()

    hermes_task = asyncio.create_task(_boot_hermes())
    app.state.hermes_boot_task = hermes_task

    from app.scheduler.ticker import start_scheduler, stop_scheduler

    await start_scheduler(app)

    yield

    await stop_scheduler(app)

    from app.hermes_bridge import shutdown_hermes

    if not hermes_task.done():
        hermes_task.cancel()
        try:
            await hermes_task
        except asyncio.CancelledError:
            pass
    await shutdown_hermes()


app = FastAPI(
    title="Personal Super Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)

# 本地桌面：开发态 Vite；生产经 Main 代理同源
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:18765",
        "http://127.0.0.1:18765",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": detail.get("code", "HTTP_ERROR"),
            "message": detail.get("message", str(exc.detail)),
            **({"detail": detail.get("detail")} if detail.get("detail") is not None else {}),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "请求参数不合法",
            "detail": exc.errors(),
        },
    )


app.include_router(api_v1_router, prefix="/api/v1")


def get_project_root() -> Path:
    """返回 monorepo 根目录（打包态为 PyInstaller _MEIPASS）。"""
    from app.core.config import resource_root

    return resource_root()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=os.getenv("PSA_RELOAD") == "1",
    )
