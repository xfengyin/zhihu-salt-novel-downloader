"""MOBI电子书导出器"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from .base_exporter import BaseExporter

if True:
    from zhihu_downloader.parsers.article_parser import ArticleInfo


logger = logging.getLogger(__name__)


class MobiExporter(BaseExporter):
    """MOBI电子书导出器"""

    def __init__(self, output_dir: Path) -> None:
        super().__init__(output_dir)
        self._kindlegen_path = self._find_kindlegen()

    def _find_kindlegen(self) -> str | None:
        """查找kindlegen可执行文件"""
        import shutil

        for name in ["kindlegen", "kindlegen.exe"]:
            path = shutil.which(name)
            if path:
                return path
        return None

    def export(self, article_info: ArticleInfo | dict[str, Any]) -> Path:
        """
        导出为MOBI文件

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
        output_path = self.output_dir / f"{safe_title}.mobi"

        if self._kindlegen_path:
            return self._export_with_kindlegen(
                title, author, chapters_list, output_path
            )
        else:
            return self._export_fallback(title, author, chapters_list, output_path)

    def _export_with_kindlegen(
        self,
        title: str,
        author: str,
        chapters: list[dict[str, Any]],
        output_path: Path,
    ) -> Path:
        """使用kindlegen导出"""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            opf_content = self._build_opf(title, author, chapters)
            opf_file = tmp_path / "content.opf"
            opf_file.write_text(opf_content, encoding="utf-8")

            ncx_content = self._build_ncx(title, chapters)
            ncx_file = tmp_path / "toc.ncx"
            ncx_file.write_text(ncx_content, encoding="utf-8")

            for i, chapter in enumerate(chapters, 1):
                html_content = self._build_chapter_html(chapter, i)
                ch_file = tmp_path / f"ch{i:03d}.html"
                ch_file.write_text(html_content, encoding="utf-8")

            cmd: list[str] = [self._kindlegen_path, str(opf_file), "-o", str(output_path.name)]
            subprocess.run(
                cmd,
                cwd=str(tmp_path),
                capture_output=True,
                text=True,
            )

        logger.info("MOBI导出完成: %s", output_path)
        return output_path

    def _export_fallback(
        self,
        title: str,
        author: str,
        chapters: list[dict[str, Any]],
        output_path: Path,
    ) -> Path:
        """回退导出（无kindlegen时）"""
        content = self._build_text_content(title, author, chapters)
        output_path.write_text(content, encoding="utf-8")
        logger.warning("kindlegen未找到，导出为TXT格式（重命名为.mobi）")
        return output_path

    def _build_opf(
        self,
        title: str,
        author: str,
        chapters: list[dict[str, Any]],
    ) -> str:
        """构建OPF文件内容"""
        root = Element("package", xmlns="http://www.idpf.org/2007/opf", version="2.0", unique_identifier="bookid")

        metadata_attrs = {
            "xmlns:dc": "http://purl.org/dc/elements/1.1/",
            "xmlns:opf": "http://www.idpf.org/2007/opf"
        }
        metadata = SubElement(root, "metadata", metadata_attrs)
        SubElement(metadata, "dc:title").text = title
        SubElement(metadata, "dc:creator", {"opf:role": "aut"}).text = author
        SubElement(metadata, "dc:language").text = "zh"
        SubElement(metadata, "dc:identifier", {"id": "bookid", "opf:scheme": "ISBN"}).text = "978-0-000-00000-0"

        manifest = SubElement(root, "manifest")
        SubElement(manifest, "item", id="ncx", href="toc.ncx", media_type="application/x-dtbncx+xml")

        for i, _chapter in enumerate(chapters, 1):
            SubElement(manifest, "item", id=f"ch{i}", href=f"ch{i:03d}.html", media_type="application/xhtml+xml")

        spine = SubElement(root, "spine", toc="ncx")
        for i in range(1, len(chapters) + 1):
            SubElement(spine, "itemref", idref=f"ch{i}")

        guide = SubElement(root, "guide")
        SubElement(guide, "reference", type="toc", title="目录", href="toc.ncx")

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")

    def _build_ncx(
        self,
        title: str,
        chapters: list[dict[str, Any]],
    ) -> str:
        """构建NCX目录文件"""
        root = Element("ncx", xmlns="http://www.daisy.org/z3986/2005/ncx/", version="2005-1")

        head = SubElement(root, "head")
        SubElement(head, "meta", name="dtb:uid", content="urn:uuid:placeholder")
        SubElement(head, "meta", name="dtb:depth", content="1")
        SubElement(head, "meta", name="dtb:totalPageCount", content="0")
        SubElement(head, "meta", name="dtb:maxPageNumber", content="0")

        doc_title = SubElement(root, "docTitle")
        SubElement(doc_title, "text").text = title

        nav_map = SubElement(root, "navMap")

        for i, chapter in enumerate(chapters, 1):
            nav_point = SubElement(nav_map, "navPoint", id=f"nav{i}", playOrder=str(i))
            nav_label = SubElement(nav_point, "navLabel")
            SubElement(nav_label, "text").text = chapter.get("title", f"第{i}章")
            SubElement(nav_point, "content", src=f"ch{i:03d}.html")

        return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(root, encoding="unicode")

    def _build_chapter_html(self, chapter: dict[str, Any], index: int) -> str:
        """构建章节HTML"""
        title = chapter.get("title", f"第{index}章")
        content = chapter.get("content", "")

        html = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<title>{title}</title>
</head>
<body>
<h1>{title}</h1>
{content}
</body>
</html>"""
        return html

    def _build_text_content(
        self,
        title: str,
        author: str,
        chapters: list[dict[str, Any]],
    ) -> str:
        """构建纯文本内容"""
        lines: list[str] = []
        lines.append(title)
        lines.append("=" * 50)
        lines.append(f"作者：{author}\n")

        for chapter in chapters:
            ch_title = chapter.get("title", "")
            ch_content = chapter.get("content", "")
            ch_type = chapter.get("type", "normal")

            if ch_type == "extra":
                lines.append(f"\n【番外】{ch_title}\n")
            elif ch_type == "author_note":
                lines.append(f"\n【作者说】{ch_title}\n")
            else:
                lines.append(f"\n{ch_title}\n")

            if ch_content:
                lines.append(f"{ch_content}\n")

        return "\n".join(lines)
