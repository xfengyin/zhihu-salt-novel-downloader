"""健康检查和监控模块"""

import time
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
from enum import Enum


logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    status: str
    timestamp: float
    components: Dict[str, Any]
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        return f"HealthCheck({self.status}, components={list(self.components.keys())})"


class HealthChecker:
    """健康检查器"""

    def __init__(self):
        self._start_time = time.time()
        self._checks: List[callable] = []

    def register_check(self, name: str, check_func: callable) -> None:
        """注册健康检查项"""
        self._checks.append((name, check_func))

    async def check_all(self) -> HealthCheckResult:
        """执行所有健康检查"""
        components = {}
        all_healthy = True

        for name, check_func in self._checks:
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()

                components[name] = result

                if isinstance(result, dict) and result.get('status') != 'ok':
                    all_healthy = False

            except Exception as e:
                components[name] = {
                    'status': 'error',
                    'error': str(e)
                }
                all_healthy = False

        if all_healthy:
            status = HealthStatus.HEALTHY.value
        else:
            status = HealthStatus.DEGRADED.value

        return HealthCheckResult(
            status=status,
            timestamp=time.time(),
            components=components
        )

    def get_uptime(self) -> float:
        """获取运行时间（秒）"""
        return time.time() - self._start_time


import asyncio


class MetricsCollector:
    """指标收集器"""

    def __init__(self):
        self._downloads_total = 0
        self._downloads_success = 0
        self._downloads_failed = 0
        self._bytes_downloaded = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._start_time = time.time()
        self._lock = asyncio.Lock()

    async def record_download(self, success: bool, bytes_count: int = 0) -> None:
        """记录下载"""
        async with self._lock:
            self._downloads_total += 1
            if success:
                self._downloads_success += 1
                self._bytes_downloaded += bytes_count
            else:
                self._downloads_failed += 1

    async def record_cache_hit(self) -> None:
        """记录缓存命中"""
        async with self._lock:
            self._cache_hits += 1

    async def record_cache_miss(self) -> None:
        """记录缓存未命中"""
        async with self._lock:
            self._cache_misses += 1

    async def get_metrics(self) -> Dict[str, Any]:
        """获取指标"""
        async with self._lock:
            total_cache_requests = self._cache_hits + self._cache_misses
            cache_hit_rate = self._cache_hits / total_cache_requests if total_cache_requests > 0 else 0

            return {
                'downloads': {
                    'total': self._downloads_total,
                    'success': self._downloads_success,
                    'failed': self._downloads_failed,
                    'success_rate': f"{self._downloads_success / self._downloads_total * 100:.2f}%" if self._downloads_total > 0 else "0%"
                },
                'bandwidth': {
                    'bytes_downloaded': self._bytes_downloaded,
                    'mb_downloaded': f"{self._bytes_downloaded / 1024 / 1024:.2f}"
                },
                'cache': {
                    'hits': self._cache_hits,
                    'misses': self._cache_misses,
                    'hit_rate': f"{cache_hit_rate * 100:.2f}%"
                },
                'uptime': {
                    'seconds': time.time() - self._start_time,
                    'started_at': self._start_time
                }
            }


class ProgressTracker:
    """进度跟踪器"""

    def __init__(self, total: int):
        self.total = total
        self.completed = 0
        self.failed = 0
        self.start_time = time.time()
        self._lock = asyncio.Lock()

    async def update(self, success: bool) -> None:
        """更新进度"""
        async with self._lock:
            self.completed += 1
            if not success:
                self.failed += 1

    def get_progress(self) -> Dict[str, Any]:
        """获取进度"""
        elapsed = time.time() - self.start_time
        remaining = self.total - self.completed

        rate = self.completed / elapsed if elapsed > 0 else 0
        eta = remaining / rate if rate > 0 else 0

        return {
            'total': self.total,
            'completed': self.completed,
            'failed': self.failed,
            'success': self.completed - self.failed,
            'progress': f"{(self.completed / self.total * 100):.1f}%" if self.total > 0 else "0%",
            'rate': f"{rate:.2f}/s",
            'elapsed': f"{elapsed:.1f}s",
            'eta': f"{eta:.1f}s"
        }


_global_health_checker = HealthChecker()
_global_metrics_collector = MetricsCollector()


def get_health_checker() -> HealthChecker:
    """获取全局健康检查器"""
    return _global_health_checker


def get_metrics_collector() -> MetricsCollector:
    """获取全局指标收集器"""
    return _global_metrics_collector
