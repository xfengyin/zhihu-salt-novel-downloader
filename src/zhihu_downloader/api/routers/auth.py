"""认证路由 - 用户登录、注册与令牌刷新

POST /auth/login    用户登录
POST /auth/refresh  刷新访问令牌
POST /auth/register 用户注册
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from passlib.context import CryptContext

from zhihu_downloader.api.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from zhihu_downloader.auth.jwt_auth import (
    create_access_token,
    create_refresh_token,
    refresh_token,
)
from zhihu_downloader.infra.models import User as UserModel
from zhihu_downloader.infra.repository import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return pwd_context.hash(password)


@router.post("/login")
async def login(body: LoginRequest) -> TokenResponse:
    """用户登录"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(body.email)

        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="邮箱或密码错误",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户未激活",
            )

        access_token = create_access_token(data={"user_id": user.id, "username": user.email})
        refresh_token_str = create_refresh_token(data={"user_id": user.id, "username": user.email})

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token_str,
            token_type="bearer",
        )


@router.post("/refresh")
async def refresh(body: RefreshRequest) -> TokenResponse:
    """刷新访问令牌"""
    try:
        new_access_token = refresh_token(body.refresh_token)
    except HTTPException as e:
        raise e

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=body.refresh_token,
        token_type="bearer",
    )


@router.post("/register")
async def register(body: RegisterRequest) -> dict:
    """用户注册"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_email(body.email)

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="邮箱已被注册",
            )

        user = UserModel(
            email=body.email,
            password_hash=get_password_hash(body.password),
            plan="free",
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        await repo.create(user)

        return {"message": "注册成功", "user_id": user.id}
