"""traceId 上下文管理

基于 contextvars 实现请求级 trace_id 透传，供日志、监控、链路追踪使用。
contextvars 在 asyncio 任务间天然隔离，无需手动加锁。
"""

from __future__ import annotations

import contextvars
import functools
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, ParamSpec, TypeVar

# 当前协程/线程的 trace_id 上下文变量；默认 "-" 表示无 trace
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default="-"
)

P = ParamSpec("P")
T = TypeVar("T")


def get_trace_id() -> str:
    """
    获取当前上下文的 trace_id

    Returns:
        当前 trace_id，未设置时返回 "-"
    """
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> contextvars.Token[str]:
    """
    设置当前上下文的 trace_id

    Args:
        trace_id: 要设置的 trace_id

    Returns:
        contextvars.Token，用于后续 reset 恢复
    """
    return _trace_id_var.set(trace_id)


def reset_trace_id(token: contextvars.Token[str]) -> None:
    """
    重置 trace_id 到 set 之前的状态

    Args:
        token: set_trace_id 返回的 token
    """
    _trace_id_var.reset(token)


def new_trace_id() -> str:
    """
    生成新的 trace_id（uuid4 hex，32 位无连字符）

    Returns:
        新的 trace_id 字符串
    """
    return uuid.uuid4().hex


@contextmanager
def trace_context(trace_id: str) -> Iterator[str]:
    """
    trace_id 上下文管理器：进入时设置，退出时恢复

    用法:
        with trace_context(new_trace_id()) as tid:
            do_something()  # 此范围内 get_trace_id() == tid

    Args:
        trace_id: 要设置的 trace_id

    Yields:
        传入的 trace_id
    """
    token = set_trace_id(trace_id)
    try:
        yield trace_id
    finally:
        reset_trace_id(token)


def with_trace_id(func: Callable[P, T]) -> Callable[P, T]:
    """
    装饰器：为被装饰函数自动注入新的 trace_id 上下文

    支持同步与异步函数。常用于 API 入口、消息消费 handler 等。

    Args:
        func: 被装饰函数

    Returns:
        包装后的函数
    """
    import asyncio

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            with trace_context(new_trace_id()):
                return await func(*args, **kwargs)

        return async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        with trace_context(new_trace_id()):
            return func(*args, **kwargs)

    return sync_wrapper


__all__ = [
    "get_trace_id",
    "new_trace_id",
    "reset_trace_id",
    "set_trace_id",
    "trace_context",
    "with_trace_id",
]
