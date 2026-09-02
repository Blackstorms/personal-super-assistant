"""本地 Bearer Token 鉴权依赖。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer = HTTPBearer(auto_error=False)


async def require_token(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """校验 Authorization: Bearer <local_token>。"""
    expected = settings.ensure_token()
    if cred is None or cred.credentials != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "invalid local token"},
        )
    return cred.credentials
