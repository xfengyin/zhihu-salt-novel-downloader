"""OpenTelemetry 配置与工具函数

提供完整的可观测性能力：
- Trace（分布式追踪）
- Metrics（指标）
- Logs（日志）
- FastAPI 自动 instrumentation
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from opentelemetry import trace
    from opentelemetry.metrics import Meter
    from opentelemetry.sdk.trace import TracerProvider

# 全局实例，供 get_* 函数使用
_tracer_provider: TracerProvider | None = None
_tracer: trace.Tracer | None = None
_meter: Meter | None = None


class OTelConfig(BaseSettings):
    """OpenTelemetry 配置项

    通过环境变量或 .env 文件配置，前缀为 OTEL_
    """

    model_config = SettingsConfigDict(env_prefix="OTEL_", case_sensitive=False)

    service_name: str = "zhihu-downloader"
    service_version: str = "3.0.0"
    endpoint: str | None = None
    protocol: str = "grpc"
    insecure: bool = True
    trace_enabled: bool = False
    metrics_enabled: bool = False
    logs_enabled: bool = False
    sampler_type: str = "parentbased_traceidratio"
    sampler_ratio: float = 1.0
    log_level: str = "INFO"


def _import_otel() -> dict[str, Any]:
    """延迟导入 OpenTelemetry 模块

    避免生产环境中未安装 OTel 依赖时的导入错误
    """
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.metrics import Meter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import (
            ConsoleMetricExporter,
            PeriodicExportingMetricReader,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
        from opentelemetry.semconv.resource import ResourceAttributes
        from opentelemetry.trace import Tracer

        return {
            "trace": trace,
            "metrics": metrics,
            "TracerProvider": TracerProvider,
            "MeterProvider": MeterProvider,
            "BatchSpanProcessor": BatchSpanProcessor,
            "ConsoleSpanExporter": ConsoleSpanExporter,
            "ConsoleMetricExporter": ConsoleMetricExporter,
            "PeriodicExportingMetricReader": PeriodicExportingMetricReader,
            "OTLPSpanExporter": OTLPSpanExporter,
            "OTLPMetricExporter": OTLPMetricExporter,
            "Resource": Resource,
            "ResourceAttributes": ResourceAttributes,
            "Tracer": Tracer,
            "Meter": Meter,
        }
    except ImportError as e:
        raise RuntimeError(
            "OpenTelemetry dependencies not installed. "
            "Install with: pip install 'zhihu-salt-novel-downloader[dev]'"
        ) from e


def init_otel(config: OTelConfig | None = None) -> None:
    """初始化 OpenTelemetry SDK

    Args:
        config: OTelConfig 实例，若为 None 则从环境变量读取
    """
    global _tracer_provider, _tracer, _meter

    if _tracer_provider is not None:
        logging.getLogger(__name__).warning("OTel SDK already initialized")
        return

    if config is None:
        config = OTelConfig()

    otel = _import_otel()

    resource = otel["Resource"](
        attributes={
            otel["ResourceAttributes"].SERVICE_NAME: config.service_name,
            otel["ResourceAttributes"].SERVICE_VERSION: config.service_version,
        }
    )

    if config.trace_enabled:
        tracer_provider = otel["TracerProvider"](resource=resource)

        if config.endpoint:
            exporter = otel["OTLPSpanExporter"](
                endpoint=config.endpoint,
                insecure=config.insecure,
            )
        else:
            exporter = otel["ConsoleSpanExporter"]()

        processor = otel["BatchSpanProcessor"](exporter)
        tracer_provider.add_span_processor(processor)
        otel["trace"].set_tracer_provider(tracer_provider)
        _tracer_provider = tracer_provider
        _tracer = tracer_provider.get_tracer(config.service_name)

    if config.metrics_enabled:
        if config.endpoint:
            exporter = otel["OTLPMetricExporter"](
                endpoint=config.endpoint,
                insecure=config.insecure,
            )
        else:
            exporter = otel["ConsoleMetricExporter"]()

        reader = otel["PeriodicExportingMetricReader"](exporter)
        meter_provider = otel["MeterProvider"](resource=resource, metric_readers=[reader])
        otel["metrics"].set_meter_provider(meter_provider)
        _meter = meter_provider.get_meter(config.service_name)

    logger = logging.getLogger(__name__)
    logger.info(
        "OTel SDK initialized: trace=%s, metrics=%s, endpoint=%s",
        config.trace_enabled,
        config.metrics_enabled,
        config.endpoint or "console",
    )


def get_tracer(name: str | None = None) -> trace.Tracer:
    """获取 Tracer 实例

    Args:
        name: Tracer 名称，默认使用服务名

    Returns:
        Tracer 实例
    """
    global _tracer

    if _tracer is None:
        otel = _import_otel()
        _tracer = otel["trace"].get_tracer(name or "zhihu-downloader")

    if name is not None and _tracer is not None:
        otel = _import_otel()
        return otel["trace"].get_tracer(name)

    return _tracer


def get_meter(name: str | None = None) -> Meter:
    """获取 Meter 实例

    Args:
        name: Meter 名称，默认使用服务名

    Returns:
        Meter 实例
    """
    global _meter

    if _meter is None:
        otel = _import_otel()
        _meter = otel["metrics"].get_meter(name or "zhihu-downloader")

    if name is not None and _meter is not None:
        otel = _import_otel()
        return otel["metrics"].get_meter(name)

    return _meter


def get_logger(name: str) -> logging.Logger:
    """获取带有 trace 上下文的 Logger 实例

    Args:
        name: Logger 名称，通常传 __name__

    Returns:
        logging.Logger 实例
    """
    from zhihu_downloader.utils.logging_setup import get_logger as get_structured_logger

    return get_structured_logger(name)


def instrument_fastapi(app: Any) -> None:
    """为 FastAPI 应用添加自动 instrumentation

    Args:
        app: FastAPI 应用实例
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger = logging.getLogger(__name__)
        logger.info("FastAPI instrumentation enabled")
    except ImportError as e:
        raise RuntimeError(
            "FastAPI instrumentation not available. "
            "Install with: pip install opentelemetry-instrumentation-fastapi"
        ) from e


def shutdown_otel() -> None:
    """关闭 OpenTelemetry SDK，确保数据完整导出"""
    global _tracer_provider, _tracer, _meter

    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None

    _tracer = None
    _meter = None

    logger = logging.getLogger(__name__)
    logger.info("OTel SDK shutdown completed")


__all__ = [
    "OTelConfig",
    "get_logger",
    "get_meter",
    "get_tracer",
    "init_otel",
    "instrument_fastapi",
    "shutdown_otel",
]
