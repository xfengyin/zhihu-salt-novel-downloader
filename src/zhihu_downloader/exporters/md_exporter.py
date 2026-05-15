"""Markdown导出器"""

from __future__ import annotations

import logging
from pathlib import Path

from .base_exporter import BaseExporter

if True:
    from zhihu_downloader.parsers.article_parser import ArticleInfo


logger = logging.getLogger(__name__)


class MarkdownExporter(BaseExporter):
    """Markdown导出器"""

    def export(self, article_info: ArticleInfo | dict) -> Path:
        """
        导出为Markdown文件

        Args:
            article_info: 文章信息

        Returns:
            输出文件路径
        """
        if isinstance(article_info, dict):
            title = article_info.get("title", "未知标题")
            author = article_info.get("author", "未知作者")
            chapters_list = article_info.get("chapters", [])
        else:
            title = article_info.title
            author = article_info.author
            chapters_list = article_info.chapters

        safe_title = self.sanitize_filename(title)
        output_path = self.output_dir / f"{safe_title}.md"

        content = self._build_markdown(title, author, chapters_list)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info("Markdown导出完成: %s", output_path)
        return output_path

    def _build_markdown(
        self,
        title: str,
        author: str,
        chapters: list[dict],
    ) -> str:
        """构建Markdown内容"""
        lines: list[str] = []

        lines.append(f"# {title}\n")
        lines.append(f"> 作者：{author}\n")
        lines.append("---\n")

        for chapter in chapters:
            ch_title = chapter.get("title", "")
            ch_content = chapter.get("content", "")
            ch_type = chapter.get("type", "normal")

            if ch_type == "extra":
                lines.append(f"\n## 【番外】{ch_title}\n")
            elif ch_type == "author_note":
                lines.append(f"\n## 【作者说】{ch_title}\n")
            else:
                lines.append(f"\n## {ch_title}\n")

            if ch_content:
                lines.append(f"{ch_content}\n")

        return "\n".join(lines)
