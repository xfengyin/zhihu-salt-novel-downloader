"""异步并发下载器 - asyncio + aiohttp"""

import asyncio
import logging
from typing import Optional, Dict, Any
from urllib.parse import urljoin

import aiohttp

from .cache import ResponseCache
from .rate_limiter import RateLimiter
from utils.retry import async_retry
from utils.user_agent import UserAgentRotator


logger = logging.getLogger(__name__)


class AsyncDownloader:
    """异步并发下载器"""
    
    def __init__(
        self,
        max_concurrent: int = 3,
        rate_limit: float = 2.0,
        cookies: Optional[Dict[str, str]] = None,
        cache_ttl: int = 3600
    ):
        """
        初始化下载器
        
        Args:
            max_concurrent: 最大并发数
            rate_limit: 每秒请求数限制
            cookies: Cookie字典
            cache_ttl: 缓存有效期（秒）
        """
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limiter = RateLimiter(rate_limit)
        self._cache = ResponseCache(ttl=cache_ttl)
        self._cookies = cookies or {}
        self._ua_rotator = UserAgentRotator()
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建会话"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                cookies=self._cookies
            )
        return self._session
    
    async def close(self):
        """关闭会话"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def fetch(self, url: str, use_cache: bool = True) -> str:
        """
        获取URL内容
        
        Args:
            url: 目标URL
            use_cache: 是否使用缓存
            
        Returns:
            HTML内容
        """
        # 检查缓存
        if use_cache:
            cached = self._cache.get(url)
            if cached:
                logger.debug(f"缓存命中: {url}")
                return cached
        
        # 速率限制
        await self._rate_limiter.acquire()
        
        async with self._semaphore:
            session = await self._get_session()
            headers = self._ua_rotator.get_mobile_headers()
            
            try:
                async with session.get(url, headers=headers) as response:
                    await self._handle_response(response, url)
                    content = await response.text()
                    
                    # 存入缓存
                    if use_cache:
                        self._cache.set(url, content)
                    
                    return content
                    
            except aiohttp.ClientError as e:
                logger.error(f"请求失败 {url}: {e}")
                raise
    
    async def fetch_with_retry(
        self,
        url: str,
        max_retries: int = 3,
        base_delay: float = 1.0
    ) -> str:
        """
        带重试的获取
        
        Args:
            url: 目标URL
            max_retries: 最大重试次数
            base_delay: 基础延迟（秒）
            
        Returns:
            HTML内容
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await self.fetch(url, use_cache=(attempt == 0))
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    # 指数退避
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"请求失败，{delay}s后重试... ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(delay)
        
        raise last_error or Exception("Unknown error")
    
    async def fetch_multiple(
        self,
        urls: list,
        use_cache: bool = True
    ) -> Dict[str, str]:
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
        
        output = {}
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.error(f"获取失败 {url}: {result}")
            else:
                output[url] = result
        
        return output
    
    async def _handle_response(
        self,
        response: aiohttp.ClientResponse,
        url: str
    ):
        """处理响应状态码"""
        status = response.status
        
        if status == 200:
            return
        elif status == 403:
            raise Exception(f"403 Forbidden - 可能被反爬限制")
        elif status == 429:
            raise Exception(f"429 Too Many Requests - 请求过于频繁")
        elif status == 500:
            raise Exception(f"500 Internal Server Error")
        elif status == 404:
            raise Exception(f"404 Not Found - 资源不存在")
        else:
            raise Exception(f"HTTP {status}")
    
    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()
    
    @property
    def cache_stats(self) -> Dict[str, int]:
        """缓存统计"""
        return self._cache.stats()
