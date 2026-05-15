"""EPUB电子书导出器"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ebooklib import epub

from .base_exporter import BaseExporter

if True:
    from zhihu_downloader.parsers.article_parser import ArticleInfo


logger = logging.getLogger(__name__)


class EpubExporter(BaseExporter):
    """EPUB电子书导出器"""

    DEFAULT_CSS: str = """
        body {
            font-family: 'Georgia', 'SimSun', serif;
            line-height: 1.8;
            text-indent: 2em;
            margin: 1em;
        }
        h1 {
            text-align: center;
            font-size: 1.5em;
            margin: 2em 0;
        }
        h2 {
            text-align: center;
            font-size: 1.2em;
            margin: 1.5em 0;
        }
        h3 {
            font-size: 1.1em;
            margin: 1em 0;
        }
        p {
            line-height: 1.8;
            text-indent: 2em;
            margin: 0.5em 0;
        }
        .chapter-title {
            text-align: center;
            font-size: 1.2em;
            margin: 2em 0;
        }
        .author-note {
            font-style: italic;
            color: #666;
            background-color: #f5f5f5;
            padding: 1em;
            margin: 1em 0;
        }
        .extra {
            background-color: #fff3cd;
            padding: 0.5em;
            margin: 1em 0;
        }
    """

    def __init__(self, output_dir: Path) -> None:
        super().__init__(output_dir)
        self._css = self.DEFAULT_CSS

    def export(self, article_info: ArticleInfo | dict) -> Path:
        """
        导出为EPUB文件

        Args:
            article_info: 文章信息

        Returns:
            输出文件路径
        """
        if isinstance(article_info, dict):
            title = article_info.get("title", "未知标题")
        else:
            title = article_info.title

        safe_title = self.sanitize_filename(title)
        output_path = self.output_dir / f"{safe_title}.epub"

        book = epub.EpubBook()

        book.set_identifier(
            f"zhihu-{safe_title}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        book.set_title(title)

        if isinstance(article_info, dict):
            book.set_language("zh-CN")
            book.add_author(article_info.get("author", "未知作者"))
        else:
            book.set_language("zh-CN")
            book.add_author(article_info.author)

        style_css = epub.EpubItem(
            uid="style_default",
            file_name="style.css",
            media_type="text/css",
            content=self._css,
        )
        book.add_item(style_css)

        if isinstance(article_info, dict):
            chapters_list = article_info.get("chapters", [])
        else:
            chapters_list = article_info.chapters

        grouped = self.group_chapters(chapters_list)

        epub_chapters: list[epub.EpubHtml] = []

        for i, chapter in enumerate(grouped["normal"], 1):
            ch = self._create_chapter(chapter, book, style_css, f"chapter_{i}", index=i)
            if ch:
                epub_chapters.append(ch)

        for i, chapter in enumerate(grouped["extra"], 1):
            ch = self._create_chapter(
                chapter, book, style_css, f"extra_{i}", is_extra=True
            )
            if ch:
                epub_chapters.append(ch)

        for i, chapter in enumerate(grouped["author_note"], 1):
            ch = self._create_chapter(
                chapter, book, style_css, f"author_note_{i}", is_author_note=True
            )
            if ch:
                epub_chapters.append(ch)

        if not epub_chapters:
            placeholder_ch = self._create_placeholder_chapter(book, style_css)
            epub_chapters.append(placeholder_ch)

        book.toc = tuple(epub_chapters)
        book.spine = ["nav"] + epub_chapters

        book.add_item(epub.EpubNcx())

        try:
            nav = epub.EpubNav()
            book.add_item(nav)
        except Exception:
            pass

        epub.write_epub(str(output_path), book, {})

        logger.info("EPUB导出完成: %s", output_path)
        return output_path

    def _create_chapter(
        self,
        chapter: dict[str, Any],
        book: epub.EpubBook,
        style_css: epub.EpubItem,
        uid: str,
        index: int = 0,
        is_extra: bool = False,
        is_author_note: bool = False,
    ) -> epub.EpubHtml | None:
        """创建EPUB章节"""
        title = chapter.get("title", f"第{index}章")
        content = chapter.get("content", "")

        if is_extra:
            title = f"【番外】{title}"
        elif is_author_note:
            title = f"【作者说】{title}"

        content_class = "author-note" if is_author_note else ("extra" if is_extra else "content")

        html_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">\n'
            "<head>\n"
            f"<title>{title}</title>\n"
            '<link rel="stylesheet" type="text/css" href="style.css" />\n'
            "</head>\n"
            "<body>\n"
            f'<h2 class="chapter-title">{title}</h2>\n'
            f'<div class="{content_class}">\n'
            f"{content}\n"
            "</div>\n"
            "</body>\n"
            "</html>"
        )

        ch = epub.EpubHtml(
            title=title,
            file_name=f"{uid}.xhtml",
            lang="zh-CN",
            uid=uid,
        )
        ch.content = html_content
        ch.add_link(href="style.css", rel="stylesheet", type="text/css")

        book.add_item(ch)

        return ch

    def _create_placeholder_chapter(
        self,
        book: epub.EpubBook,
        style_css: epub.EpubItem,
    ) -> epub.EpubHtml:
        """创建占位章节"""
        html_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE html>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">\n'
            "<head>\n"
            "<title>内容</title>\n"
            '<link rel="stylesheet" type="text/css" href="style.css" />\n'
            "</head>\n"
            "<body>\n"
            '<h2 class="chapter-title">内容</h2>\n'
            '<div class="content">\n'
            "<p>请下载章节内容后重新导出。</p>\n"
            "</div>\n"
            "</body>\n"
            "</html>"
        )

        ch = epub.EpubHtml(
            title="内容",
            file_name="chapter_placeholder.xhtml",
            lang="zh-CN",
            uid="chapter_placeholder",
        )
        ch.content = html_content
        ch.add_link(href="style.css", rel="stylesheet", type="text/css")

        book.add_item(ch)

        return ch
