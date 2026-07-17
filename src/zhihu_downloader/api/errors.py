"""RFC 7807 错误模型实现

参考规范：https://datatracker.ietf.org/doc/html/rfc7807

提供标准化的 HTTP 问题详情响应，支持 trace_id 注入用于链路追踪。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from zhihu_downloader.utils.trace_context import get_trace_id

logger = logging.getLogger(__name__)


class Problem(BaseModel):
    """RFC 7807 问题详情模型

    Attributes:
        type: 问题类型的 URI 引用，默认为 about:blank
        title: 问题的简短、人类可读的标题
        status: HTTP 状态码，可选
        detail: 问题的详细描述，可选
        instance: 问题发生的具体实例 URI，可选
        trace_id: 链路追踪 ID，用于问题定位
        extra: 额外的自定义字段，可选
    """

    type: str = Field(
        default="about:blank",
        description="问题类型的 URI 引用",
    )
    title: str = Field(
        ...,
        description="问题的简短、人类可读的标题",
    )
    status: int | None = Field(
        default=None,
        description="HTTP 状态码",
    )
    detail: str | None = Field(
        default=None,
        description="问题的详细描述",
    )
    instance: str | None = Field(
        default=None,
        description="问题发生的具体实例 URI",
    )
    trace_id: str = Field(
        default_factory=get_trace_id,
        description="链路追踪 ID",
    )
    extra: dict[str, Any] | None = Field(
        default=None,
        description="额外的自定义字段",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "https://example.com/probs/invalid-request",
                "title": "无效请求",
                "status": 400,
                "detail": "缺少必需参数: url",
                "instance": "/api/download",
                "trace_id": "abc123def456",
                "extra": {"param": "url"},
            }
        }
    }


class ProblemException(HTTPException):
    """自定义异常，支持 Problem 模型

    将 RFC 7807 Problem 对象封装为可抛出的异常，
    由 FastAPI 异常处理器统一处理并返回标准化响应。

    Args:
        problem: Problem 对象
        status_code: HTTP 状态码，优先使用 problem.status
    """

    def __init__(self, problem: Problem) -> None:
        status_code = problem.status or 500
        super().__init__(
            status_code=status_code,
            detail=problem.detail,
            headers={"Content-Type": "application/problem+json"},
        )
        self.problem = problem


def create_problem(
    title: str,
    type: str = "about:blank",
    status: int | None = None,
    detail: str | None = None,
    instance: str | None = None,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Problem:
    """创建 Problem 对象

    便捷工厂函数，自动从上下文获取 trace_id。

    Args:
        title: 问题标题
        type: 问题类型 URI，默认为 about:blank
        status: HTTP 状态码
        detail: 详细描述
        instance: 发生实例 URI
        trace_id: 链路追踪 ID，未提供时从上下文获取
        extra: 额外字段

    Returns:
        Problem 对象
    """
    return Problem(
        type=type,
        title=title,
        status=status,
        detail=detail,
        instance=instance,
        trace_id=trace_id or get_trace_id(),
        extra=extra,
    )


async def problem_handler(request: Request, exc: ProblemException) -> JSONResponse:
    """FastAPI 异常处理器：处理 ProblemException

    将 ProblemException 转换为符合 RFC 7807 规范的 JSON 响应，
    自动注入请求级 trace_id。

    Args:
        request: FastAPI 请求对象
        exc: ProblemException 异常

    Returns:
        JSONResponse，Content-Type 为 application/problem+json
    """
    request_trace_id = getattr(request.state, "trace_id", "")
    if request_trace_id and exc.problem.trace_id == "-":
        exc.problem.trace_id = request_trace_id

    logger.warning(
        "ProblemException trace_id=%s status=%s type=%s title=%s detail=%s",
        exc.problem.trace_id,
        exc.status_code,
        exc.problem.type,
        exc.problem.title,
        exc.problem.detail,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=exc.problem.model_dump(exclude_none=True),
        headers={"Content-Type": "application/problem+json"},
    )


__all__ = [
    "Problem",
    "ProblemException",
    "create_problem",
    "problem_handler",
]
