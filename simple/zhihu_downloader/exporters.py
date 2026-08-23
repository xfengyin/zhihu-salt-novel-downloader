"""导出器 - 把解析结果导出为 txt / md / epub。"""

from __future__ import annotations

import re
from pathlib import Path

try:
    from ebooklib import epub
except ImportError:  # pragma: no cover - 未安装 ebooklib 时降级
    epub = None  # type: ignore[assignment]


class ExportError(Exception):
    """导出失败。"""


def safe_filename(name: str, max_len: int = 80) -> str:
    """文件名安全化：去非法字符与首尾空白，限制长度。"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    name = re.sub(r"\s+", " ", name).strip().strip(".")
    # 全部由非法字符组成时回退为默认名
    if not name or not name.strip("_ "):
        name = "zhihu"
    return name[:max_len].rstrip(".").rstrip(" ")


def _resolve_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_txt(title: str, articles: list[dict], output_dir: str | Path) -> str:
    """导出为单个 txt（标题 + 正文）。"""
    output_dir = _resolve_output_dir(output_dir)
    filename = safe_filename(title) + ".txt"
    path = output_dir / filename

    parts: list[str] = []
    for article in articles:
        parts.append(article["title"])
        parts.append("")
        parts.append(article["content"])
        parts.append("")
        parts.append("-" * 40)
        parts.append("")

    path.write_text("\n".join(parts), encoding="utf-8")
    return str(path)


def export_md(title: str, articles: list[dict], output_dir: str | Path) -> str:
    """导出为单个 Markdown（带标题与来源链接）。"""
    output_dir = _resolve_output_dir(output_dir)
    filename = safe_filename(title) + ".md"
    path = output_dir / filename

    parts: list[str] = []
    for article in articles:
        parts.append(f"# {article['title']}")
        parts.append("")
        if article.get("url"):
            parts.append(f"> 来源：{article['url']}")
            parts.append("")
        parts.append(article["content"])
        parts.append("")

    path.write_text("\n".join(parts), encoding="utf-8")
    return str(path)


def export_epub(title: str, articles: list[dict], output_dir: str | Path) -> str:
    """导出为单个 EPUB（每章一个章节）。"""
    if epub is None:
        raise ExportError("未安装 ebooklib，无法导出 epub（请 pip install ebooklib）")

    output_dir = _resolve_output_dir(output_dir)
    filename = safe_filename(title) + ".epub"
    path = output_dir / filename

    book = epub.EpubBook()
    book.set_identifier(f"zhihu-{abs(hash(title)) & 0xFFFFFFFF:x}")
    book.set_title(title)
    book.set_language("zh-CN")

    chapters = []
    for i, article in enumerate(articles):
        chapter = epub.EpubHtml(
            title=article["title"],
            file_name=f"chapter_{i}.xhtml",
            lang="zh-CN",
        )
        body = f"<h1>{_escape(article['title'])}</h1>\n"
        for para in article["content"].split("\n"):
            para = para.strip()
            if para:
                body += f"<p>{_escape(para)}</p>\n"
        chapter.content = body
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.spine = ["nav"] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(path), book)
    return str(path)


def _escape(text: str) -> str:
    """最小 HTML 转义。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def export(title: str, articles: list[dict], fmt: str, output_dir: str | Path) -> list[str]:
    """按格式导出，返回生成的文件路径列表。"""
    fmt = fmt.lower()
    if fmt == "txt":
        return [export_txt(title, articles, output_dir)]
    if fmt == "md":
        return [export_md(title, articles, output_dir)]
    if fmt == "epub":
        return [export_epub(title, articles, output_dir)]
    raise ExportError(f"不支持的导出格式: {fmt}（支持 txt/md/epub）")
