"""缓存测试"""

import pytest
import time
from core.cache import LRUCache, ResponseCache, CacheEntry


class TestLRUCache:
    """LRU缓存测试"""

    def test_basic_operations(self):
        """测试基本操作"""
        cache = LRUCache(max_size=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self):
        """测试LRU淘汰"""
        cache = LRUCache(max_size=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key4", "value4")

        assert cache.get("key1") is None
        assert cache.get("key4") == "value4"

    def test_lru_update(self):
        """测试更新触发LRU"""
        cache = LRUCache(max_size=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        cache.get("key1")

        cache.set("key4", "value4")

        assert cache.get("key2") is None

    def test_expiration(self):
        """测试过期"""
        cache = LRUCache(max_size=10, ttl=1)

        cache.set("key1", "value1")

        assert cache.get("key1") == "value1"

        time.sleep(1.1)

        assert cache.get("key1") is None

    def test_stats(self):
        """测试统计"""
        cache = LRUCache(max_size=10)

        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("nonexistent")

        stats = cache.stats()

        assert stats['size'] == 1
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert 'hit_rate' in stats

    def test_clear(self):
        """测试清除"""
        cache = LRUCache(max_size=10)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.clear()

        assert cache.get("key1") is None
        stats = cache.stats()
        assert stats['size'] == 0

    def test_delete(self):
        """测试删除"""
        cache = LRUCache(max_size=10)

        cache.set("key1", "value1")

        assert cache.delete("key1") is True
        assert cache.delete("nonexistent") is False

    def test_cleanup_expired(self):
        """测试清理过期"""
        cache = LRUCache(max_size=10, ttl=1)

        cache.set("key1", "value1")
        time.sleep(1.1)
        cache.set("key2", "value2")

        cleaned = cache.cleanup_expired()

        assert cleaned == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"


class TestResponseCache:
    """响应缓存测试"""

    def test_memory_cache(self, tmp_path):
        """测试内存缓存"""
        cache = ResponseCache(ttl=3600)

        cache.set("url1", "content1")
        assert cache.get("url1") == "content1"

    def test_disk_persistence(self, tmp_path):
        """测试磁盘持久化"""
        cache_dir = tmp_path / "cache"
        cache = ResponseCache(ttl=3600, cache_dir=str(cache_dir))

        cache.set("url1", "content1")

        new_cache = ResponseCache(ttl=3600, cache_dir=str(cache_dir))
        assert new_cache.get("url1") == "content1"

    def test_max_memory_size(self, tmp_path):
        """测试内存大小限制"""
        cache = ResponseCache(ttl=3600, max_memory_size=3)

        cache.set("url1", "content1")
        cache.set("url2", "content2")
        cache.set("url3", "content3")
        cache.set("url4", "content4")

        stats = cache.stats()
        assert stats['size'] == 3

    def test_cache_entry_dataclass(self):
        """测试缓存条目数据类"""
        now = time.time()
        entry = CacheEntry(
            url="http://example.com",
            content="content",
            created_at=now,
            expires_at=now + 3600
        )

        assert entry.is_expired() is False

        entry.expires_at = now - 1
        assert entry.is_expired() is True
