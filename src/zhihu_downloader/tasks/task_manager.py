"""任务管理器 - 统一任务调度与生命周期管理

基于数据库持久化的任务管理系统，支持：
- 任务提交/查询/取消/重试
- 异步任务队列处理
- SIGTERM 优雅停机
- 状态机驱动的任务流转

设计要点：
- 使用 asyncio.Queue 作为内存队列，数据库作为持久化层
- 通过状态机控制任务状态转换
- 后台 worker 协程消费队列并执行任务
- 支持幂等提交（通过 idemp_key 去重）
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select

from zhihu_downloader.infra.database import get_session
from zhihu_downloader.infra.models import Task
from zhihu_downloader.infra.repository import TaskRepository
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.events import ProgressEvent

from .state_machine import TaskKind, TaskStatus

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Task], Coroutine[Any, Any, dict[str, object]]]


class TaskManager:
    """任务管理器 - 统一入口"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._running: bool = False
        self._download_service: DownloadService | None = None
        self._stop_task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # 任务管理 API
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        kind: str,
        user_id: int,
        payload: dict[str, object],
        idemp_key: str | None = None,
        trace_id: str = "",
    ) -> Task:
        """提交任务到队列

        Args:
            kind: 任务类型
            user_id: 用户ID
            payload: 任务参数
            idemp_key: 幂等键，用于去重
            trace_id: 追踪ID

        Returns:
            创建的任务对象

        Raises:
            ValueError: 任务类型无效
        """
        if kind not in [e.value for e in TaskKind]:
            raise ValueError(f"无效的任务类型: {kind}")

        async with get_session() as session:
            repo = TaskRepository(session)

            if idemp_key:
                existing = await repo.get_by_idemp_key(idemp_key)
                if existing:
                    logger.info("任务已存在 idemp_key=%s task_id=%d", idemp_key, existing.id)
                    return existing

            task = Task(
                idemp_key=idemp_key or uuid.uuid4().hex,
                user_id=user_id,
                kind=kind,
                status="pending",
                payload=payload,
                trace_id=trace_id,
            )
            task = await repo.create(task)
            logger.info("任务创建成功 task_id=%d kind=%s", task.id, kind)

        await self._queue.put(task.id)
        logger.debug("任务已入队 task_id=%d", task.id)

        return task

    async def get_task(self, task_id: int) -> Task | None:
        """获取任务详情"""
        async with get_session() as session:
            repo = TaskRepository(session)
            return await repo.get(task_id)

    async def list_tasks(
        self,
        user_id: int | None = None,
        status: str | None = None,
        kind: str | None = None,
    ) -> list[Task]:
        """列出任务列表

        Args:
            user_id: 可选，按用户筛选
            status: 可选，按状态筛选
            kind: 可选，按类型筛选

        Returns:
            任务列表
        """
        async with get_session() as session:
            query = select(Task)

            if user_id is not None:
                query = query.where(Task.user_id == user_id)
            if status is not None:
                query = query.where(Task.status == status)
            if kind is not None:
                query = query.where(Task.kind == kind)

            query = query.order_by(Task.created_at.desc())
            result = await session.execute(query)
            return list(result.scalars().all())

    async def cancel_task(self, task_id: int) -> bool:
        """取消任务

        Args:
            task_id: 任务ID

        Returns:
            是否取消成功
        """
        async with get_session() as session:
            repo = TaskRepository(session)
            task = await repo.get(task_id)

            if task is None:
                return False

            from .state_machine import TaskStateMachine

            machine = TaskStateMachine()
            machine._status = TaskStatus(task.status)

            if not machine.cancel():
                logger.warning(
                    "任务状态不允许取消 task_id=%d status=%s",
                    task_id,
                    task.status,
                )
                return False

            updated = await repo.update_status(task_id, "cancelled")
            if updated:
                logger.info("任务已取消 task_id=%d", task_id)

            return updated

    async def retry_task(self, task_id: int) -> bool:
        """重试失败任务

        Args:
            task_id: 任务ID

        Returns:
            是否重试成功
        """
        async with get_session() as session:
            repo = TaskRepository(session)
            task = await repo.get(task_id)

            if task is None:
                return False

            from .state_machine import TaskStateMachine

            machine = TaskStateMachine()
            machine._status = TaskStatus(task.status)
            machine._retry_count = task.attempts

            if not machine.retry():
                logger.warning(
                    "任务不允许重试 task_id=%d status=%s attempts=%d",
                    task_id,
                    task.status,
                    task.attempts,
                )
                return False

            updated = await repo.update_status(task_id, "pending")
            if updated:
                await self._queue.put(task_id)
                logger.info("任务已重新入队 task_id=%d", task_id)

            return updated

    # ------------------------------------------------------------------
    # 任务执行
    # ------------------------------------------------------------------

    async def process_task(self, task: Task) -> dict[str, object]:
        """处理任务（执行下载/导出逻辑）

        Args:
            task: 任务对象

        Returns:
            执行结果
        """
        handlers: dict[str, TaskHandler] = {
            "download_book": self._handle_download_book,
            "update_shelf": self._handle_update_shelf,
            "export_book": self._handle_export_book,
            "sync_chapters": self._handle_sync_chapters,
        }

        handler = handlers.get(task.kind)
        if handler is None:
            raise ValueError(f"未实现的任务类型: {task.kind}")

        return await handler(task)

    async def _handle_download_book(self, task: Task) -> dict[str, object]:
        """处理下载书籍任务"""
        urls_obj = task.payload.get("urls", [])
        urls = [str(u) for u in urls_obj] if isinstance(urls_obj, list) else []
        if not urls:
            return {"error": "缺少URL参数"}

        export_format = str(task.payload.get("export_format", "md"))
        output_dir = task.payload.get("output_dir")
        output_dir_str = str(output_dir) if output_dir is not None else None

        events: list[dict[str, Any]] = []

        if self._download_service is None:
            self._download_service = DownloadService()

        async for event in self._download_service.download(
            urls=urls,
            export_format=export_format,
            output_dir=output_dir_str,
        ):
            events.append(self._event_to_dict(event))

        last_event = events[-1] if events else {}
        if last_event.get("type") == "error":
            return {"events": events, "success": False}

        return {"events": events, "success": True}

    async def _handle_update_shelf(self, task: Task) -> dict[str, object]:
        """处理更新书架任务"""
        events: list[dict[str, Any]] = []

        if self._download_service is None:
            self._download_service = DownloadService()

        async for event in self._download_service.update_shelf():
            events.append(self._event_to_dict(event))

        return {"events": events}

    async def _handle_export_book(self, task: Task) -> dict[str, object]:
        """处理导出书籍任务"""
        book_title = task.payload.get("book_title")
        export_format = task.payload.get("export_format", "md")

        if not book_title:
            return {"error": "缺少书名参数"}

        return {
            "message": f"导出任务已处理: {book_title}",
            "format": export_format,
        }

    async def _handle_sync_chapters(self, task: Task) -> dict[str, object]:
        """处理同步章节任务"""
        url_obj = task.payload.get("url")
        url = str(url_obj) if url_obj else None

        if not url:
            return {"error": "缺少URL参数"}

        if self._download_service is None:
            self._download_service = DownloadService()

        events: list[dict[str, Any]] = []
        async for event in self._download_service.download(
            urls=[url],
            list_only=True,
        ):
            events.append(self._event_to_dict(event))

        return {"events": events}

    def _event_to_dict(self, event: ProgressEvent) -> dict[str, Any]:
        """将进度事件转换为字典"""
        return {
            "type": event.type,
            "message": event.message,
            "total": event.total,
            "downloaded": event.downloaded,
            "current": event.current,
            "book_title": event.book_title,
            "output_files": event.output_files,
        }

    # ------------------------------------------------------------------
    # Worker 生命周期管理
    # ------------------------------------------------------------------

    async def start(self, worker_count: int = 2) -> None:
        """启动任务管理器"""
        if self._running:
            logger.warning("任务管理器已运行")
            return

        self._running = True
        logger.info("启动任务管理器，worker数量: %d", worker_count)

        signal.signal(signal.SIGTERM, self._handle_sigterm)

        for i in range(worker_count):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)

        await self._recover_pending_tasks()

    async def stop(self) -> None:
        """停止任务管理器"""
        if not self._running:
            return

        logger.info("正在停止任务管理器...")
        self._running = False

        for worker in self._workers:
            worker.cancel()

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
            logger.info("所有worker已停止")

        self._workers.clear()

    def _handle_sigterm(self, sig: int, frame: Any) -> None:
        """处理 SIGTERM 信号"""
        logger.info("收到 SIGTERM 信号，准备优雅停机")
        self._stop_task = asyncio.create_task(self.stop())

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker 主循环"""
        logger.info("Worker %d 已启动", worker_id)

        try:
            while self._running:
                try:
                    task_id = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                await self._execute_task(task_id)
                self._queue.task_done()

        except asyncio.CancelledError:
            logger.info("Worker %d 已取消", worker_id)
        except Exception as e:
            logger.error("Worker %d 异常退出: %s", worker_id, e)
        finally:
            logger.info("Worker %d 已停止", worker_id)

    async def _execute_task(self, task_id: int) -> None:
        """执行单个任务"""
        async with get_session() as session:
            repo = TaskRepository(session)
            task = await repo.get(task_id)

            if task is None:
                logger.warning("任务不存在 task_id=%d", task_id)
                return

            from .state_machine import TaskStateMachine

            machine = TaskStateMachine()
            machine._status = TaskStatus(task.status)
            machine._retry_count = task.attempts

            if not machine.pick():
                logger.warning(
                    "任务状态不允许执行 task_id=%d status=%s",
                    task_id,
                    task.status,
                )
                return

            await repo.update_status(task_id, "running")
            logger.info("开始执行任务 task_id=%d kind=%s", task_id, task.kind)

            try:
                result = await self.process_task(task)

                if result.get("success") is False:
                    machine.fail()
                    error = result.get("error")
                    error_str = str(error) if error is not None else None
                    await repo.increment_attempt(task_id, error_str)
                    await repo.update_status(task_id, "failed", result)
                    logger.error("任务执行失败 task_id=%d", task_id)
                else:
                    machine.success()
                    await repo.update_status(task_id, "completed", result)
                    logger.info("任务执行完成 task_id=%d", task_id)

            except Exception as e:
                machine.fail()
                await repo.increment_attempt(task_id, str(e))
                await repo.update_status(task_id, "failed", {"error": str(e)})
                logger.exception("任务执行异常 task_id=%d", task_id)

    async def _recover_pending_tasks(self) -> None:
        """恢复 pending 状态的任务到队列"""
        async with get_session() as session:
            repo = TaskRepository(session)
            tasks = await repo.list_pending()

        for task in tasks:
            await self._queue.put(task.id)
            logger.info("恢复任务到队列 task_id=%d", task.id)

        logger.info("共恢复 %d 个待处理任务", len(tasks))


# 全局单例
_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    """获取全局任务管理器实例"""
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager
