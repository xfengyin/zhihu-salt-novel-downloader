"""书架路由 - 书架 CRUD 与批量更新

GET    /api/shelf/books                       列出书架所有书籍
GET    /api/shelf/stats                        获取书架统计
POST   /api/shelf/books                        添加书籍到书架
DELETE /api/shelf/books/{url}                  从书架移除书籍
POST   /api/shelf/clean                        清空书架
POST   /api/shelf/update-all                   触发书架批量更新，返回 task_id
GET    /api/shelf/update-all/stream/{task_id}  SSE 流推送更新进度
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from zhihu_downloader.api.dependencies import (
    get_config,
    get_download_service,
    get_shelf_service,
    get_task_manager,
)
from zhihu_downloader.api.schemas import (
    BookSchema,
    MessageResponse,
    ShelfAddRequest,
    ShelfStatsSchema,
)
from zhihu_downloader.api.tasks import TaskInfo, TaskManager, sse_event_stream
from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.events import ProgressEvent
from zhihu_downloader.services.shelf_service import ShelfService
from zhihu_downloader.utils.config import Config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shelf", tags=["shelf"])


# ---------------------------------------------------------------------------
# 书架查询与管理
# ---------------------------------------------------------------------------


@router.get("/books")
async def list_books(
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> list[BookSchema]:
    """列出书架所有书籍"""
    return [BookSchema(**_normalize_book(b)) for b in shelf_service.list_books()]


@router.get("/stats")
async def get_stats(
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> ShelfStatsSchema:
    """获取书架统计信息"""
    return ShelfStatsSchema(**shelf_service.get_statistics())


@router.post("/books")
async def add_book(
    body: ShelfAddRequest,
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> MessageResponse:
    """添加书籍到书架"""
    result = shelf_service.add_book(body.url)
    return MessageResponse(message=result["message"], success=result["success"])


@router.delete("/books/{url:path}")
async def remove_book(
    url: str,
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> MessageResponse:
    """从书架移除书籍

    url 使用 :path 转换器以支持含斜杠的完整 URL，客户端应 URL 编码。
    """
    result = shelf_service.remove_book(url)
    return MessageResponse(message=result["message"], success=result["success"])


@router.post("/clean")
async def clean_shelf(
    shelf_service: ShelfService = Depends(get_shelf_service),
) -> MessageResponse:
    """清空书架"""
    result = shelf_service.clean_cache()
    return MessageResponse(message=result["message"], success=result["success"])


# ---------------------------------------------------------------------------
# 书架批量更新（后台任务 + SSE）
# ---------------------------------------------------------------------------


@router.post("/update-all")
async def update_all(
    http_request: Request,
    task_manager: TaskManager = Depends(get_task_manager),
    download_service: DownloadService = Depends(get_download_service),
    config: Config = Depends(get_config),
) -> dict:
    """触发书架批量更新，返回 task_id

    从配置读取 cookie_file 尽力装配凭证，更新进度通过 SSE 流获取。
    """
    trace_id = getattr(http_request.state, "trace_id", "")
    cookie_manager = _build_cookie_from_config(config)

    task_info = task_manager.create_task(trace_id=trace_id)
    # 保存 task 引用避免被 GC 回收（RUF006）
    task_info.bg_task = asyncio.create_task(
        _run_shelf_update(
            download_service=download_service,
            task_info=task_info,
            cookie_manager=cookie_manager,
            task_manager=task_manager,
            config=config,
        )
    )

    return {"task_id": task_info.task_id, "trace_id": trace_id}


@router.get("/update-all/stream/{task_id}")
async def stream_shelf_update(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> StreamingResponse:
    """SSE 流 - 推送书架更新进度事件，任务结束后自动关闭"""
    task_info = task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")

    return StreamingResponse(
        sse_event_stream(task_info),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _normalize_book(book: dict) -> dict:
    """将书架字典字段对齐到 BookSchema，过滤 chapters 等大字段"""
    return {
        "url": book.get("url", ""),
        "title": book.get("title", "未知标题"),
        "author": book.get("author", "未知作者"),
        "chapter_count": book.get("chapter_count", 0),
        "completed": book.get("completed", False),
        "added_at": book.get("added_at", ""),
        "last_update": book.get("last_update", ""),
    }


def _build_cookie_from_config(config: Config) -> CookieManager | None:
    """从配置的 auth.cookie_file 尽力装配 CookieManager

    配置未指定或文件不存在时返回 None（匿名更新）。
    """
    cookie_file = config.get("auth.cookie_file", "")
    if not cookie_file:
        return None

    cm = CookieManager()
    try:
        cm.load_from_file(cookie_file)
        return cm
    except FileNotFoundError:
        logger.warning("配置的 Cookie 文件不存在: %s", cookie_file)
        return None


async def _run_shelf_update(
    download_service: DownloadService,
    task_info: TaskInfo,
    cookie_manager: CookieManager | None,
    task_manager: TaskManager,
    config: Config,
) -> None:
    """后台书架更新任务 - 消费 update_shelf generator 并将事件推入队列"""
    output_dir = config.get("output.output_dir", "./output")
    export_format = config.get("output.default_format", "md")

    try:
        async for event in download_service.update_shelf(
            cookie_manager=cookie_manager,
            output_dir=output_dir,
            export_format=export_format,
        ):
            await task_info.queue.put(event)
    except Exception as e:
        logger.exception(
            "后台书架更新任务异常 task_id=%s trace_id=%s",
            task_info.task_id,
            task_info.trace_id,
        )
        await task_info.queue.put(ProgressEvent.error(f"任务异常: {e}"))
        task_manager.mark_status(task_info.task_id, "failed")
    else:
        task_manager.mark_status(task_info.task_id, "completed")
    finally:
        await task_info.queue.put(None)
