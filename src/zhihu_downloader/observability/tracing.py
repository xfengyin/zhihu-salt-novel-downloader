"""Trace工具模块

提供完整的分布式链路追踪能力，支持：
- Trace上下文管理
- Span创建与层级管理
- 标签设置
- 异常记录
- 同步与异步函数支持
"""

from __future__ import annotations

import contextvars
import functools
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")

_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default="-"
)
_span_stack_var: contextvars.ContextVar[list[Span] | None] = contextvars.ContextVar(
    "span_stack", default=None
)


@dataclass
class Span:
    """Span表示一次操作的时间范围"""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time: float
    end_time: float | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    exception: Exception | None = None

    @property
    def duration(self) -> float:
        """获取span持续时间（毫秒）"""
        if self.end_time is None:
            return (time.time() - self.start_time) * 1000
        return (self.end_time - self.start_time) * 1000


class TraceContext:
    """Trace上下文管理器

    管理当前trace的生命周期，包括trace_id和span栈。
    """

    def __init__(self, trace_id: str | None = None) -> None:
        self._trace_id = trace_id or uuid.uuid4().hex
        self._span_stack: list[Span] = []
        self._trace_token: contextvars.Token[str] | None = None
        self._span_token: contextvars.Token[list[Span] | None] | None = None

    def __enter__(self) -> TraceContext:
        self._trace_token = _trace_id_var.set(self._trace_id)
        self._span_token = _span_stack_var.set(self._span_stack)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._trace_token:
            _trace_id_var.reset(self._trace_token)
        if self._span_token:
            _span_stack_var.reset(self._span_token)

    @property
    def trace_id(self) -> str:
        """获取当前trace_id"""
        return self._trace_id

    @property
    def current_span(self) -> Span | None:
        """获取当前活跃的span"""
        return self._span_stack[-1] if self._span_stack else None


@contextmanager
def start_span(name: str) -> Iterator[Span]:
    """创建并启动一个新的span

    span会自动加入当前trace的span栈，支持嵌套调用。

    Args:
        name: span名称

    Yields:
        创建的span对象
    """
    trace_id = _trace_id_var.get()
    span_stack = _span_stack_var.get() or []

    parent_span = span_stack[-1] if span_stack else None
    parent_span_id = parent_span.span_id if parent_span else None

    span = Span(
        name=name,
        trace_id=trace_id,
        span_id=uuid.uuid4().hex[:16],
        parent_span_id=parent_span_id,
        start_time=time.time(),
    )

    span_stack.append(span)
    _span_stack_var.set(span_stack)

    try:
        yield span
    finally:
        span.end_time = time.time()
        span_stack.pop()
        _span_stack_var.set(span_stack)


def get_current_trace_id() -> str:
    """获取当前trace_id

    Returns:
        当前trace_id，未设置时返回"-"
    """
    return _trace_id_var.get()


def set_trace_tag(key: str, value: Any) -> None:
    """为当前span设置标签

    Args:
        key: 标签键
        value: 标签值
    """
    span_stack = _span_stack_var.get()
    if span_stack:
        span_stack[-1].tags[key] = value
        _span_stack_var.set(span_stack)


def record_exception(exc: Exception) -> None:
    """记录异常到当前span

    Args:
        exc: 异常对象
    """
    span_stack = _span_stack_var.get()
    if span_stack:
        span_stack[-1].exception = exc
        _span_stack_var.set(span_stack)


def with_trace(func: Callable[P, T]) -> Callable[P, T]:
    """装饰器：为函数添加trace能力

    自动创建trace上下文并为函数创建span。
    支持同步和异步函数。

    Args:
        func: 被装饰函数

    Returns:
        包装后的函数
    """
    import asyncio

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            with TraceContext():
                with start_span(func.__name__):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as exc:
                        record_exception(exc)
                        raise

        return async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        with TraceContext():
            with start_span(func.__name__):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    record_exception(exc)
                    raise

    return sync_wrapper


__all__ = [
    "Span",
    "TraceContext",
    "get_current_trace_id",
    "record_exception",
    "set_trace_tag",
    "start_span",
    "with_trace",
]
