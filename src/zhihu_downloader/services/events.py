"""进度事件定义 - Service 层与 API/CLI 层的进度通信载体

使用 dataclass 而非 pydantic，保持 service 层零 web 框架依赖。
API 层负责将 ProgressEvent 转换为 ProgressEventSchema 推送给前端。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# 事件类型字面量，与 api.schemas.ProgressEventType 对齐
ProgressEventType = Literal["info", "progress", "export", "complete", "error"]


@dataclass(slots=True)
class ProgressEvent:
    """进度事件

    通过 async generator 产出，供 SSE 流式推送或 CLI 实时打印。

    Attributes:
        type: 事件类型
        message: 人类可读消息
        total: 总章节数
        downloaded: 已下载数
        current: 当前章节标题
        book_title: 当前书名
        output_files: 导出文件路径列表
    """

    type: ProgressEventType = "info"
    message: str = ""
    total: int = 0
    downloaded: int = 0
    current: str = ""
    book_title: str = ""
    output_files: list[str] = field(default_factory=list)

    # 便捷工厂方法，降低调用方构造成本
    @classmethod
    def info(cls, message: str, book_title: str = "") -> ProgressEvent:
        """构造信息事件"""
        return cls(type="info", message=message, book_title=book_title)

    @classmethod
    def progress(
        cls,
        message: str,
        total: int,
        downloaded: int,
        current: str = "",
        book_title: str = "",
    ) -> ProgressEvent:
        """构造章节进度事件"""
        return cls(
            type="progress",
            message=message,
            total=total,
            downloaded=downloaded,
            current=current,
            book_title=book_title,
        )

    @classmethod
    def export(cls, message: str, book_title: str = "") -> ProgressEvent:
        """构造导出阶段事件"""
        return cls(type="export", message=message, book_title=book_title)

    @classmethod
    def complete(
        cls,
        message: str,
        book_title: str = "",
        output_files: list[str] | None = None,
    ) -> ProgressEvent:
        """构造完成事件"""
        return cls(
            type="complete",
            message=message,
            book_title=book_title,
            output_files=output_files or [],
        )

    @classmethod
    def error(cls, message: str, book_title: str = "") -> ProgressEvent:
        """构造错误事件"""
        return cls(type="error", message=message, book_title=book_title)
