"""下载路由 - 下载任务管理与进度流

POST /downloads          启动下载任务
GET  /downloads/{id}     查询下载任务状态
GET  /downloads/{id}/events  SSE 流推送进度事件
POST /downloads/{id}/cancel  取消下载任务
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

router = APIRouter(prefix="/downloads", tags=["downloads"])


@router.get("")
async def list_downloads(
    task_manager: TaskManager = Depends(get_task_manager),
) -> list[dict]:
    """查询下载任务列表"""
    return [
        {
            "task_id": t.task_id,
            "status": t.status,
            "created_at": t.created_at,
            "trace_id": t.trace_id,
        }
        for t in task_manager.list_tasks()
    ]


@router.post("")
async def create_download(
    body: DownloadRequest,
    http_request: Request,
    download_service: DownloadService = Depends(get_download_service),
    task_manager: TaskManager = Depends(get_task_manager),
) -> dict:
    """启动下载任务，返回 task_id"""
    trace_id = getattr(http_request.state, "trace_id", "")

    urls = body.batch_urls or ([body.url] if body.url else [])
    if not urls:
        raise HTTPException(status_code=400, detail="未提供下载 URL")

    try:
        cookie_manager = build_cookie_manager(body)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    task_info = task_manager.create_task(trace_id=trace_id)
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


@router.get("/{task_id}")
async def get_download(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> dict:
    """查询下载任务状态"""
    task_info = task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "task_id": task_info.task_id,
        "status": task_info.status,
        "created_at": task_info.created_at,
        "trace_id": task_info.trace_id,
    }


@router.get("/{task_id}/events")
async def stream_download_events(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> StreamingResponse:
    """SSE 流 - 推送下载进度事件"""
    task_info = task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")

    return StreamingResponse(
        sse_event_stream(task_info),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{task_id}/cancel")
async def cancel_download(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
) -> dict:
    """取消下载任务"""
    task_info = task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task_info.status in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="任务已结束")

    if task_info.bg_task:
        task_info.bg_task.cancel()

    task_manager.mark_status(task_id, "cancelled")
    await task_info.queue.put(None)

    return {"message": "任务已取消", "task_id": task_id}


async def _run_download(
    download_service: DownloadService,
    task_info: TaskInfo,
    body: DownloadRequest,
    cookie_manager: CookieManager | None,
    task_manager: TaskManager,
) -> None:
    """后台下载任务"""
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
    except asyncio.CancelledError:
        logger.info("下载任务被取消 task_id=%s", task_info.task_id)
        await task_info.queue.put(ProgressEvent.error("任务已取消"))
        task_manager.mark_status(task_info.task_id, "cancelled")
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
        await task_info.queue.put(None)
