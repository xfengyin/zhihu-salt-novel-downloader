"""TXT 导出器：把结构化 Block 拍平为纯文本（规格书 §2.12）。

拍平逻辑复用 types.py 里 `Article.plain_text()`（团队共享契约），本模块只负责
分章排版与落盘：书名抬头 + 每章「标题 / 空行 / 正文 / 分隔线」。
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ExportError
from ..types import Article
from .base import chapter_display_title, resolve_output_dir, safe_filename

#: 章间分隔线宽度（沿用 v4 的 40 个短横线）。
_SEPARATOR = "-" * 40


def render_text(title: str, articles: list[Article]) -> str:
    """生成 TXT 全文内容（不落盘，便于单测直接断言结构）。

    Args:
        title: 书名，用于文件抬头。
        articles: 有序章节列表。

    Returns:
        完整 TXT 文本（以换行结尾）。
    """
    lines: list[str] = [title, _SEPARATOR, ""]
    for article in articles:
        lines.append(chapter_display_title(article))
        lines.append("")
        body = article.plain_text()
        lines.append(body if body.strip() else "（本章无正文）")
        lines.append("")
        lines.append(_SEPARATOR)
        lines.append("")
    return "\n".join(lines)


def export(title: str, articles: list[Article], output_dir: str | Path) -> str:
    """导出为单个 `.txt` 文件。

    Args:
        title: 书名（同时决定文件名）。
        articles: 有序章节列表。
        output_dir: 输出目录，不存在时自动创建。

    Returns:
        生成文件的绝对/相对路径字符串（与传入 output_dir 形态一致）。
    """
    out_dir = resolve_output_dir(output_dir)
    path = out_dir / f"{safe_filename(title)}.txt"
    try:  # R1 审查 M5：同名目录/权限/磁盘满等 OSError 不得裸穿
        path.write_text(render_text(title, articles), encoding="utf-8")
    except OSError as e:
        raise ExportError(
            f"写入 TXT 失败：{path}（{type(e).__name__}: {e}）。"
            "若同名路径是目录请先删除，或检查磁盘空间/输出目录权限后重试"
        ) from e
    return str(path)
