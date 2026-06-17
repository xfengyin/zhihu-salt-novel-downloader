"""下载路由 - 启动下载任务与 SSE 进度流

POST /api/download        启动后台下载，返回 task_id
GET  /api/download/stream/{task_id}  SSE 流推送进度事件
GET  /api/download/tasks  列出所有任务状态
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import StreamingResponse

from zhihu_downloader.api.dependencies import (
    build_cookie_manager,
    get_download_service,
    get_task_manager,
)
from zhihu_downloader.api.schemas import DownloadRequest
from zhihu_downloader.api.tasks import TaskInfo, TaskManager, sse_event_stream
from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.events import ProgressEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/download", tags=["download"])


@router.post("")
async def start_download(
    body: DownloadRequest,
    http_request: Request,
    download_service: DownloadService = Depends(get_download_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> dict:
    """启动下载任务，返回 task_id

    下载在后台 asyncio.Task 中执行，进度事件通过 SSE 流获取。
    """
    trace_id = getattr(http_request.state, "trace_id", "")

    # 合并 URL 列表：batch_urls 优先，否则取单个 url
    urls = body.batch_urls or ([body.url] if body.url else [])
    if not urls:
        raise HTTPException(status_code=400, detail="未提供下载 URL")

    # 装配 CookieManager（cookie_file 不存在时抛 400）
    try:
        cookie_manager = build_cookie_manager(body)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 创建任务并启动后台执行
    task_info = task_manager.create_task(trace_id=trace_id)
    # 保存 task 引用避免被 GC 回收（RUF006）
    task_info.bg_task = asyncio.create_task(
        _run_download(
            download_service=download_service,
            task_info=task_info,
            body=body,
            cookie_manager=cookie_manager,
            task_manager=task_manager,
        )
    )

    return {"task_id": task_info.task_id, "trace_id": trace_id}


@router.get("/stream/{task_id}")
async def stream_download(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> StreamingResponse:
    """SSE 流 - 推送下载进度事件，任务结束后自动关闭"""
    task_info = task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")

    return StreamingResponse(
        sse_event_stream(task_info),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks")
async def list_tasks(
    task_manager: TaskManager = Depends(get_task_manager),
) -> list[dict]:
    """列出所有下载任务及其状态"""
    return [
        {
            "task_id": t.task_id,
            "status": t.status,
            "created_at": t.created_at,
            "trace_id": t.trace_id,
        }
        for t in task_manager.list_tasks()
    ]


# ---------------------------------------------------------------------------
# 后台任务执行
# ---------------------------------------------------------------------------


async def _run_download(
    download_service: DownloadService,
    task_info: TaskInfo,
    body: DownloadRequest,
    cookie_manager: CookieManager | None,
    task_manager: TaskManager,
) -> None:
    """后台下载任务 - 消费 download generator 并将事件推入队列

    异常在边界捕获：service 层内部已有 try/except 产出 error 事件，
    此处兜底捕获 generator 自身未预期的异常。
    """
    urls = body.batch_urls or ([body.url] if body.url else [])

    try:
        async for event in download_service.download(
            urls,
            cookie_manager=cookie_manager,
            max_concurrent=body.max_concurrent,
            rate_limit=body.rate_limit,
            output_dir=body.output_dir,
            export_format=body.export_format.value,
            list_only=body.list_only,
            clean_content=body.clean_content,
            resume=body.resume,
            update_check=body.update_check,
        ):
            await task_info.queue.put(event)
    except Exception as e:
        logger.exception(
            "后台下载任务异常 task_id=%s trace_id=%s",
            task_info.task_id,
            task_info.trace_id,
        )
        await task_info.queue.put(ProgressEvent.error(f"任务异常: {e}"))
        task_manager.mark_status(task_info.task_id, "failed")
    else:
        task_manager.mark_status(task_info.task_id, "completed")
    finally:
        # 哨兵：通知 SSE 流关闭
        await task_info.queue.put(None)
