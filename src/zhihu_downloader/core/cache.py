"""HTTP响应缓存"""

from __future__ import annotations

import time
from typing import Any


class CacheEntry:
    """缓存条目"""

    __slots__ = ("expires_at", "value")

    def __init__(self, value: str, ttl: int) -> None:
        self.value = value
        self.expires_at: float = time.time() + ttl

    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() > self.expires_at


class ResponseCache:
    """HTTP响应缓存"""

    def __init__(self, ttl: int = 3600) -> None:
        """
        初始化缓存

        Args:
            ttl: 默认缓存有效期（秒）
        """
        self._cache: dict[str, CacheEntry] = {}
        self._default_ttl = ttl
        self._hits = 0
        self._misses = 0

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        """
        设置缓存

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 缓存有效期（秒），使用默认值
        """
        self._cache[key] = CacheEntry(value, ttl or self._default_ttl)

    def get(self, key: str) -> str | None:
        """
        获取缓存

        Args:
            key: 缓存键

        Returns:
            缓存值，如果不存在或已过期返回None
        """
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        if entry.is_expired():
            del self._cache[key]
            self._misses += 1
            return None

        self._hits += 1
        return entry.value

    def delete(self, key: str) -> bool:
        """
        删除缓存

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """清除所有缓存"""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, Any]:
        """缓存统计"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "total": len(self._cache),
            "valid": sum(1 for e in self._cache.values() if not e.is_expired()),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": hit_rate,
        }

    def cleanup_expired(self) -> int:
        """
        清理过期缓存

        Returns:
            清理的条目数
        """
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)
