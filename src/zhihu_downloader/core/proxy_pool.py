"""代理池 - 支持HTTP/HTTPS/SOCKS5代理，带健康检查和LRU缓存"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

logger = logging.getLogger(__name__)


class Proxy:
    """代理信息"""

    __slots__ = (
        "fail_count",
        "host",
        "is_healthy",
        "last_success",
        "password",
        "port",
        "protocol",
        "url",
        "username",
        "weight",
    )

    def __init__(self, url: str) -> None:
        self.url = url
        self.protocol = self._parse_protocol(url)
        self.host, self.port, self.username, self.password = self._parse_url(url)
        self.fail_count = 0
        self.last_success = 0.0
        self.is_healthy = True
        self.weight = 1.0

    def _parse_protocol(self, url: str) -> str:
        """解析代理协议"""
        if url.startswith("socks5://"):
            return "socks5"
        elif url.startswith("https://"):
            return "https"
        elif url.startswith("http://"):
            return "http"
        else:
            return "http"

    def _parse_url(self, url: str) -> tuple[str, int, str | None, str | None]:
        """解析代理URL"""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if self.protocol == "https" else 8080)
        username = parsed.username
        password = parsed.password
        return host, port, username, password

    def to_aiohttp_proxy(self) -> str:
        """转换为aiohttp可用的代理格式"""
        return self.url

    def record_success(self) -> None:
        """记录成功使用"""
        self.fail_count = 0
        self.last_success = time.time()
        self.is_healthy = True
        self.weight = min(self.weight + 0.1, 2.0)

    def record_failure(self) -> None:
        """记录失败使用"""
        self.fail_count += 1
        self.weight = max(self.weight - 0.2, 0.1)

    def mark_unhealthy(self) -> None:
        """标记为不健康"""
        self.is_healthy = False


class ProxyPool:
    """代理池 - LRU缓存代理，支持健康检查"""

    def __init__(
        self,
        max_size: int = 100,
        max_failures: int = 3,
        health_check_interval: int = 60,
        health_check_timeout: int = 10,
    ) -> None:
        """
        初始化代理池

        Args:
            max_size: 最大代理数量
            max_failures: 最大失败次数，超过后标记为不可用
            health_check_interval: 健康检查间隔（秒）
            health_check_timeout: 健康检查超时时间（秒）
        """
        self._proxies: OrderedDict[str, Proxy] = OrderedDict()
        self._max_size = max_size
        self._max_failures = max_failures
        self._health_check_interval = health_check_interval
        self._health_check_timeout = health_check_timeout
        self._lock = asyncio.Lock()
        self._health_check_task: asyncio.Task[None] | None = None

    async def start_health_check(self) -> None:
        """启动定时健康检查"""
        if self._health_check_task is not None:
            return

        async def _health_check_loop() -> None:
            while True:
                try:
                    await self.health_check()
                except Exception as e:
                    logger.error("健康检查异常: %s", e)
                await asyncio.sleep(self._health_check_interval)

        self._health_check_task = asyncio.create_task(_health_check_loop())
        logger.info("代理池健康检查已启动，间隔 %d 秒", self._health_check_interval)

    async def stop_health_check(self) -> None:
        """停止定时健康检查"""
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
            logger.info("代理池健康检查已停止")

    def add_proxy(self, proxy_url: str) -> bool:
        """
        添加新代理

        Args:
            proxy_url: 代理URL，如 http://user:pass@host:port

        Returns:
            是否添加成功
        """
        if proxy_url in self._proxies:
            return False

        if len(self._proxies) >= self._max_size:
            oldest_key = next(iter(self._proxies))
            del self._proxies[oldest_key]
            logger.debug("代理池已满，移除最旧代理: %s", oldest_key)

        proxy = Proxy(proxy_url)
        self._proxies[proxy_url] = proxy
        logger.debug("添加代理: %s", proxy_url)
        return True

    def load_from_config(self, config_proxies: Sequence[str]) -> int:
        """
        从配置加载代理列表

        Args:
            config_proxies: 代理URL列表

        Returns:
            添加的代理数量
        """
        count = 0
        for proxy_url in config_proxies:
            if self.add_proxy(proxy_url):
                count += 1
        logger.info("从配置加载了 %d 个代理", count)
        return count

    def acquire(self) -> Proxy | None:
        """
        获取可用代理

        Returns:
            可用代理，如果没有可用代理返回None
        """
        healthy_proxies = [
            proxy for proxy in self._proxies.values()
            if proxy.is_healthy and proxy.fail_count < self._max_failures
        ]

        if not healthy_proxies:
            return None

        proxy = max(healthy_proxies, key=lambda p: p.weight)

        if proxy.url in self._proxies:
            self._proxies.move_to_end(proxy.url)

        logger.debug("获取代理: %s", proxy.url)
        return proxy

    def release(self, proxy: Proxy, ok: bool) -> None:
        """
        释放代理

        Args:
            proxy: 代理对象
            ok: 是否成功使用
        """
        if ok:
            proxy.record_success()
            logger.debug("代理使用成功: %s", proxy.url)
        else:
            proxy.record_failure()
            logger.debug("代理使用失败: %s (失败次数: %d)", proxy.url, proxy.fail_count)

            if proxy.fail_count >= self._max_failures:
                proxy.mark_unhealthy()
                logger.warning("代理标记为不可用: %s", proxy.url)

    async def health_check(self) -> dict[str, Any]:
        """
        执行健康检查

        Returns:
            检查结果统计
        """
        async with self._lock:
            proxies = list(self._proxies.values())

        if not proxies:
            return {"total": 0, "healthy": 0, "unhealthy": 0, "checked": 0}

        results = await asyncio.gather(
            *[self._check_single_proxy(proxy) for proxy in proxies],
            return_exceptions=True,
        )

        healthy_count = 0
        unhealthy_count = 0
        checked_count = 0

        for proxy, result in zip(proxies, results, strict=True):
            checked_count += 1
            if isinstance(result, Exception):
                proxy.mark_unhealthy()
                unhealthy_count += 1
                logger.debug("代理健康检查失败: %s - %s", proxy.url, result)
            else:
                if result:
                    proxy.record_success()
                    healthy_count += 1
                else:
                    proxy.mark_unhealthy()
                    unhealthy_count += 1
                    logger.debug("代理健康检查未通过: %s", proxy.url)

        logger.info(
            "健康检查完成: 总数=%d, 健康=%d, 不健康=%d",
            checked_count,
            healthy_count,
            unhealthy_count,
        )

        return {
            "total": len(proxies),
            "healthy": healthy_count,
            "unhealthy": unhealthy_count,
            "checked": checked_count,
        }

    async def _check_single_proxy(self, proxy: Proxy) -> bool:
        """
        检查单个代理的可用性

        Args:
            proxy: 代理对象

        Returns:
            是否可用
        """
        test_urls = [
            "http://httpbin.org/ip",
            "http://icanhazip.com",
            "http://api.ipify.org",
        ]

        timeout = aiohttp.ClientTimeout(total=self._health_check_timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in test_urls:
                try:
                    async with session.get(url, proxy=proxy.to_aiohttp_proxy()):
                        return True
                except Exception:
                    continue

        return False

    def remove_unhealthy(self) -> int:
        """
        移除所有不健康的代理

        Returns:
            移除的代理数量
        """
        unhealthy_keys = [
            key for key, proxy in self._proxies.items()
            if not proxy.is_healthy
        ]

        for key in unhealthy_keys:
            del self._proxies[key]
            logger.info("移除不可用代理: %s", key)

        return len(unhealthy_keys)

    def clear(self) -> None:
        """清空代理池"""
        self._proxies.clear()
        logger.info("代理池已清空")

    def stats(self) -> dict[str, Any]:
        """
        获取代理池统计信息

        Returns:
            统计信息字典
        """
        total = len(self._proxies)
        healthy = sum(1 for p in self._proxies.values() if p.is_healthy)
        unhealthy = total - healthy
        avg_weight = sum(p.weight for p in self._proxies.values()) / total if total > 0 else 0.0

        return {
            "total": total,
            "healthy": healthy,
            "unhealthy": unhealthy,
            "max_size": self._max_size,
            "max_failures": self._max_failures,
            "avg_weight": round(avg_weight, 2),
        }

    def __iter__(self) -> Iterator[Proxy]:
        """遍历所有代理"""
        return iter(self._proxies.values())

    def __len__(self) -> int:
        """代理数量"""
        return len(self._proxies)

    def __contains__(self, proxy_url: str) -> bool:
        """检查代理是否存在"""
        return proxy_url in self._proxies
