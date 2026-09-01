"""导出层统一入口（规格书 §2.12）。

对外只暴露四样东西：

    FORMATS      —— 支持的格式元组 ("txt", "md", "epub")
    export_book  —— 按格式导出整本书，返回生成文件路径列表
    safe_filename / resolve_output_dir —— 供 CLI 与 Web 层复用的文件名工具

各格式模块（txt.py / md.py / epub.py）各自实现
export(title, articles, output_dir) -> str(path)，本模块只做分发。
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ExportError
from ..types import Article
from . import epub, md, txt
from .base import book_identifier, chapter_display_title, resolve_output_dir, safe_filename

__all__ = [
    "FORMATS",
    "book_identifier",
    "chapter_display_title",
    "export_book",
    "resolve_output_dir",
    "safe_filename",
]

#: 支持的导出格式（顺序即 CLI --format 的提示顺序）。
FORMATS: tuple[str, ...] = ("txt", "md", "epub")

#: 格式 → 导出函数。每个函数签名：export(title, articles, output_dir) -> str
_EXPORTERS = {"txt": txt.export, "md": md.export, "epub": epub.export}


def export_book(title: str, articles: list[Article], fmt: str, output_dir: str | Path) -> list[str]:
    """按指定格式把整本书导出到目录。

    Args:
        title: 书名（决定输出文件名）。
        articles: 有序章节列表（types.Article）。
        fmt: 目标格式，大小写不敏感，取值见 FORMATS。
        output_dir: 输出目录，不存在时自动创建。

    Returns:
        生成文件的路径列表（当前每种格式产出单个文件，长度恒为 1）。

    Raises:
        ExportError: 格式不支持，或底层导出失败（消息为中文、含下一步建议）。
    """
    key = (fmt or "").strip().lower()
    exporter = _EXPORTERS.get(key)
    if exporter is None:
        raise ExportError(f"不支持的导出格式「{fmt}」，请改用 {' / '.join(FORMATS)} 之一")
    return [exporter(title, articles, output_dir)]
