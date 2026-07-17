"""API Key 路由 - API Key 管理

POST   /api-keys       创建 API Key
GET    /api-keys       列出 API Key
DELETE /api-keys/{id}  删除 API Key
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from zhihu_downloader.api.schemas import (
    APIKeyCreateRequest,
    APIKeyCreateResponse,
    APIKeySchema,
)
from zhihu_downloader.auth.api_key_manager import APIKeyManager
from zhihu_downloader.auth.jwt_auth import TokenData, get_current_user
from zhihu_downloader.infra.models import APIKey as APIKeyModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("")
async def create_api_key(
    body: APIKeyCreateRequest,
    token_data: TokenData = Depends(get_current_user),
) -> APIKeyCreateResponse:
    """创建 API Key"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        key_manager = APIKeyManager(session)
        api_key, api_key_obj = await key_manager.create_api_key(
            user_id=token_data.user_id,
            name=body.name,
            scopes=body.scopes,
            expires_days=body.expires_days,
        )

        return APIKeyCreateResponse(
            api_key=api_key,
            key_id=api_key_obj.id,
            name=api_key_obj.name,
            scopes=api_key_obj.scopes,
            expires_at=api_key_obj.expires_at.isoformat() if api_key_obj.expires_at else None,
            created_at=api_key_obj.created_at.isoformat(),
        )


@router.get("")
async def list_api_keys(
    token_data: TokenData = Depends(get_current_user),
) -> list[APIKeySchema]:
    """列出 API Key"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        key_manager = APIKeyManager(session)
        api_keys = await key_manager._repository.list(token_data.user_id)

        return [_model_to_schema(api_key) for api_key in api_keys]


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: int,
    token_data: TokenData = Depends(get_current_user),
) -> dict:
    """删除 API Key"""
    from zhihu_downloader.infra.database import get_session

    async with get_session() as session:
        key_manager = APIKeyManager(session)
        success = await key_manager.revoke_api_key(key_id, token_data.user_id)

        if not success:
            raise HTTPException(status_code=404, detail="API Key 不存在或无权限")

        return {"message": "API Key 已删除", "key_id": key_id}


def _model_to_schema(api_key: APIKeyModel) -> APIKeySchema:
    """将数据库模型转换为 schema"""
    return APIKeySchema(
        id=api_key.id,
        name=api_key.name,
        scopes=api_key.scopes,
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        expires_at=api_key.expires_at.isoformat() if api_key.expires_at else None,
        created_at=api_key.created_at.isoformat(),
    )
