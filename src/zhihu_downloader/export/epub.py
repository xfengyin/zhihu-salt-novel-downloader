"""EPUB 导出器（ebooklib，规格书 §2.12）。

实现要点：
  * identifier = sha1(f"{title}|{首章 url}") 的十六进制，跨进程稳定（不用 hash()）；
  * 封面：程序生成的 SVG 封面图（ebooklib 图片项，零额外依赖）+ 封面页（书名大字、
    作者占位、章节数）；
  * TOC 两级：正文章归入「正文」节点，番外/作者说按 chapter_type 归入「附录」节点；
  * 图片块（R2 审计 #5 · 终局定稿 containment，**冻结于 A10 门禁**，
    spec §2.12/§6 表同步）：唯一判据 = **(output_dir/src) resolve 后的
    realpath 必须落在 output_dir 之内**（is_relative_to）——绝对/相对/../
    软链同判据：框外（真攻击面）必拒、框内必嵌（v5.1 图片下载回填），
    双钉焊死在 scripts/acceptance.py A10，翻转即 FAIL；SVG/SVGZ（可携带
    脚本）一律不内嵌；"~" 不做 expanduser，按字面组件挂在 output_dir 下
    解析（通常不存在 → 自然降级 alt，无第二条展开通路）；
  * 内嵌基础 CSS：段首缩进 2em、行距 1.6、标题/引用/图片样式。
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any

from ..errors import ExportError
from ..types import Article
from .base import (
    AUTHOR_PLACEHOLDER,
    book_identifier,
    chapter_display_title,
    html_escape,
    is_appendix,
    resolve_output_dir,
    safe_filename,
)

try:  # pragma: no cover - ebooklib 是声明的运行时依赖，缺失时给出可操作提示
    from ebooklib import epub as _epub
except ImportError:  # pragma: no cover
    _epub = None  # type: ignore[assignment]

__all__ = ["build_cover_svg", "export", "render_chapter_body"]

#: 封面图与封面页、样式表在 EPUB 内的文件名。
COVER_IMAGE_NAME = "cover_image.svg"
COVER_PAGE_NAME = "cover.xhtml"
CSS_FILE_NAME = "style/default.css"

#: 内嵌基础样式：段首缩进 2em、行距 1.6、标题层级样式。
BASE_CSS = """body { font-family: "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", serif;
       line-height: 1.6; margin: 1em; color: #222; }
h1.chapter-title { font-size: 1.6em; line-height: 1.6; text-align: center;
                   margin: 1.6em 0 1em; page-break-before: always; }
h2 { font-size: 1.3em; line-height: 1.6; margin: 1.2em 0 0.6em; }
h3 { font-size: 1.15em; line-height: 1.6; margin: 1em 0 0.5em; }
p { text-indent: 2em; line-height: 1.6; margin: 0.4em 0; }
ul { margin: 0.5em 0; padding-left: 2em; }
li { line-height: 1.6; text-indent: 0; margin: 0.2em 0; }
blockquote { margin: 0.8em 1.5em; padding: 0.3em 0.8em; color: #555;
             border-left: 3px solid #ccc; font-style: italic; }
blockquote p { text-indent: 0; margin: 0; }
p.source { text-indent: 0; font-size: 0.85em; color: #888; text-align: center;
           word-break: break-all; margin: 0 0 1.5em; }
div.figure { text-indent: 0; text-align: center; margin: 1em 0; }
div.figure img { max-width: 100%; }
p.image-alt { text-indent: 0; text-align: center; color: #888; font-style: italic; }
div.cover { text-indent: 0; text-align: center; margin-top: 18%; }
div.cover img { max-width: 100%; }
h1.cover-title { font-size: 2.2em; text-indent: 0; margin: 0.8em 0 0.2em; }
p.cover-author { text-indent: 0; color: #666; margin: 0.2em 0; }
"""

#: 可内嵌的图片扩展名 → media_type（未知扩展名再走 mimetypes 猜测，猜不出则降级）。
#: 刻意不含 .svg/.svgz：SVG 是 XML 文档、可携带脚本，见 EMBED_BLOCKED_SUFFIXES。
IMAGE_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: 无论来自何处都不内嵌的扩展名（SVG 家族可携带脚本，阅读器执行面不可控）。
EMBED_BLOCKED_SUFFIXES: frozenset[str] = frozenset({".svg", ".svgz"})

#: 内嵌进 EPUB 包内的文件扩展名白名单形态（防远端 src 拼出畸形 zip 条目名）。
_SAFE_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9]{1,8}$")


def build_cover_svg(title: str, author: str, chapters: int) -> bytes:
    """生成封面图（纯标准库拼装的 SVG，避免引入 Pillow 等额外运行时依赖）。

    Args:
        title: 书名（自动折行，最多 5 行）。
        author: 作者占位文本。
        chapters: 章节数，印在封面底部。

    Returns:
        UTF-8 编码后的 SVG 字节串。
    """
    width, height = 600, 800
    lines = _wrap_text(title, 11)[:5]
    start_y = 300 - (len(lines) - 1) * 30
    spans = "".join(
        f'<text x="300" y="{start_y + i * 60}" font-size="52" fill="#f2e6c8" '
        f'font-family="serif" text-anchor="middle">{html_escape(line)}</text>'
        for i, line in enumerate(lines)
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="#1f3a5f"/><stop offset="100%" stop-color="#0b1622"/>'
        f'</stop></linearGradient></defs>'
        f'<rect width="{width}" height="{height}" fill="url(#bg)"/>'
        f'<rect x="36" y="36" width="{width - 72}" height="{height - 72}" fill="none" '
        f'stroke="#e8d8a8" stroke-width="3"/>'
        f'{spans}'
        f'<text x="300" y="640" font-size="30" fill="#cbb98a" font-family="serif" '
        f'text-anchor="middle">{html_escape(author)}</text>'
        f'<text x="300" y="690" font-size="22" fill="#8fa3bd" font-family="serif" '
        f'text-anchor="middle">共 {chapters} 章 · 知乎盐选备份</text>'
        f'</svg>'
    )
    return svg.encode("utf-8")


def _wrap_text(text: str, size: int) -> list[str]:
    """按固定字符数折行（中文书名排版用）。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return [""]
    return [cleaned[i : i + size] for i in range(0, len(cleaned), size)]


def _embed_image(src: str, book: Any, cache: dict[str, str], output_dir: Path) -> str | None:
    """把 output_dir 内的本地图片文件内嵌进 book，返回章节内可引用的相对路径。

    安全不变量（R2 审计 #5 · 终局定稿 containment，默认拒绝）：

      1. 唯一判据是 resolve（跟随符号链接）后的 realpath 落在 output_dir
         之内：相对 src 以 output_dir 为根解析；绝对 src 在 pathlib join 下
         整体替换左值，因此框外绝对路径、"../" 逃逸与软链指出去被同一条
         is_relative_to 边界检查挡掉 → 降级 alt。真攻击面（诱导把 output_dir
         外的本机文件读进 EPUB）全量钉死；框内绝对路径是合法用例
         （v5.1 图片下载回填）；
      2. "~" 不做 expanduser：Path("~/x") 非绝对路径，按字面组件挂在
         output_dir 下解析，通常不存在 → 自然降级 alt，不存在"展开到
         $HOME 再判"的第二条通路；
      3. SVG / SVGZ 一律不内嵌（XML 文档可携带脚本）；条目扩展名另过
         ".[A-Za-z0-9]{1,8}" 白名单，防畸形 zip 条目名。

    冻结机制（round49 终局）：规则不再靠注释约束，而是焊死在
    scripts/acceptance.py A10 门禁——框外必拒 + 框内必嵌双钉，任何翻转
    （包括主审）都会让 A10 直接 FAIL；spec §2.12 与 §6 表已同步本表述。

    Args:
        src: Block.src，可能是本地相对路径，也可能是远端 URL。
        book: ebooklib 的 EpubBook 实例。
        cache: 「解析后的本机 realpath → EPUB 内路径」去重表（同一张图只嵌一次）。
        output_dir: 本次导出的输出目录，相对 src 的解析根与越界判定边界。

    Returns:
        EPUB 内的相对路径；不可内嵌（绝对路径/越界/SVG/远端地址/文件缺失/
        格式未知/读取失败）时返回 None，由调用方降级为 alt 文本。
    """
    raw = (src or "").strip()
    if not raw:
        return None
    # 唯一判据（定稿 containment，A10 门禁冻结）：realpath 是否落在
    # output_dir 之内。pathlib 语义下绝对 src 整体替换 join 左值 →
    # 绝对/相对/"../"/符号链接走同一条边界检查；"~" 不做 expanduser，
    # 按字面组件解析（通常不存在 → 自然降级 alt）。
    out_root = Path(output_dir).resolve()
    try:
        candidate = (out_root / Path(raw)).resolve()
    except OSError:  # pragma: no cover - 特殊文件系统上的解析失败
        return None
    if not candidate.is_relative_to(out_root):
        return None
    suffix = candidate.suffix.lower()
    if suffix in EMBED_BLOCKED_SUFFIXES:  # SVG 家族可携带脚本，永不内嵌
        return None
    if not candidate.is_file():  # 远端 URL 或本地已缺失 → 由调用方降级为 alt 文本
        return None
    key = str(candidate)
    if key in cache:
        return cache[key]
    try:
        data = candidate.read_bytes()
    except OSError:
        return None
    media_type = IMAGE_MEDIA_TYPES.get(suffix) or mimetypes.guess_type(candidate.name)[0]
    if not media_type or not media_type.startswith("image/"):
        return None
    index = len(cache)
    ext = suffix if _SAFE_SUFFIX_RE.fullmatch(suffix) else ".bin"
    file_name = f"images/image_{index}{ext}"
    book.add_item(_epub.EpubImage(uid=f"image_{index}", file_name=file_name, media_type=media_type, content=data))
    cache[key] = file_name
    return file_name


def render_chapter_body(
    article: Article, book: Any, image_cache: dict[str, str], output_dir: Path
) -> str:
    """把一篇文章的 Block 列表渲染为 EPUB 章节正文 XHTML 片段。

    Args:
        article: 章节数据。
        book: ebooklib 的 EpubBook 实例（内嵌图片时用于 add_item）。
        image_cache: 图片去重表，跨章节共享。
        output_dir: 本次导出目录；图片内嵌的安全边界（见 _embed_image）。

    Returns:
        body 内的 XHTML 片段字符串。
    """
    parts: list[str] = [f'<h1 class="chapter-title">{html_escape(chapter_display_title(article))}</h1>']
    if article.url:
        url = html_escape(article.url)
        parts.append(f'<p class="source">来源：<a href="{url}">{url}</a></p>')

    list_buffer: list[str] = []

    def flush_list() -> None:
        """把缓冲的 li 输出为一个 ul。"""
        if list_buffer:
            items = "".join(f"<li>{html_escape(item)}</li>" for item in list_buffer)
            parts.append(f"<ul>{items}</ul>")
            list_buffer.clear()

    has_body = False
    for block in article.blocks:
        text = block.text.strip()
        if block.kind == "li":
            if text:
                list_buffer.append(text)
                has_body = True
            continue
        flush_list()
        if block.kind in ("h2", "h3"):
            if text:
                parts.append(f"<{block.kind}>{html_escape(text)}</{block.kind}>")
                has_body = True
        elif block.kind == "quote":
            if text:
                parts.append(f"<blockquote><p>{html_escape(text)}</p></blockquote>")
                has_body = True
        elif block.kind == "img":
            href = _embed_image(block.src, book, image_cache, output_dir)
            alt = html_escape(block.alt.strip() or "图片")
            if href:
                parts.append(f'<div class="figure"><img alt="{alt}" src="{href}"/></div>')
            else:
                # 远端地址 / 绝对路径 / realpath 越界 / SVG / 文件缺失：降级 alt，不留坏图。
                parts.append(f'<p class="image-alt">[图片：{alt}]</p>')
            has_body = True
        else:  # p 及其它未知块按段落处理
            if text:
                parts.append(f"<p>{html_escape(text)}</p>")
                has_body = True
    flush_list()
    if not has_body:
        parts.append('<p class="image-alt">（本章无正文）</p>')
    return "\n".join(parts)


def _make_chapter(
    article: Article, index: int, book: Any, image_cache: dict[str, str], output_dir: Path
) -> Any:
    """构造单章 EpubHtml（标题 + 来源 + 正文 + 样式链接）并登记到 book。"""
    chapter = _epub.EpubHtml(
        title=chapter_display_title(article),
        file_name=f"chapter_{index}.xhtml",
        lang="zh-CN",
        uid=f"chapter_{index}",
    )
    chapter.content = f"<html><body>{render_chapter_body(article, book, image_cache, output_dir)}</body></html>"
    chapter.add_link(href=CSS_FILE_NAME, rel="stylesheet", type="text/css")
    book.add_item(chapter)
    return chapter


def export(title: str, articles: list[Article], output_dir: str | Path) -> str:
    """导出为单个 .epub 文件。

    Args:
        title: 书名（同时决定文件名与元数据）。
        articles: 有序章节列表；为空时生成一本带占位章节的书。
        output_dir: 输出目录，不存在时自动创建。

    Returns:
        生成文件的路径字符串。

    Raises:
        ExportError: 未安装 ebooklib，或写盘失败。
    """
    if _epub is None:
        raise ExportError("未安装 ebooklib，无法导出 EPUB，请执行 pip install ebooklib 后重试")

    out_dir = resolve_output_dir(output_dir)
    path = out_dir / f"{safe_filename(title)}.epub"

    book = _epub.EpubBook()
    book.set_identifier(book_identifier(title, articles))
    book.set_title(title)
    book.set_language("zh-CN")
    book.add_author(AUTHOR_PLACEHOLDER)

    # —— 封面：图片项（properties="cover-image"）+ 封面页
    book.set_cover(COVER_IMAGE_NAME, build_cover_svg(title, AUTHOR_PLACEHOLDER, len(articles)), create_page=False)
    cover_page = _epub.EpubHtml(uid="cover", file_name=COVER_PAGE_NAME, title="封面", lang="zh-CN")
    cover_page.content = (
        '<html><body><div class="cover">'
        f'<img alt="{html_escape(title)}" src="{COVER_IMAGE_NAME}"/>'
        f'<h1 class="cover-title">{html_escape(title)}</h1>'
        f'<p class="cover-author">{html_escape(AUTHOR_PLACEHOLDER)} 著</p>'
        f'<p class="cover-author">共 {len(articles)} 章</p>'
        "</div></body></html>"
    )
    cover_page.add_link(href=CSS_FILE_NAME, rel="stylesheet", type="text/css")
    book.add_item(cover_page)

    css = _epub.EpubItem(uid="style_default", file_name=CSS_FILE_NAME, media_type="text/css", content=BASE_CSS)
    book.add_item(css)

    image_cache: dict[str, str] = {}
    chapters: list[Any] = []
    for index, article in enumerate(articles):
        chapters.append(_make_chapter(article, index, book, image_cache, out_dir))
    if not chapters:  # 空书也要产出合法 EPUB
        placeholder = _epub.EpubHtml(title="暂无内容", file_name="chapter_0.xhtml", lang="zh-CN", uid="chapter_0")
        placeholder.content = (
            '<html><body><h1 class="chapter-title">暂无内容</h1>'
            "<p>请先下载章节内容，再重新导出。</p></body></html>"
        )
        placeholder.add_link(href=CSS_FILE_NAME, rel="stylesheet", type="text/css")
        book.add_item(placeholder)
        chapters.append(placeholder)

    # —— TOC 两级：正文 / 附录（番外、作者说）
    if articles:
        # chapters 与 articles 严格 1:1（上方逐项构建），strict=True 显式化该不变量
        normal = [ch for ch, art in zip(chapters, articles, strict=True) if not is_appendix(art)]
        appendix = [ch for ch, art in zip(chapters, articles, strict=True) if is_appendix(art)]
    else:
        normal, appendix = chapters, []
    toc: list[Any] = []
    if normal:
        toc.append((_epub.Section("正文", href=normal[0].file_name), normal))
    if appendix:
        toc.append((_epub.Section("附录", href=appendix[0].file_name), appendix))
    book.toc = toc
    # EPUB2 guide 参考项：方便老阅读器定位封面页
    book.guide = [{"type": "cover", "title": "封面", "href": COVER_PAGE_NAME}]

    book.add_item(_epub.EpubNcx())
    book.add_item(_epub.EpubNav())
    book.spine = ["cover", "nav", *chapters]  # 阅读顺序保持原始章节顺序

    try:
        _epub.write_epub(str(path), book, {})
    except Exception as exc:  # noqa: BLE001 - 统一包装为中文可操作错误
        raise ExportError(f"EPUB 写入失败：{path}（原因：{exc}），请检查输出目录权限，或改用 txt/md 格式") from exc
    # R1 审查 M5 深挖：目标撞目录时 ebooklib 不把 OSError 抛出，只发 UserWarning
    # （其源码自注"未来版本将默认抛异常"）——不加事后校验就会出现
    # export_book 承诺 ExportError 却"静默成功、无产物"的契约违背。
    if not path.is_file() or path.stat().st_size == 0:
        raise ExportError(
            f"EPUB 写入失败：{path} 未能生成（同名路径是目录，或磁盘空间/权限不足）。"
            "若同名路径是目录请先删除，或检查输出目录后重试；仍失败可改用 txt/md 格式"
        )
    return str(path)
