"""异步并发下载器 - asyncio + aiohttp"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin
from contextlib import asynccontextmanager

import aiohttp

from .cache import ResponseCache
from .rate_limiter import RateLimiter
from utils.retry import async_retry
from auth.user_agent import UserAgentRotator
from utils.exceptions import (
    NetworkError,
    HTTPError,
    RateLimitError,
    AuthenticationError,
    NotFoundError,
    DownloaderError
)


logger = logging.getLogger(__name__)


class AsyncDownloader:
    """异步并发下载器"""

    def __init__(
        self,
        max_concurrent: int = 3,
        rate_limit: float = 2.0,
        cookies: Optional[Dict[str, str]] = None,
        cache_ttl: int = 3600,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: int = 30
    ):
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limiter = RateLimiter(rate_limit)
        self._cache = ResponseCache(ttl=cache_ttl)
        self._cookies = cookies or {}
        self._ua_rotator = UserAgentRotator()
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self._timeout = aiohttp.ClientTimeout(total=timeout, connect=10)

    @asynccontextmanager
    async def _get_session(self):
        """获取或创建会话的上下文管理器"""
        async with self._session_lock:
            if self._session is None or self._session.closed:
                connector = aiohttp.TCPConnector(
                    limit=100,
                    limit_per_host=10,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True
                )
                self._session = aiohttp.ClientSession(
                    timeout=self._timeout,
                    cookies=self._cookies,
                    connector=connector
                )
        yield self._session

    async def close(self):
        """关闭会话"""
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None

    async def fetch(self, url: str, use_cache: bool = True) -> str:
        """获取URL内容"""
        if use_cache:
            cached = self._cache.get(url)
            if cached:
                logger.debug(f"缓存命中: {url}")
                return cached

        await self._rate_limiter.acquire()

        async with self._semaphore:
            async with self._get_session() as session:
                headers = self._ua_rotator.get_mobile_headers()

                try:
                    async with session.get(url, headers=headers) as response:
                        await self._handle_response(response, url)
                        content = await response.text()

                        if use_cache:
                            self._cache.set(url, content)

                        return content

                except aiohttp.ClientError as e:
                    logger.error(f"请求失败 {url}: {e}")
                    raise NetworkError(
                        message=str(e),
                        url=url
                    ) from e

    async def fetch_with_retry(
        self,
        url: str,
        max_retries: Optional[int] = None,
        base_delay: Optional[float] = None
    ) -> str:
        """带重试的获取"""
        max_retries = max_retries if max_retries is not None else self.max_retries
        base_delay = base_delay if base_delay is not None else self.retry_delay

        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                return await self.fetch(url, use_cache=(attempt == 0))
            except (RateLimitError, NetworkError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"请求失败，{delay}s后重试... ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
            except AuthenticationError:
                raise
            except NotFoundError:
                raise
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"请求失败，{delay}s后重试... ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)

        raise DownloaderError(
            message=f"重试{max_retries}次后仍失败: {last_error}",
            url=url,
            retry_count=max_retries
        ) from last_error

    async def fetch_multiple(
        self,
        urls: List[str],
        use_cache: bool = True,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Any]:
        """批量获取URL内容"""
        results: Dict[str, Any] = {}
        total = len(urls)

        async def fetch_one(url: str, index: int) -> tuple:
            try:
                content = await self.fetch_with_retry(url)
                if progress_callback:
                    await progress_callback(index, total)
                return (url, {'success': True, 'content': content})
            except Exception as e:
                logger.error(f"获取失败 {url}: {e}")
                if progress_callback:
                    await progress_callback(index, total)
                return (url, {'success': False, 'error': str(e)})

        tasks = [fetch_one(url, i) for i, url in enumerate(urls)]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for result in completed:
            if isinstance(result, Exception):
                logger.error(f"任务异常: {result}")
                continue
            url, data = result
            results[url] = data

        return results

    async def _handle_response(
        self,
        response: aiohttp.ClientResponse,
        url: str
    ) -> None:
        """处理响应状态码"""
        status = response.status

        if status == 200:
            return
        elif status == 403:
            raise AuthenticationError(
                message="403 Forbidden - 可能被反爬限制或认证过期",
                url=url
            )
        elif status == 429:
            raise RateLimitError(url=url)
        elif status == 500:
            raise HTTPError(
                status_code=500,
                message="500 Internal Server Error",
                url=url
            )
        elif status == 404:
            raise NotFoundError(url=url)
        else:
            raise HTTPError(
                status_code=status,
                message=f"HTTP {status}",
                url=url
            )

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return self._cache.stats()

    def get_rate_limiter_stats(self) -> Dict[str, float]:
        """获取速率限制器状态"""
        return {
            'available_tokens': self._rate_limiter.available_tokens,
            'rate': self._rate_limiter.rate,
            'burst': self._rate_limiter.burst
        }

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            'status': 'healthy',
            'session_active': self._session is not None and not self._session.closed,
            'cache_stats': self.get_cache_stats(),
            'rate_limiter': self.get_rate_limiter_stats(),
            'semaphore_value': self._semaphore._value
        }
