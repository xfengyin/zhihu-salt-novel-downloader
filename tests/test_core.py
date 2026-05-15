"""核心模块测试"""

import pytest
from unittest.mock import MagicMock, patch

from zhihu_downloader.core.downloader import AsyncDownloader
from zhihu_downloader.core.rate_limiter import RateLimiter
from zhihu_downloader.core.cache import ResponseCache, CacheEntry


class TestAsyncDownloader:
    """异步下载器测试"""

    @pytest.fixture
    def downloader(self) -> AsyncDownloader:
        return AsyncDownloader(max_concurrent=2, rate_limit=5.0)

    def test_init(self, downloader: AsyncDownloader) -> None:
        """测试初始化"""
        assert downloader.max_concurrent == 2
        assert downloader._rate_limiter.rate == 5.0

    def test_cache_operations(self, downloader: AsyncDownloader) -> None:
        """测试缓存操作"""
        downloader._cache.set("http://test.com", "<html>test</html>")
        result = downloader._cache.get("http://test.com")
        assert result == "<html>test</html>"

    def test_cache_clear(self, downloader: AsyncDownloader) -> None:
        """测试清除缓存"""
        downloader._cache.set("http://test1.com", "<html>1</html>")
        downloader._cache.set("http://test2.com", "<html>2</html>")
        downloader.clear_cache()
        assert downloader._cache.get("http://test1.com") is None
        assert downloader._cache.get("http://test2.com") is None

    def test_cache_stats(self, downloader: AsyncDownloader) -> None:
        """测试缓存统计"""
        downloader._cache.set("http://test.com", "<html>test</html>")
        downloader._cache.get("http://test.com")
        downloader._cache.get("http://not-exist.com")
        stats = downloader.cache_stats
        assert stats["total"] == 1
        assert stats["hits"] == 1
        assert stats["misses"] == 1


class TestRateLimiter:
    """速率限制器测试"""

    @pytest.mark.asyncio
    async def test_acquire_tokens(self) -> None:
        """测试获取令牌"""
        limiter = RateLimiter(rate=10.0, burst=10)
        initial_tokens = limiter.available_tokens
        await limiter.acquire(1)
        assert limiter.available_tokens < initial_tokens

    def test_reset(self) -> None:
        """测试重置"""
        limiter = RateLimiter(rate=5.0, burst=5)
        limiter._tokens = 0
        limiter.reset()
        assert limiter.available_tokens == 5

    def test_available_tokens_calculation(self) -> None:
        """测试可用令牌计算"""
        limiter = RateLimiter(rate=10.0, burst=5)
        assert limiter.available_tokens <= 5


class TestResponseCache:
    """响应缓存测试"""

    def test_set_and_get(self) -> None:
        """测试设置和获取"""
        cache = ResponseCache(ttl=60)
        cache.set("http://test.com", "<html>content</html>")
        result = cache.get("http://test.com")
        assert result == "<html>content</html>"

    def test_cache_miss(self) -> None:
        """测试缓存未命中"""
        cache = ResponseCache(ttl=60)
        result = cache.get("http://not-exists.com")
        assert result is None

    def test_cache_expiration(self) -> None:
        """测试缓存过期"""
        cache = ResponseCache(ttl=0)
        cache.set("http://test.com", "<html>content</html>")
        result = cache.get("http://test.com")
        assert result is None

    def test_delete(self) -> None:
        """测试删除"""
        cache = ResponseCache(ttl=60)
        cache.set("http://test.com", "<html>content</html>")
        assert cache.delete("http://test.com") is True
        assert cache.get("http://test.com") is None

    def test_clear(self) -> None:
        """测试清除"""
        cache = ResponseCache(ttl=60)
        cache.set("http://test1.com", "<html>1</html>")
        cache.set("http://test2.com", "<html>2</html>")
        cache.clear()
        assert cache.stats()["total"] == 0

    def test_stats(self) -> None:
        """测试统计"""
        cache = ResponseCache(ttl=60)
        cache.set("http://test1.com", "<html>1</html>")
        cache.set("http://test2.com", "<html>2</html>")
        cache.get("http://test1.com")
        cache.get("http://test3.com")
        stats = cache.stats()
        assert stats["total"] == 2
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_cleanup_expired(self) -> None:
        """测试清理过期缓存"""
        cache = ResponseCache(ttl=0)
        cache.set("http://test1.com", "<html>1</html>")
        cache.set("http://test2.com", "<html>2</html>")
        count = cache.cleanup_expired()
        assert count == 2


class TestCacheEntry:
    """缓存条目测试"""

    def test_is_expired_false(self) -> None:
        """测试未过期"""
        entry = CacheEntry("<html>content</html>", 3600)
        assert entry.is_expired() is False

    def test_is_expired_true(self) -> None:
        """测试已过期"""
        entry = CacheEntry("<html>content</html>", 0)
        assert entry.is_expired() is True
