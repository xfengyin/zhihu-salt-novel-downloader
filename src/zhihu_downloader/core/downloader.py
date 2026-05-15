"""异步并发下载器 - asyncio + aiohttp"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, ClassVar

import aiohttp

from .cache import ResponseCache
from .rate_limiter import RateLimiter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

logger = logging.getLogger(__name__)


class AsyncDownloader:
    """异步并发下载器 - 支持速率控制、缓存、重试机制"""

    DEFAULT_TIMEOUT: ClassVar[aiohttp.ClientTimeout] = aiohttp.ClientTimeout(
        total=30, connect=10
    )

    def __init__(
        self,
        max_concurrent: int = 3,
        rate_limit: float = 2.0,
        cookies: dict[str, str] | None = None,
        cache_ttl: int = 3600,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> None:
        """
        初始化下载器

        Args:
            max_concurrent: 最大并发数
            rate_limit: 每秒请求数限制
            cookies: Cookie字典
            cache_ttl: 缓存有效期（秒）
            timeout: 请求超时配置
        """
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limiter = RateLimiter(rate_limit)
        self._cache = ResponseCache(ttl=cache_ttl)
        self._cookies = cookies or {}
        self._session: aiohttp.ClientSession | None = None
        self._timeout = timeout or self.DEFAULT_TIMEOUT

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                cookies=self._cookies,
            )
        return self._session

    async def close(self) -> None:
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> AsyncIterator[AsyncDownloader]:
        """异步上下文管理器入口"""
        yield self
        await self.close()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """异步上下文管理器退出"""
        await self.close()

    async def fetch(self, url: str, use_cache: bool = True) -> str:
        """
        获取URL内容

        Args:
            url: 目标URL
            use_cache: 是否使用缓存

        Returns:
            HTML内容

        Raises:
            aiohttp.ClientError: 请求失败时抛出
        """
        if use_cache:
            cached = self._cache.get(url)
            if cached:
                logger.debug("缓存命中: %s", url)
                return cached

        await self._rate_limiter.acquire()

        async with self._semaphore:
            session = await self._get_session()
            headers = self._get_mobile_headers()

            try:
                async with session.get(url, headers=headers) as response:
                    await self._handle_response(response)
                    content = await response.text()

                    if use_cache:
                        self._cache.set(url, content)

                    return content

            except aiohttp.ClientError as e:
                logger.error("请求失败 %s: %s", url, e)
                raise

    async def fetch_with_retry(
        self,
        url: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
        use_cache: bool = True,
    ) -> str:
        """
        带重试的获取

        Args:
            url: 目标URL
            max_retries: 最大重试次数
            base_delay: 基础延迟（秒）
            use_cache: 是否使用缓存

        Returns:
            HTML内容

        Raises:
            aiohttp.ClientError: 所有重试失败后抛出
        """
        last_error: BaseException | None = None

        for attempt in range(max_retries):
            try:
                return await self.fetch(url, use_cache=(use_cache and attempt == 0))
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "请求失败，%.1fs后重试... (%d/%d)", delay, attempt + 1, max_retries
                    )
                    await asyncio.sleep(delay)

        msg = f"获取失败 {url}，已重试 {max_retries} 次"
        raise type(last_error)(msg) if last_error else RuntimeError(msg)

    async def fetch_multiple(
        self,
        urls: Sequence[str],
        use_cache: bool = True,
    ) -> dict[str, str]:
        """
        批量获取URL内容

        Args:
            urls: URL列表
            use_cache: 是否使用缓存

        Returns:
            URL到内容的映射
        """
        tasks = [
            self.fetch_with_retry(url, use_cache=use_cache)
            for url in urls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, str] = {}
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.error("获取失败 %s: %s", url, result)
            else:
                output[url] = result

        return output

    async def _handle_response(self, response: aiohttp.ClientResponse) -> None:
        """处理响应状态码"""
        status = response.status

        if status == 200:
            return
        elif status == 403:
            msg = "403 Forbidden - 可能被反爬限制"
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message=msg,
            )
        elif status == 429:
            msg = "429 Too Many Requests - 请求过于频繁"
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message=msg,
            )
        elif status == 500:
            msg = "500 Internal Server Error"
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message=msg,
            )
        elif status == 404:
            msg = "404 Not Found - 资源不存在"
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message=msg,
            )
        else:
            msg = f"HTTP {status}"
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message=msg,
            )

    def _get_mobile_headers(self) -> dict[str, str]:
        """获取移动端请求头"""
        return {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()

    @property
    def cache_stats(self) -> dict[str, int]:
        """缓存统计"""
        return self._cache.stats()
