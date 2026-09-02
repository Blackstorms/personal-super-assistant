"""健康检查（可豁免鉴权）。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from app.db.database import get_db

router = APIRouter()
_STARTED = time.time()


@router.get("/health")
async def health(request: Request):
    """F1：检测后端存活、版本、数据库是否可用。"""
    db_ok = False
    try:
        db = await get_db()
        try:
            await db.execute("SELECT 1")
            db_ok = True
        finally:
            await db.close()
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": "1.0.0",
        "db_ok": db_ok,
        "uptime_sec": int(time.time() - _STARTED),
        "hermes": _hermes_status(request),
    }


def _hermes_status(request: Request | None = None) -> dict:
    try:
        from app.hermes_bridge.lifecycle import get_bridge_status

        status = get_bridge_status()
        if request is not None:
            cached = getattr(request.app.state, "hermes_status", None)
            if isinstance(cached, dict):
                merged = {**cached, **status}
                if cached.get("booting") and not status.get("available"):
                    merged["booting"] = True
                elif status.get("available"):
                    merged["booting"] = False
                return merged
        return status
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)}
