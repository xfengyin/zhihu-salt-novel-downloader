"""导出器基类"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zhihu_downloader.parsers.article_parser import ArticleInfo, Chapter


class BaseExporter(ABC):
    """导出器基类"""

    def __init__(self, output_dir: Path) -> None:
        """
        初始化导出器

        Args:
            output_dir: 输出目录
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def export(self, article_info: ArticleInfo | dict) -> Path:
        """
        导出文件

        Args:
            article_info: 文章信息

        Returns:
            输出文件路径
        """
        ...

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        清理文件名

        Args:
            filename: 原始文件名

        Returns:
            清理后的文件名
        """
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
        filename = filename.strip(". ")
        return filename or "untitled"

    def group_chapters(
        self, chapters: list[Chapter | dict]
    ) -> dict[str, list[Chapter | dict]]:
        """
        按类型分组章节

        Args:
            chapters: 章节列表

        Returns:
            分组后的章节字典
        """
        grouped: dict[str, list[Chapter | dict]] = {
            "normal": [],
            "extra": [],
            "author_note": [],
            "unknown": [],
        }

        for chapter in chapters:
            ch_type = chapter.get("type", "unknown") if isinstance(chapter, dict) else chapter.type
            if ch_type in grouped:
                grouped[ch_type].append(chapter)
            else:
                grouped["unknown"].append(chapter)

        return grouped

    def build_toc(
        self, chapters: list[Chapter | dict]
    ) -> str:
        """
        构建目录

        Args:
            chapters: 章节列表

        Returns:
            目录文本
        """
        lines = ["目录", ""]

        for chapter in chapters:
            title = chapter.get("title", "") if isinstance(chapter, dict) else chapter.title
            ch_type = chapter.get("type", "unknown") if isinstance(chapter, dict) else chapter.type

            prefix = ""
            if ch_type == "extra":
                prefix = "【番外】"
            elif ch_type == "author_note":
                prefix = "【作者说】"

            lines.append(f"{prefix}{title}")

        return "\n".join(lines)
