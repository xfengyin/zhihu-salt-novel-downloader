"""下载器测试"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from core.downloader import AsyncDownloader
from utils.exceptions import (
    NetworkError,
    HTTPError,
    RateLimitError,
    AuthenticationError,
    NotFoundError,
    DownloaderError
)


class TestAsyncDownloader:
    """异步下载器测试"""

    @pytest.fixture
    def downloader(self):
        return AsyncDownloader(max_concurrent=3, rate_limit=2.0)

    @pytest.mark.asyncio
    async def test_initialization(self, downloader):
        """测试初始化"""
        assert downloader.max_concurrent == 3
        assert downloader._rate_limiter.rate == 2.0
        assert downloader._session is None

    @pytest.mark.asyncio
    async def test_close_session(self, downloader):
        """测试关闭会话"""
        await downloader.close()
        assert downloader._session is None

    @pytest.mark.asyncio
    async def test_cache_operations(self, downloader):
        """测试缓存操作"""
        downloader._cache.set("http://test.com", "test content")

        content = downloader._cache.get("http://test.com")
        assert content == "test content"

    def test_cache_stats(self, downloader):
        """测试缓存统计"""
        stats = downloader.get_cache_stats()
        assert 'size' in stats
        assert 'max_size' in stats

    def test_rate_limiter_stats(self, downloader):
        """测试速率限制器统计"""
        stats = downloader.get_rate_limiter_stats()
        assert 'available_tokens' in stats
        assert 'rate' in stats

    @pytest.mark.asyncio
    async def test_health_check(self, downloader):
        """测试健康检查"""
        health = await downloader.health_check()

        assert health['status'] == 'healthy'
        assert 'cache_stats' in health
        assert 'rate_limiter' in health


class TestExceptionHandling:
    """异常处理测试"""

    def test_network_error(self):
        """测试网络错误"""
        error = NetworkError(
            message="Connection timeout",
            url="http://example.com"
        )
        assert error.url == "http://example.com"
        assert error.message == "Connection timeout"

    def test_http_error(self):
        """测试HTTP错误"""
        error = HTTPError(
            status_code=500,
            message="Internal Server Error",
            url="http://example.com"
        )
        assert error.status_code == 500
        assert error.url == "http://example.com"

    def test_rate_limit_error(self):
        """测试速率限制错误"""
        error = RateLimitError(url="http://example.com")
        assert error.status_code == 429
        assert "频率" in error.message or "降低" in error.message

    def test_authentication_error(self):
        """测试认证错误"""
        error = AuthenticationError(url="http://example.com")
        assert error.status_code == 403

    def test_not_found_error(self):
        """测试未找到错误"""
        error = NotFoundError(url="http://example.com")
        assert error.status_code == 404

    def test_downloader_error_with_retry(self):
        """测试下载器错误包含重试信息"""
        error = DownloaderError(
            message="Max retries exceeded",
            url="http://example.com",
            retry_count=3
        )
        assert error.retry_count == 3
