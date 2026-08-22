"""认证路由 - 用户登录、注册、令牌刷新与知乎扫码登录

POST /auth/login            用户登录
POST /auth/refresh          刷新访问令牌
POST /auth/register         用户注册
POST /auth/qrcode           发起知乎扫码登录（返回 token 与二维码图片地址）
GET  /auth/qrcode/{token}/image      获取二维码图片
GET  /auth/qrcode/{token}/status     轮询扫码状态
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from passlib.context import CryptContext

from zhihu_downloader.api.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.auth.jwt_auth import (
    create_access_token,
    create_refresh_token,
    refresh_token,
)
from zhihu_downloader.auth.qr_login import QrLoginError, ZhihuQrLoginService
from zhihu_downloader.infra.models import User as UserModel
from zhihu_downloader.infra.repository import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 扫码登录共享单例：登录成功后 cookie 保存在此 manager 中，供后续下载使用。
# （app.py 未注册该服务，此处用模块级单例保证 start/poll 间状态一致。）
_qr_cookie_manager = CookieManager()
qr_login_service = ZhihuQrLoginService(cookie_manager=_qr_cookie_manager)


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


# ---------------------------------------------------------------------------
# 知乎扫码登录
# ---------------------------------------------------------------------------


@router.post("/qrcode")
async def create_qrcode() -> dict:
    """发起知乎扫码登录，返回 token 与二维码图片地址。

    Returns:
        {"token": str, "image_url": "/api/auth/qrcode/{token}/image", ...}
    """
    try:
        result = await qr_login_service.start()
    except QrLoginError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return result


@router.get("/qrcode/{token}/image")
async def qrcode_image(token: str) -> Response:
    """返回二维码图片（JPEG）。"""
    try:
        image = await qr_login_service.fetch_image(token)
    except QrLoginError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return Response(content=image, media_type="image/jpeg")


@router.get("/qrcode/{token}/status")
async def qrcode_status(token: str) -> dict:
    """轮询扫码状态。

    Returns:
        确认成功: {"status": "confirmed", "user_id": str, "error": None}
        未完成:   {"status": "waiting" | "scanned", ...}
        失败/过期: {"status": "error" | "expired", ...}
    """
    try:
        result = await qr_login_service.poll(token)
    except QrLoginError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    return {
        "status": result["status"],
        "user_id": result.get("user_id"),
        "error": result.get("error"),
    }
