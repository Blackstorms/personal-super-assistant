"""系统登录（用户名密码换取本地 Bearer Token）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn):
    """校验账号密码，返回本机 API Token。"""
    if body.username != settings.admin_username or body.password != settings.admin_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "用户名或密码错误"},
        )
    return {
        "token": settings.ensure_token(),
        "username": body.username,
    }
