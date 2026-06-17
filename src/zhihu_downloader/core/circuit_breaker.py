"""熔断器

实现三态熔断（CLOSED/OPEN/HALF_OPEN），保护下游服务：
- CLOSED：正常放行，失败累计达到阈值后切换 OPEN
- OPEN：直接快速失败，拒绝调用，等待 recovery_timeout 后切 HALF_OPEN
- HALF_OPEN：放行一次试探调用，成功则 CLOSED，失败则重新 OPEN

使用 asyncio.Lock 保证并发场景下状态变更的原子性。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from zhihu_downloader.utils.logging_setup import get_logger
from zhihu_downloader.utils.trace_context import get_trace_id

logger = get_logger(__name__)


class CircuitState(str, Enum):
    """熔断状态枚举"""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(RuntimeError):
    """熔断器处于 OPEN 状态时调用被拒绝"""


class CircuitBreaker:
    """
    异步熔断器

    用法:
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        result = await cb.call(fetch, url)

    线程/协程安全：内部使用 asyncio.Lock 保护状态变更。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        """
        初始化熔断器

        Args:
            failure_threshold: 连续失败次数阈值，达到后熔断
            recovery_timeout: OPEN 状态持续时间（秒），过后进入 HALF_OPEN
            expected_exception: 视为失败的异常类型元组
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._expected_exception = expected_exception

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """当前熔断状态（读取时可能触发 OPEN -> HALF_OPEN 的惰性迁移）"""
        # 不持锁读取，状态迁移在 call 路径中由锁保护；这里仅作只读快照
        if self._state is CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def is_open(self) -> bool:
        """是否处于 OPEN（含已超时即将 HALF_OPEN 的过渡态视为非 open，便于试探）"""
        return self.state is CircuitState.OPEN

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        通过熔断器执行异步函数

        Args:
            func: 异步可调用对象
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            func 的返回值

        Raises:
            CircuitBreakerOpenError: 熔断器 OPEN 时
            原 func 抛出的异常（在 CLOSED/HALF_OPEN 状态下）
        """
        async with self._lock:
            await self._before_call()

            try:
                result = await func(*args, **kwargs)
            except self._expected_exception as e:
                await self._on_failure()
                raise e
            else:
                await self._on_success()
                return result

    async def _before_call(self) -> None:
        """调用前状态检查与 OPEN -> HALF_OPEN 迁移"""
        if self._state is CircuitState.OPEN:
            # 超时则迁移 HALF_OPEN 放行试探
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "熔断器 OPEN -> HALF_OPEN [trace_id=%s]", get_trace_id()
                )
            else:
                logger.warning(
                    "熔断器 OPEN，拒绝调用 [trace_id=%s]", get_trace_id()
                )
                raise CircuitBreakerOpenError(
                    f"熔断器处于 OPEN 状态，{self._recovery_timeout}s 后重试"
                )

    async def _on_success(self) -> None:
        """调用成功：HALF_OPEN 恢复 CLOSED，失败计数清零"""
        if self._state is CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            logger.info(
                "熔断器 HALF_OPEN -> CLOSED [trace_id=%s]", get_trace_id()
            )
        self._failure_count = 0

    async def _on_failure(self) -> None:
        """调用失败：累计失败计数，必要时熔断"""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state is CircuitState.HALF_OPEN:
            # 试探失败，重新熔断
            self._state = CircuitState.OPEN
            logger.warning(
                "熔断器 HALF_OPEN -> OPEN（试探失败）[trace_id=%s]",
                get_trace_id(),
            )
            return

        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "熔断器 CLOSED -> OPEN（连续失败 %d 次）[trace_id=%s]",
                self._failure_count,
                get_trace_id(),
            )

    def reset(self) -> None:
        """手动重置熔断器到 CLOSED 状态（用于运维干预）"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0


__all__ = ["CircuitBreaker", "CircuitBreakerOpenError", "CircuitState"]
