"""指标收集器

使用 OpenTelemetry 实现统一的指标收集，包括：
- 下载尝试次数
- 下载时长分布
- 导出时长分布
- 活跃任务数
- 熔断器状态
- 缓存命中次数
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram
try:
    from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[attr-defined]
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,  # type: ignore[attr-defined]
        PeriodicExportingMetricReader,  # type: ignore[attr-defined]
    )
except ImportError:
    MeterProvider = None  # type: ignore[assignment]
    ConsoleMetricExporter = None  # type: ignore[assignment]
    PeriodicExportingMetricReader = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter


class MetricsCollector:
    """
    统一指标收集器

    使用 OpenTelemetry SDK 提供的指标类型：
    - Counter: 单调递增计数器（如请求次数）
    - Histogram: 分布直方图（如耗时分布）
    - Gauge: 瞬时值测量（如活跃任务数、熔断器状态）

    用法示例:
        collector = MetricsCollector()
        collector.record_download_attempt(url="https://example.com")
        collector.record_download_duration(seconds=2.5, url="https://example.com")
    """

    def __init__(self) -> None:
        """初始化指标收集器"""
        self._meter: Meter = self._get_or_create_meter()

        self.download_attempts_total: Counter = self._meter.create_counter(
            name="download_attempts_total",
            description="下载尝试总次数",
            unit="1",
        )

        self.download_duration_seconds: Histogram = self._meter.create_histogram(
            name="download_duration_seconds",
            description="下载操作耗时分布",
            unit="s",
        )

        self.exporter_duration_seconds: Histogram = self._meter.create_histogram(
            name="exporter_duration_seconds",
            description="导出操作耗时分布",
            unit="s",
        )

        self.active_tasks_gauge = self._meter.create_gauge(
            name="active_tasks_gauge",
            description="当前活跃任务数量",
            unit="1",
        )

        self.circuit_breaker_state = self._meter.create_gauge(
            name="circuit_breaker_state",
            description="熔断器状态: 0=CLOSED, 1=OPEN, 2=HALF_OPEN",
            unit="1",
        )

        self.cache_hits_total: Counter = self._meter.create_counter(
            name="cache_hits_total",
            description="缓存命中总次数",
            unit="1",
        )

    def _get_or_create_meter(self) -> Meter:
        """获取或创建 OpenTelemetry Meter"""
        try:
            return metrics.get_meter(__name__)
        except Exception:
            if MeterProvider is None or ConsoleMetricExporter is None or PeriodicExportingMetricReader is None:
                return metrics.get_meter(__name__)
            provider = MeterProvider(
                metric_readers=[
                    PeriodicExportingMetricReader(ConsoleMetricExporter()),
                ]
            )
            metrics.set_meter_provider(provider)
            return metrics.get_meter(__name__)

    def record_download_attempt(self, url: str | None = None, success: bool = True) -> None:
        """
        记录下载尝试

        Args:
            url: 下载地址
            success: 是否成功
        """
        attributes: dict[str, Any] = {"success": str(success).lower()}
        if url:
            attributes["url"] = url
        self.download_attempts_total.add(1, attributes=attributes)

    def record_download_duration(self, seconds: float, url: str | None = None) -> None:
        """
        记录下载时长

        Args:
            seconds: 下载耗时（秒）
            url: 下载地址
        """
        attributes: dict[str, Any] = {}
        if url:
            attributes["url"] = url
        self.download_duration_seconds.record(seconds, attributes=attributes)

    def record_exporter_duration(
        self,
        seconds: float,
        format: str,
        book_title: str | None = None,
    ) -> None:
        """
        记录导出时长

        Args:
            seconds: 导出耗时（秒）
            format: 导出格式（epub/mobi/md/txt）
            book_title: 书名
        """
        attributes: dict[str, Any] = {"format": format}
        if book_title:
            attributes["book_title"] = book_title
        self.exporter_duration_seconds.record(seconds, attributes=attributes)

    def update_active_tasks(self, count: int) -> None:
        """
        更新活跃任务数

        Args:
            count: 当前活跃任务数量
        """
        self.active_tasks_gauge.set(count, attributes={})

    def update_circuit_breaker(self, state: str) -> None:
        """
        更新熔断器状态

        Args:
            state: 熔断器状态（CLOSED/OPEN/HALF_OPEN）
        """
        state_map = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
        state_value = state_map.get(state.upper(), 0)
        self.circuit_breaker_state.set(state_value, attributes={"state": state})

    def record_cache_hit(self, key: str | None = None) -> None:
        """
        记录缓存命中

        Args:
            key: 缓存键
        """
        attributes: dict[str, Any] = {}
        if key:
            attributes["key"] = key
        self.cache_hits_total.add(1, attributes=attributes)


__all__ = ["MetricsCollector"]
