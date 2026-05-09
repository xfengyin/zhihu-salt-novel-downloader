"""EPUB电子书导出器"""

import logging
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from ebooklib import epub

from .base_exporter import BaseExporter


logger = logging.getLogger(__name__)


class EpubExporter(BaseExporter):
    """EPUB电子书导出器"""
    
    def __init__(self, output_dir: Path):
        super().__init__(output_dir)
        self._css = self._get_epub_css()
    
    def _get_epub_css(self) -> str:
        """获取EPUB样式"""
        return """
        body {
            font-family: 'SimSun', '宋体', serif;
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
    
    def export(self, article_info: Dict[str, Any]) -> Path:
        """
        导出为EPUB文件
        
        Args:
            article_info: 文章信息字典
            
        Returns:
            输出文件路径
        """
        title = article_info.get('title', '未知标题')
        safe_title = self.sanitize_filename(title)
        output_path = self.output_dir / f"{safe_title}.epub"
        
        # 创建EPUB书籍
        book = epub.EpubBook()
        
        # 设置元数据
        book.set_identifier(f'zhihu-{safe_title}-{datetime.now().strftime("%Y%m%d%H%M%S")}')
        book.set_title(title)
        book.set_language('zh-CN')
        book.add_author(article_info.get('author', '未知作者'))
        
        # 添加CSS样式
        style_css = epub.EpubItem(
            uid='style_default',
            file_name='style.css',
            media_type='text/css',
            content=self._css
        )
        book.add_item(style_css)
        
        chapters = article_info.get('chapters', [])
        grouped = self.group_chapters(chapters)
        
        # 创建章节
        epub_chapters: List[epub.EpubHtml] = []
        
        # 正文
        for i, chapter in enumerate(grouped['normal'], 1):
            ch = self._create_chapter(
                chapter,
                book,
                style_css,
                f'chapter_{i}',
                index=i
            )
            if ch:
                epub_chapters.append(ch)
        
        # 番外
        for i, chapter in enumerate(grouped['extra'], 1):
            ch = self._create_chapter(
                chapter,
                book,
                style_css,
                f'extra_{i}',
                is_extra=True
            )
            if ch:
                epub_chapters.append(ch)
        
        # 作者说
        for i, chapter in enumerate(grouped['author_note'], 1):
            ch = self._create_chapter(
                chapter,
                book,
                style_css,
                f'author_note_{i}',
                is_author_note=True
            )
            if ch:
                epub_chapters.append(ch)
        
        # 添加章节到书籍
        book.toc = tuple(epub_chapters)
        
        # 添加章节到spine
        book.spine = ['nav'] + epub_chapters
        
        # 添加nav
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        # 写入文件
        epub.write_epub(str(output_path), book, {})
        
        logger.info(f"EPUB导出完成: {output_path}")
        return output_path
    
    def _create_chapter(
        self,
        chapter: Dict,
        book: epub.EpubBook,
        style_css: epub.EpubItem,
        uid: str,
        index: int = 0,
        is_extra: bool = False,
        is_author_note: bool = False
    ) -> epub.EpubHtml:
        """
        创建EPUB章节
        
        Args:
            chapter: 章节信息
            book: EPUB书籍对象
            style_css: 样式CSS
            uid: 唯一标识
            index: 章节序号
            is_extra: 是否为番外
            is_author_note: 是否为作者说
            
        Returns:
            EpubHtml对象
        """
        title = chapter.get('title', f'第{index}章')
        content = chapter.get('content', '')
        
        # 添加前缀
        if is_extra:
            title = f"【番外】{title}"
        elif is_author_note:
            title = f"【作者说】{title}"
        
        # 创建HTML内容
        html_content = f"""<?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE html>
        <html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">
        <head>
            <title>{title}</title>
            <link rel="stylesheet" type="text/css" href="style.css" />
        </head>
        <body>
            <h2 class="chapter-title">{title}</h2>
            <div class="{'author-note' if is_author_note else ('extra' if is_extra else 'content')}">
            {content}
            </div>
        </body>
        </html>"""
        
        # 创建章节
        ch = epub.EpubHtml(
            title=title,
            file_name=f'{uid}.xhtml',
            lang='zh-CN',
            uid=uid
        )
        ch.content = html_content
        ch.add_link(href='style.css', rel='stylesheet', type='text/css')
        
        book.add_item(ch)
        
        return ch
