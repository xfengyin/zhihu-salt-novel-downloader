"""异步智能下载器 - 集成UA池+代理池+重试+熔断+限流"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

import aiohttp

from .cache import ResponseCache
from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from .rate_limiter import RateLimiter

if TYPE_CHECKING:
    from aiohttp import ClientResponse

logger = logging.getLogger(__name__)


class IFetcher(Protocol):
    """下载器协议 - 定义 fetch() 接口"""

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
        proxy: str | None = None,
        max_retries: int = 3,
    ) -> str:
        """
        获取URL内容

        Args:
            url: 目标URL
            headers: 自定义请求头
            use_cache: 是否使用缓存
            proxy: 代理地址
            max_retries: 最大重试次数

        Returns:
            HTML内容

        Raises:
            Exception: 请求失败时抛出
        """
        ...


class AsyncDownloader:
    """异步智能下载器 - 支持UA池、代理池、重试、熔断、限流"""

    DEFAULT_TIMEOUT: ClassVar[aiohttp.ClientTimeout] = aiohttp.ClientTimeout(
        total=30, connect=10
    )

    DEFAULT_UA_POOL: ClassVar[list[str]] = [
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; SM-S918B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.6099.144 Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.6099.144 Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.6099.144 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.6099.144 Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Safari/605.1.15"
        ),
    ]

    DEFAULT_HEADERS: ClassVar[dict[str, str]] = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Cache-Control": "max-age=0",
    }

    def __init__(
        self,
        max_concurrent: int = 3,
        min_concurrent: int = 1,
        rate_limit: float = 2.0,
        cookies: dict[str, str] | None = None,
        cache_ttl: int = 3600,
        timeout: aiohttp.ClientTimeout | None = None,
        ua_pool: list[str] | None = None,
        proxy_pool: list[str] | None = None,
        mirror_urls: dict[str, str] | None = None,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
    ) -> None:
        """
        初始化智能下载器

        Args:
            max_concurrent: 最大并发数
            min_concurrent: 最小并发数（自适应降级下限）
            rate_limit: 每秒请求数限制
            cookies: Cookie字典
            cache_ttl: 缓存有效期（秒）
            timeout: 请求超时配置
            ua_pool: User-Agent池
            proxy_pool: 代理地址池
            mirror_urls: 备用镜像URL映射
            circuit_failure_threshold: 熔断器失败阈值
            circuit_recovery_timeout: 熔断器恢复超时时间
        """
        self.max_concurrent = max_concurrent
        self.min_concurrent = min_concurrent
        self._current_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limiter = RateLimiter(rate_limit)
        self._cache = ResponseCache(ttl=cache_ttl)
        self._cookies = cookies or {}
        self._ua_pool = ua_pool or self.DEFAULT_UA_POOL.copy()
        self._proxy_pool = proxy_pool or []
        self._mirror_urls = mirror_urls or {}
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_failure_threshold,
            recovery_timeout=circuit_recovery_timeout,
        )
        self._session: aiohttp.ClientSession | None = None
        self._timeout = timeout or self.DEFAULT_TIMEOUT
        self._last_5xx_time: float = 0.0
        self._concurrent_degrade_lock: asyncio.Lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建会话"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                cookies=self._cookies,
                connector=aiohttp.TCPConnector(ssl=False),
            )
        return self._session

    async def close(self) -> None:
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> AsyncDownloader:
        """异步上下文管理器入口"""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """异步上下文管理器退出"""
        await self.close()

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
        proxy: str | None = None,
        max_retries: int = 3,
    ) -> str:
        """
        获取URL内容（支持自定义headers、缓存、代理、重试）

        Args:
            url: 目标URL
            headers: 自定义请求头
            use_cache: 是否使用缓存
            proxy: 代理地址（优先使用指定代理，否则从代理池随机选择）
            max_retries: 最大重试次数

        Returns:
            HTML内容

        Raises:
            Exception: 所有重试失败后抛出
        """
        if use_cache:
            cached = self._cache.get(url)
            if cached:
                logger.debug("缓存命中: %s", url)
                return cached

        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                result = await self._fetch_once(
                    url,
                    headers=headers,
                    proxy=proxy,
                    attempt=attempt,
                )
                if use_cache:
                    self._cache.set(url, result)
                return result

            except CircuitBreakerOpenError:
                logger.warning("熔断器OPEN，尝试备用镜像: %s", url)
                mirror_url = self._mirror_urls.get(url)
                if mirror_url:
                    try:
                        result = await self._fetch_once(
                            mirror_url,
                            headers=headers,
                            proxy=proxy,
                            attempt=attempt,
                        )
                        if use_cache:
                            self._cache.set(url, result)
                            self._cache.set(mirror_url, result)
                        return result
                    except Exception as mirror_err:
                        last_error = mirror_err

                if use_cache:
                    cached = self._cache.get(url)
                    if cached:
                        logger.warning("使用缓存兜底: %s", url)
                        return cached

                raise

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = self._calculate_backoff_delay(attempt)
                    logger.warning(
                        "请求失败，%.1fs后重试... (%d/%d) - %s",
                        delay,
                        attempt + 1,
                        max_retries,
                        url,
                    )
                    await asyncio.sleep(delay)

        if last_error and use_cache:
            cached = self._cache.get(url)
            if cached:
                logger.warning("最终使用缓存兜底: %s", url)
                return cached

        msg = f"获取失败 {url}，已重试 {max_retries} 次"
        raise type(last_error)(msg) if last_error else RuntimeError(msg)

    async def _fetch_once(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        attempt: int = 0,
    ) -> str:
        """单次请求获取URL内容"""
        await self._rate_limiter.acquire()

        async with self._semaphore:
            session = await self._get_session()
            request_headers = self._build_headers(headers)
            request_proxy = proxy or self._get_random_proxy()

            try:
                async with self._circuit_breaker.call(
                    session.get,
                    url,
                    headers=request_headers,
                    proxy=request_proxy,
                ) as response:
                    await self._handle_response(response, url)
                    content = await response.text()
                    return content

            except aiohttp.ClientError as e:
                logger.error("请求失败 %s: %s", url, e)
                raise
            except Exception as e:
                logger.error("请求异常 %s: %s", url, e)
                raise

    async def _handle_response(self, response: ClientResponse, url: str) -> None:
        """处理响应状态码，触发相应策略"""
        status = response.status

        if status == 200:
            await self._on_success()
            return

        if status in (403, 429):
            await self._handle_antispam(status, url)
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message=f"{status} - 反爬限制，已触发降级策略",
            )

        if 500 <= status < 600:
            await self._handle_server_error(status, url)
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message=f"{status} - 服务器错误，已触发并发降级",
            )

        if status == 404:
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=status,
                message="404 Not Found - 资源不存在",
            )

        raise aiohttp.ClientResponseError(
            response.request_info,
            response.history,
            status=status,
            message=f"HTTP {status}",
        )

    async def _handle_antispam(self, status: int, url: str) -> None:
        """处理验证码/反爬（403/429）"""
        logger.warning("检测到反爬限制 %d: %s", status, url)

        if self._ua_pool:
            random.shuffle(self._ua_pool)
            logger.info("已随机重排UA池")

        await self._reduce_concurrent()

        if self._proxy_pool:
            logger.info("尝试切换代理，当前代理池大小: %d", len(self._proxy_pool))

    async def _handle_server_error(self, status: int, url: str) -> None:
        """处理服务器错误（5xx），触发自适应并发降级"""
        logger.warning("检测到服务器错误 %d: %s", status, url)
        await self._reduce_concurrent()
        self._last_5xx_time = time.monotonic()

    async def _reduce_concurrent(self) -> None:
        """降低并发数（自适应并发降级）"""
        async with self._concurrent_degrade_lock:
            if self._current_concurrent > self.min_concurrent:
                new_concurrent = max(self.min_concurrent, self._current_concurrent // 2)
                self._current_concurrent = new_concurrent
                self._semaphore = asyncio.Semaphore(new_concurrent)
                logger.warning(
                    "并发降级: %d -> %d",
                    self._current_concurrent * 2,
                    new_concurrent,
                )

    async def _on_success(self) -> None:
        """请求成功回调，恢复并发数"""
        now = time.monotonic()
        if (
            now - self._last_5xx_time > 60
            and self._current_concurrent < self.max_concurrent
        ):
            async with self._concurrent_degrade_lock:
                if self._current_concurrent < self.max_concurrent:
                    new_concurrent = min(
                        self.max_concurrent,
                        self._current_concurrent * 2,
                    )
                    self._current_concurrent = new_concurrent
                    self._semaphore = asyncio.Semaphore(new_concurrent)
                    logger.info(
                        "并发恢复: %d -> %d",
                        self._current_concurrent // 2,
                        new_concurrent,
                    )

    def _build_headers(self, custom_headers: dict[str, str] | None = None) -> dict[str, str]:
        """构建请求头，随机选择UA"""
        headers = self.DEFAULT_HEADERS.copy()
        headers["User-Agent"] = random.choice(self._ua_pool)
        if custom_headers:
            headers.update(custom_headers)
        return headers

    def _get_random_proxy(self) -> str | None:
        """从代理池随机选择代理"""
        if not self._proxy_pool:
            return None
        return random.choice(self._proxy_pool)

    def _calculate_backoff_delay(self, attempt: int, base_delay: float = 1.0) -> float:
        """
        抖动指数退避算法 - 避免雷鸣效应

        Args:
            attempt: 当前重试次数（从0开始）
            base_delay: 基础延迟（秒）

        Returns:
            退避延迟时间（秒）
        """
        jitter = random.uniform(0, base_delay)
        delay = base_delay * (2**attempt) + jitter
        return min(delay, 30.0)

    async def fetch_multiple(
        self,
        urls: Sequence[str],
        *,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
        proxy: str | None = None,
        max_retries: int = 3,
    ) -> dict[str, str]:
        """
        批量获取URL内容

        Args:
            urls: URL列表
            headers: 自定义请求头
            use_cache: 是否使用缓存
            proxy: 代理地址
            max_retries: 最大重试次数

        Returns:
            URL到内容的映射
        """
        tasks = [
            self.fetch(
                url,
                headers=headers,
                use_cache=use_cache,
                proxy=proxy,
                max_retries=max_retries,
            )
            for url in urls
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, str] = {}
        for url, result in zip(urls, results, strict=True):
            if isinstance(result, Exception):
                logger.error("获取失败 %s: %s", url, result)
            else:
                output[url] = str(result)

        return output

    def add_proxy(self, proxy: str) -> None:
        """添加代理到代理池"""
        if proxy not in self._proxy_pool:
            self._proxy_pool.append(proxy)
            logger.info("已添加代理: %s", proxy)

    def remove_proxy(self, proxy: str) -> None:
        """从代理池移除代理"""
        if proxy in self._proxy_pool:
            self._proxy_pool.remove(proxy)
            logger.info("已移除代理: %s", proxy)

    def add_ua(self, ua: str) -> None:
        """添加UA到UA池"""
        if ua not in self._ua_pool:
            self._ua_pool.append(ua)
            logger.info("已添加UA: %s", ua[:50] + "..." if len(ua) > 50 else ua)

    def add_mirror(self, original_url: str, mirror_url: str) -> None:
        """添加备用镜像"""
        self._mirror_urls[original_url] = mirror_url
        logger.info("已添加镜像: %s -> %s", original_url, mirror_url)

    def clear_cache(self) -> None:
        """清除缓存"""
        self._cache.clear()

    def reset_circuit_breaker(self) -> None:
        """重置熔断器"""
        self._circuit_breaker.reset()

    @property
    def cache_stats(self) -> dict[str, int]:
        """缓存统计"""
        return self._cache.stats()

    @property
    def circuit_state(self) -> str:
        """熔断器状态"""
        return self._circuit_breaker.state.value

    @property
    def current_concurrent(self) -> int:
        """当前并发数"""
        return self._current_concurrent

    @property
    def proxy_pool_size(self) -> int:
        """代理池大小"""
        return len(self._proxy_pool)

    @property
    def ua_pool_size(self) -> int:
        """UA池大小"""
        return len(self._ua_pool)


__all__ = ["AsyncDownloader", "IFetcher"]
