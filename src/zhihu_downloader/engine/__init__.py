"""engine：知乎客户端与下载编排（HTTP 客户端 / 断点存储 / 下载流程）。

对外稳定 API 见 __all__；实现细节分别在同名子模块中。
"""

from __future__ import annotations

from .checkpoint import CheckpointStore
from .client import DEFAULT_USER_AGENT, ZhihuClient
from .fetcher import check_new_chapters, download_book, resolve_book

__all__ = [
    "DEFAULT_USER_AGENT",
    "CheckpointStore",
    "ZhihuClient",
    "check_new_chapters",
    "download_book",
    "resolve_book",
]
