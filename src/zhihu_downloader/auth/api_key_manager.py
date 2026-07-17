"""API Key管理器"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from zhihu_downloader.infra.models import APIKey
from zhihu_downloader.infra.repository import APIKeyRepository


def generate_api_key(length: int = 32) -> str:
    """
    生成随机API Key

    Args:
        length: API Key长度，默认32字符

    Returns:
        随机生成的API Key字符串
    """
    return secrets.token_urlsafe(length)


def hash_api_key(api_key: str) -> str:
    """
    哈希API Key（SHA-256）

    Args:
        api_key: 原始API Key

    Returns:
        SHA-256哈希值字符串
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """
    验证API Key是否匹配哈希值

    Args:
        api_key: 待验证的API Key
        key_hash: 存储的哈希值

    Returns:
        True表示验证通过，False表示不匹配
    """
    return hash_api_key(api_key) == key_hash


class APIKeyManager:
    """API Key管理器"""

    def __init__(self, session: AsyncSession) -> None:
        self._repository = APIKeyRepository(session)

    async def create_api_key(
        self,
        user_id: int,
        name: str,
        scopes: Sequence[str],
        expires_days: int | None = None,
    ) -> tuple[str, APIKey]:
        """
        创建API Key并保存到数据库

        Args:
            user_id: 用户ID
            name: API Key名称
            scopes: 权限范围列表
            expires_days: 过期天数，None表示永不过期

        Returns:
            元组(原始API Key, APIKey对象)，原始Key仅在创建时返回一次
        """
        api_key = generate_api_key()
        key_hash = hash_api_key(api_key)

        expires_at: datetime | None = None
        if expires_days is not None:
            expires_at = datetime.utcnow() + timedelta(days=expires_days)

        api_key_obj = APIKey(
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            scopes=list(scopes),
            expires_at=expires_at,
        )

        await self._repository.create(api_key_obj)
        return api_key, api_key_obj

    async def get_api_key(self, key_id: int, user_id: int | None = None) -> APIKey | None:
        """
        获取API Key详情

        Args:
            key_id: API Key ID
            user_id: 用户ID（可选），用于额外的权限校验

        Returns:
            APIKey对象或None
        """
        api_key = await self._repository.get(key_id)
        if api_key is None:
            return None

        if user_id is not None and api_key.user_id != user_id:
            return None

        return api_key

    async def revoke_api_key(self, key_id: int, user_id: int | None = None) -> bool:
        """
        撤销API Key（从数据库删除）

        Args:
            key_id: API Key ID
            user_id: 用户ID（可选），用于权限校验

        Returns:
            True表示撤销成功，False表示Key不存在或无权限
        """
        if user_id is not None:
            api_key = await self._repository.get(key_id)
            if api_key is None or api_key.user_id != user_id:
                return False

        deleted = await self._repository.delete(key_id)
        return bool(deleted)

    async def validate_scopes(
        self,
        api_key: str,
        required_scopes: Sequence[str],
    ) -> tuple[bool, APIKey | None]:
        """
        验证API Key的权限范围

        Args:
            api_key: 待验证的API Key
            required_scopes: 所需的权限范围列表

        Returns:
            元组(验证结果, APIKey对象)
            - 验证通过返回(True, APIKey对象)
            - 验证失败返回(False, None)
        """
        key_hash = hash_api_key(api_key)
        api_key_obj = await self._repository.get_by_key_hash(key_hash)

        if api_key_obj is None:
            return False, None

        if api_key_obj.expires_at is not None and api_key_obj.expires_at < datetime.utcnow():
            return False, None

        for scope in required_scopes:
            if scope not in api_key_obj.scopes:
                return False, api_key_obj

        await self._repository.update_last_used(api_key_obj.id)
        return True, api_key_obj
