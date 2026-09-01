"""Markdown 导出器：保留解析层结构（规格书 §2.12）。

映射规则（与 parse/parser.py 的 Block.kind 一一对应）：

    h2    -> `## 文本`
    h3    -> `### 文本`
    li    -> `- 文本`（连续 li 合并为同一无序列表）
    quote -> `> 文本`
    img   -> `![alt](src)`
    p     -> 原文

每章以 `# 章节标题` 开头，其后紧跟 `> 来源：url`，便于回溯原始页面。

安全（R2 审计 #4）：block.text / alt / src / 章节标题 / 来源 URL 全部来自远端页面，
知乎实体编码的 HTML 经 get_text() 解码后是字面量 <script>…</script>，Typora /
VS Code 等预览器会把 Markdown 里的裸 HTML 直接执行。因此**所有文本出口**统一过
`base.html_escape`（`< > & "`），并给每个反引号前置反斜杠，防止远端内容借代码
围栏/行内码逃逸结构。书名不再写进首行 HTML 注释（含 `-->` 的远端书名可逃逸注释）。
txt 导出是纯文本，无需此转义。
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ExportError
from ..types import Article, Block
from .base import chapter_display_title, html_escape, resolve_output_dir, safe_filename

__all__ = ["export", "render_block", "render_blocks", "render_markdown"]


def _md_text(text: str) -> str:
    """把远端来源的任意文本净化为 Markdown 字面量。

    1. `html_escape`：`< > & "` 实体化，预览器不再执行远端 HTML；
    2. 每个反引号前加一个反斜杠：远端内容无法拼出三反引号围栏或行内码逃逸结构。

    Args:
        text: 原始文本（block.text / alt / src / 标题 / URL）。

    Returns:
        净化后的文本；普通中英文零损耗，实体在预览器中还原为原字符。
    """
    return html_escape(text).replace("`", "\\`")


def render_block(block: Block) -> str:
    """把单个 Block 渲染为一行/一段 Markdown（文本全部净化）。

    Args:
        block: 解析层内容块。

    Returns:
        Markdown 片段；无内容的块返回空字符串（调用方负责丢弃）。
    """
    kind = block.kind
    if kind == "h2":
        return f"## {_md_text(block.text.strip())}"
    if kind == "h3":
        return f"### {_md_text(block.text.strip())}"
    if kind == "li":
        return f"- {_md_text(block.text.strip())}"
    if kind == "quote":
        return f"> {_md_text(block.text.strip())}"
    if kind == "img":
        alt = _md_text(block.alt.strip())
        src = _md_text(block.src.strip())
        if not src:
            # 没有 src 的图片块没有意义，降级为 alt 提示文本。
            return f"*（图片缺失：{alt}）*" if alt else ""
        return f"![{alt}]({src})"
    return _md_text(block.text.strip())


def render_blocks(blocks: list[Block]) -> list[str]:
    """把 Block 列表渲染为 Markdown 片段列表。

    连续的 li 合并进同一个片段，保证渲染出的列表紧凑而非「松散列表」。

    Args:
        blocks: 章节内容块列表。

    Returns:
        非空 Markdown 片段列表（调用方用空行拼接）。
    """
    parts: list[str] = []
    for block in blocks:
        piece = render_block(block)
        if not piece.strip():
            continue
        if block.kind == "li" and parts and parts[-1].startswith("- "):
            parts[-1] = parts[-1] + "\n" + piece
        else:
            parts.append(piece)
    return parts


def render_markdown(title: str, articles: list[Article]) -> str:
    """生成整本 Markdown 文本（不落盘，便于单测直接断言结构）。

    书名不写进文件内容（R2 审计 #4：首行 HTML 注释可被含 `-->` 的远端书名
    逃逸，在预览器里注入 HTML）；书名信息保留在导出文件名中。每个一级标题
    `#` 对应一章，与规格书「每章 # 标题 + > 来源：url」严格一致。

    Args:
        title: 书名（保留签名兼容；内容不再落首行注释）。
        articles: 有序章节列表。

    Returns:
        完整 Markdown 文本（以换行结尾）。
    """
    del title  # 安全净化：书名不进正文（见 docstring），文件名仍由 export() 决定。
    lines: list[str] = []
    for article in articles:
        lines.append(f"# {_md_text(chapter_display_title(article))}")
        lines.append("")
        if article.url:
            lines.append(f"> 来源：{_md_text(article.url)}")
            lines.append("")
        parts = render_blocks(article.blocks)
        lines.append("\n\n".join(parts) if parts else "（本章无正文）")
        lines.append("")
    if not lines:
        return "（本章无正文）\n"
    return "\n".join(lines) + "\n"


def export(title: str, articles: list[Article], output_dir: str | Path) -> str:
    """导出为单个 `.md` 文件。

    Args:
        title: 书名（同时决定文件名）。
        articles: 有序章节列表。
        output_dir: 输出目录，不存在时自动创建。

    Returns:
        生成文件的路径字符串。
    """
    out_dir = resolve_output_dir(output_dir)
    path = out_dir / f"{safe_filename(title)}.md"
    try:  # R1 审查 M5：同名目录/权限/磁盘满等 OSError 不得裸穿
        path.write_text(render_markdown(title, articles), encoding="utf-8")
    except OSError as e:
        raise ExportError(
            f"写入 Markdown 失败：{path}（{type(e).__name__}: {e}）。"
            "若同名路径是目录请先删除，或检查磁盘空间/输出目录权限后重试"
        ) from e
    return str(path)
