"""结构化日志配置

基于标准库 logging 实现可观测日志：
- 支持 JSON / 人类可读两种输出格式
- 自动注入 trace_id（来自 contextvars）
- 不引入 loguru/structlog 等第三方依赖，便于打包分发
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from zhihu_downloader.utils.trace_context import get_trace_id

# 已配置标记，避免重复添加 handler 导致日志重复输出
_configured: bool = False


class _StructuredFormatter(logging.Formatter):
    """人类可读的结构化格式：时间 [级别] [trace_id=xxx] logger: 消息"""

    def format(self, record: logging.LogRecord) -> str:
        # 使用 ISO 风格的本地时间，便于人眼快速定位
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        trace_id = get_trace_id()
        return (
            f"{ts} [{record.levelname}] [trace_id={trace_id}] "
            f"{record.name}: {record.getMessage()}"
        )


class _JsonFormatter(logging.Formatter):
    """JSON 行格式，便于 ELK / Loki 等日志系统采集与检索"""

    def format(self, record: logging.LogRecord) -> str:
        # 异常信息单独字段，便于聚合告警
        exc_info: str | None = None
        if record.exc_info:
            exc_info = self.formatException(record.exc_info)

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": get_trace_id(),
            "module": record.module,
            "line": record.lineno,
        }
        if exc_info:
            payload["exception"] = exc_info
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """
    配置 root logger

    幂等：多次调用不会重复添加 handler。

    Args:
        level: 日志级别字符串（DEBUG/INFO/WARNING/ERROR/CRITICAL）
        json_output: True 输出 JSON 行，False 输出人类可读格式
    """
    global _configured

    root = logging.getLogger()
    root.setLevel(level.upper())

    # 已配置过则只更新级别，避免重复 handler
    if _configured:
        for handler in root.handlers:
            handler.setLevel(level.upper())
        return

    handler = logging.StreamHandler()
    handler.setLevel(level.upper())
    handler.setFormatter(_JsonFormatter() if json_output else _StructuredFormatter())
    root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的 logger

    Args:
        name: logger 名称，通常传 __name__

    Returns:
        logging.Logger 实例
    """
    return logging.getLogger(name)


__all__ = ["get_logger", "setup_logging"]
