"""核心模块测试"""

import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

from core.downloader import AsyncDownloader
from core.rate_limiter import RateLimiter
from core.cache import ResponseCache


class TestAsyncDownloader:
    """异步下载器测试"""

    @pytest.fixture
    def downloader(self):
        return AsyncDownloader(max_concurrent=2, rate_limit=5.0)

    @pytest.mark.asyncio
    async def test_fetch_success(self, downloader):
        """测试成功获取"""
        downloader._cache.set('http://test.com', '<html>test</html>')
        result = downloader._cache.get('http://test.com')
        assert result == '<html>test</html>'

    def test_rate_limiter_acquire(self):
        """测试速率限制器"""
        limiter = RateLimiter(rate=5.0, burst=5)

        assert limiter.available_tokens >= 4

    def test_rate_limiter_reset(self):
        """测试速率限制器重置"""
        limiter = RateLimiter(rate=5.0, burst=5)
        limiter._tokens = 1

        limiter.reset()
        assert limiter.available_tokens == 5


class TestRateLimiter:
    """速率限制器测试"""

    @pytest.mark.asyncio
    async def test_acquire_tokens(self):
        """测试获取令牌"""
        limiter = RateLimiter(rate=10.0, burst=10)
        await limiter.acquire(1)
        assert limiter.available_tokens < 10

    def test_reset(self):
        """测试重置"""
        limiter = RateLimiter(rate=5.0, burst=5)
        limiter._tokens = 0
        limiter.reset()
        assert limiter.available_tokens == 5


class TestResponseCache:
    """响应缓存测试"""

    def test_set_and_get(self):
        """测试设置和获取"""
        cache = ResponseCache(ttl=60)
        cache.set('http://test.com', '<html>content</html>')

        result = cache.get('http://test.com')
        assert result == '<html>content</html>'

    def test_cache_miss(self):
        """测试缓存未命中"""
        cache = ResponseCache(ttl=60)
        result = cache.get('http://not-exists.com')
        assert result is None

    def test_clear_cache(self):
        """测试清除缓存"""
        cache = ResponseCache(ttl=60)
        cache.set('http://test.com', '<html>content</html>')
        cache.clear()

        result = cache.get('http://test.com')
        assert result is None

    def test_stats(self):
        """测试缓存统计"""
        cache = ResponseCache(ttl=60)
        cache.set('http://test1.com', '<html>1</html>')
        cache.set('http://test2.com', '<html>2</html>')

        stats = cache.stats()
        assert stats['size'] == 2
        assert 'total_requests' in stats
