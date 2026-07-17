from enum import Enum
from typing import ClassVar


class TaskStatus(Enum):
    pending = "pending"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskKind(Enum):
    download_book = "download_book"
    update_shelf = "update_shelf"
    export_book = "export_book"
    sync_chapters = "sync_chapters"


class TaskStateMachine:
    MAX_RETRY_COUNT = 3
    BASE_RETRY_DELAY = 60

    VALID_TRANSITIONS: ClassVar[dict[TaskStatus, tuple[TaskStatus, ...]]] = {
        TaskStatus.pending: (TaskStatus.running, TaskStatus.cancelled),
        TaskStatus.running: (TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled),
        TaskStatus.paused: (TaskStatus.running, TaskStatus.cancelled),
        TaskStatus.completed: (TaskStatus.cancelled,),
        TaskStatus.failed: (TaskStatus.pending, TaskStatus.cancelled),
        TaskStatus.cancelled: (),
    }

    def __init__(self) -> None:
        self._status: TaskStatus = TaskStatus.pending
        self._retry_count: int = 0

    @property
    def status(self) -> TaskStatus:
        return self._status

    @property
    def retry_count(self) -> int:
        return self._retry_count

    def is_valid_transition(self, from_status: TaskStatus, to_status: TaskStatus) -> bool:
        return to_status in self.VALID_TRANSITIONS.get(from_status, ())

    def can_retry(self) -> bool:
        return self._status == TaskStatus.failed and self._retry_count < self.MAX_RETRY_COUNT

    def get_next_retry_delay(self) -> float:
        return float(self.BASE_RETRY_DELAY * (2 ** self._retry_count))

    def transition(self, to_status: TaskStatus) -> bool:
        if not self.is_valid_transition(self._status, to_status):
            return False

        if to_status == TaskStatus.failed:
            self._retry_count += 1
        elif to_status == TaskStatus.pending:
            pass
        elif to_status == TaskStatus.completed:
            self._retry_count = 0
        elif to_status == TaskStatus.cancelled:
            self._retry_count = 0
        elif to_status == TaskStatus.running:
            if self._status == TaskStatus.failed:
                pass
            else:
                self._retry_count = 0

        self._status = to_status
        return True

    def pick(self) -> bool:
        return self.transition(TaskStatus.running)

    def success(self) -> bool:
        return self.transition(TaskStatus.completed)

    def fail(self) -> bool:
        return self.transition(TaskStatus.failed)

    def retry(self) -> bool:
        if not self.can_retry():
            return False
        return self.transition(TaskStatus.pending)

    def cancel(self) -> bool:
        return self.transition(TaskStatus.cancelled)
