"""用户路由 - 当前用户信息

GET /users/me  获取当前登录用户信息
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from zhihu_downloader.api.schemas import UserSchema
from zhihu_downloader.auth.jwt_auth import TokenData, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_current_user_info(
    token_data: TokenData = Depends(get_current_user),
) -> UserSchema:
    """获取当前登录用户信息"""
    from zhihu_downloader.infra.database import get_session
    from zhihu_downloader.infra.repository import UserRepository

    async with get_session() as session:
        repo = UserRepository(session)
        user = await repo.get(token_data.user_id)

        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        return UserSchema(
            id=user.id,
            email=user.email,
            username=user.email,
            plan=user.plan,
            is_active=user.is_active,
            created_at=user.created_at.isoformat(),
            updated_at=user.updated_at.isoformat(),
        )
