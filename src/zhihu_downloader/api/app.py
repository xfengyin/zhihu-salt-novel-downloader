"""FastAPI 应用工厂 - 组装中间件、路由、异常处理

职责：
- 创建 FastAPI 实例并注册路由器
- 添加 CORS 中间件（白名单）与 traceId 中间件（纯 ASGI，不缓冲 SSE）
- 注册全局异常处理器，统一返回 {success, message, trace_id}
- 初始化 app.state 单例（Config / TaskManager / DownloadService / ShelfService）
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from zhihu_downloader.api.routers.download import router as download_router
from zhihu_downloader.api.routers.shelf import router as shelf_router
from zhihu_downloader.api.tasks import TaskManager
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.shelf_service import ShelfService
from zhihu_downloader.shelf.shelf_manager import ShelfManager
from zhihu_downloader.utils.config import Config

logger = logging.getLogger(__name__)

VERSION = "2.1.0"

# CORS 白名单 - vite 开发服务器及常见前端本地地址
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


class TraceIdMiddleware:
    """traceId 中间件 - 纯 ASGI 实现

    为什么不用 BaseHTTPMiddleware：它会缓冲响应体，破坏 SSE 流式推送。
    纯 ASGI 中间件直接透传消息，不影响流式响应。

    行为：
    - 读取请求 X-Trace-Id 头，没有则生成 uuid4 hex
    - 注入 request.state.trace_id，供路由与异常处理器使用
    - 响应头回写 X-Trace-Id
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 从请求头读取或生成 trace_id
        headers = dict(scope.get("headers", []))
        trace_id = headers.get(b"x-trace-id", b"").decode() or uuid.uuid4().hex

        # 注入到 scope["state"]（dict），Request.state 的 State 包装器会读取此 dict
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["trace_id"] = trace_id

        # 包装 send 以在响应头回写 X-Trace-Id
        trace_id_header = (b"x-trace-id", trace_id.encode())

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), trace_id_header]
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app(config: Config | None = None) -> FastAPI:
    """创建 FastAPI 应用实例

    Args:
        config: 配置管理器，为 None 时使用默认配置

    Returns:
        配置完成的 FastAPI 应用
    """
    app = FastAPI(
        title="知乎盐选小说下载器 API",
        version=VERSION,
        description="知乎盐选小说异步下载与书架管理 HTTP 接口",
    )

    # ------------------------------------------------------------------
    # 应用状态：共享单例，确保 ShelfService 与 DownloadService 内存一致
    # ------------------------------------------------------------------
    resolved_config = config or Config()
    shelf_manager = ShelfManager()
    app.state.config = resolved_config
    app.state.task_manager = TaskManager()
    app.state.download_service = DownloadService(
        config=resolved_config, shelf=shelf_manager
    )
    app.state.shelf_service = ShelfService(shelf=shelf_manager)

    # ------------------------------------------------------------------
    # 中间件（后添加的为外层）：CORS 在最外层，TraceId 在内层
    # ------------------------------------------------------------------
    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # 全局异常处理 - 统一 JSON 格式 {success, message, trace_id}
    # ------------------------------------------------------------------

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "")
        logger.warning(
            "HTTP异常 trace_id=%s status=%s detail=%s",
            trace_id,
            exc.status_code,
            exc.detail,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": str(exc.detail),
                "trace_id": trace_id,
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", "")
        logger.exception("未处理异常 trace_id=%s", trace_id)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "内部服务器错误",
                "trace_id": trace_id,
            },
        )

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    @app.get("/api/health", tags=["health"])
    async def health() -> dict:
        """健康检查端点"""
        return {"status": "ok", "version": VERSION}

    # ------------------------------------------------------------------
    # 路由注册
    # ------------------------------------------------------------------
    app.include_router(download_router, prefix="/api")
    app.include_router(shelf_router, prefix="/api")

    return app
