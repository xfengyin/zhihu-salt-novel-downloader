"""HTML响应缓存 - LRU缓存实现"""

import hashlib
import json
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from collections import OrderedDict
from threading import Lock


logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    url: str
    content: str
    created_at: float
    expires_at: float

    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() > self.expires_at


class LRUCache:
    """LRU缓存实现"""

    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get(self, url: str) -> Optional[str]:
        """获取缓存内容"""
        with self._lock:
            if url not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[url]
            if entry.is_expired():
                del self._cache[url]
                self._misses += 1
                return None

            self._cache.move_to_end(url)
            self._hits += 1
            return entry.content

    def set(self, url: str, content: str, ttl: Optional[int] = None) -> None:
        """设置缓存"""
        with self._lock:
            now = time.time()
            expires_at = now + (ttl if ttl is not None else self.ttl)

            if url in self._cache:
                del self._cache[url]

            entry = CacheEntry(
                url=url,
                content=content,
                created_at=now,
                expires_at=expires_at
            )

            self._cache[url] = entry

            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def delete(self, url: str) -> bool:
        """删除缓存"""
        with self._lock:
            if url in self._cache:
                del self._cache[url]
                return True
            return False

    def clear(self) -> None:
        """清除所有缓存"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def cleanup_expired(self) -> int:
        """清理过期缓存，返回清理数量"""
        with self._lock:
            now = time.time()
            expired_keys = [
                url for url, entry in self._cache.items()
                if entry.expires_at < now
            ]

            for url in expired_keys:
                del self._cache[url]

            return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0

            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': f"{hit_rate:.2%}",
                'total_requests': total
            }


class ResponseCache:
    """响应缓存 - LRU + 磁盘持久化"""

    def __init__(self, ttl: int = 3600, cache_dir: Optional[str] = None, max_memory_size: int = 1000):
        self.ttl = ttl
        self.max_memory_size = max_memory_size
        self._memory_cache = LRUCache(max_size=max_memory_size, ttl=ttl)

        self._cache_dir: Optional[Path] = None
        if cache_dir:
            self._cache_dir = Path(cache_dir)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

        self._lock = Lock()

    def _get_cache_key(self, url: str) -> str:
        """生成缓存键（URL的MD5哈希）"""
        return hashlib.md5(url.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径"""
        return self._cache_dir / f"{key}.json"

    def get(self, url: str) -> Optional[str]:
        """获取缓存内容"""
        content = self._memory_cache.get(url)
        if content is not None:
            logger.debug(f"内存缓存命中: {url}")
            return content

        if self._cache_dir:
            key = self._get_cache_key(url)
            cache_path = self._get_cache_path(key)

            if cache_path.exists():
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    entry = CacheEntry(**data)
                    if not entry.is_expired():
                        self._memory_cache.set(url, entry.content)
                        logger.debug(f"磁盘缓存命中: {url}")
                        return entry.content
                    else:
                        cache_path.unlink()
                except Exception as e:
                    logger.warning(f"读取缓存失败: {e}")

        return None

    def set(self, url: str, content: str, ttl: Optional[int] = None) -> None:
        """设置缓存"""
        self._memory_cache.set(url, content, ttl)

        if self._cache_dir:
            key = self._get_cache_key(url)
            cache_path = self._get_cache_path(key)

            try:
                now = time.time()
                entry = CacheEntry(
                    url=url,
                    content=content,
                    created_at=now,
                    expires_at=now + (ttl if ttl is not None else self.ttl)
                )

                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(asdict(entry), f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"写入缓存失败: {e}")

    def delete(self, url: str) -> None:
        """删除缓存"""
        self._memory_cache.delete(url)

        if self._cache_dir:
            key = self._get_cache_key(url)
            cache_path = self._get_cache_path(key)
            if cache_path.exists():
                cache_path.unlink()

    def clear(self) -> None:
        """清除所有缓存"""
        self._memory_cache.clear()

        if self._cache_dir and self._cache_dir.exists():
            for cache_file in self._cache_dir.glob("*.json"):
                cache_file.unlink()

        logger.info("缓存已清除")

    def _load_from_disk(self) -> None:
        """从磁盘加载缓存"""
        if not self._cache_dir or not self._cache_dir.exists():
            return

        loaded = 0
        for cache_file in self._cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                entry = CacheEntry(**data)
                if not entry.is_expired():
                    key = cache_file.stem
                    self._memory_cache.set(entry.url, entry.content)
                    loaded += 1
            except Exception:
                pass

        if loaded > 0:
            logger.info(f"从磁盘加载了 {loaded} 个缓存条目")

    def stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return self._memory_cache.stats()

    def cleanup(self) -> int:
        """清理过期缓存"""
        return self._memory_cache.cleanup_expired()
