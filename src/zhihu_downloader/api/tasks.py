"""后台任务管理 - 下载/更新任务的队列与状态管理

通过 asyncio.Queue 解耦后台业务执行与 SSE 推送：
- 后台 Task 消费 DownloadService 的 async generator，将事件放入队列
- SSE 流从队列读取事件推送给前端
- 任务状态贯穿生命周期，支持列表查询

设计说明：
- 单进程内存方案，重启后任务状态丢失（YAGNI，不引入 Redis）
- 使用 None 哨兵标记任务结束，而非按 complete/error 事件类型关闭流。
  原因：批量下载时每本书都会产出 complete/error 事件，但流应在整个
  任务结束后才关闭。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from zhihu_downloader.api.schemas import ProgressEventSchema
from zhihu_downloader.services.events import ProgressEvent

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskInfo:
    """单个后台任务的运行时信息

    Attributes:
        task_id: 任务唯一标识
        queue: 事件队列，后台任务写入、SSE 流读取
        status: running / completed / failed
        created_at: 创建时间戳
        trace_id: 关联的请求 traceId，用于日志追踪
    """

    task_id: str
    queue: asyncio.Queue[ProgressEvent | None]
    status: str = "running"
    created_at: float = field(default_factory=time.time)
    trace_id: str = ""
    # 保存后台 asyncio.Task 引用，避免被 GC 回收
    bg_task: asyncio.Task[None] | None = None


class TaskManager:
    """进程内任务管理器 - 维护 task_id 到 TaskInfo 的映射

    挂载在 app.state 上，通过依赖注入在路由中获取。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskInfo] = {}

    def create_task(self, trace_id: str = "") -> TaskInfo:
        """创建新任务，返回 TaskInfo（含唯一 task_id 与专属队列）"""
        task_id = uuid.uuid4().hex
        info = TaskInfo(
            task_id=task_id,
            queue=asyncio.Queue(),
            trace_id=trace_id,
        )
        self._tasks[task_id] = info
        logger.info("任务创建 task_id=%s trace_id=%s", task_id, trace_id)
        return info

    def get_task(self, task_id: str) -> TaskInfo | None:
        """按 task_id 查询任务"""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[TaskInfo]:
        """列出所有任务"""
        return list(self._tasks.values())

    def remove_task(self, task_id: str) -> None:
        """移除任务"""
        self._tasks.pop(task_id, None)

    def mark_status(self, task_id: str, status: str) -> None:
        """更新任务状态"""
        info = self._tasks.get(task_id)
        if info:
            info.status = status


async def sse_event_stream(task_info: TaskInfo) -> AsyncIterator[str]:
    """SSE 事件流生成器 - 从任务队列读取事件并格式化为 SSE 数据帧

    遇到 None 哨兵（任务结束标记）后关闭流。
    每个事件格式为 ``data: {json}\\n\\n``，符合 SSE 规范。
    """
    while True:
        event = await task_info.queue.get()
        if event is None:
            break
        schema = _event_to_schema(event)
        yield f"data: {schema.model_dump_json()}\n\n"


def _event_to_schema(event: ProgressEvent) -> ProgressEventSchema:
    """将 service 层 ProgressEvent 转换为 API 层 schema"""
    return ProgressEventSchema(
        type=event.type,
        message=event.message,
        total=event.total,
        downloaded=event.downloaded,
        current=event.current,
        book_title=event.book_title,
        output_files=event.output_files,
    )
