"""导出层共享工具（规格书 §2.12）。

`safe_filename` 移植自 v4 `simple/zhihu_downloader/exporters.py`，行为保持一致；
`resolve_output_dir` 负责按需创建输出目录。此外本模块提供三个导出器共用的
小工具：EPUB 稳定标识、章节类型判定与展示标题、HTML 转义。

本模块只依赖标准库与 types.py，不引入任何第三方运行时依赖。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..errors import ExportError
from ..types import Article

__all__ = [
    "APPENDIX_TYPES",
    "AUTHOR_PLACEHOLDER",
    "TYPE_MARKERS",
    "TYPE_PREFIXES",
    "book_identifier",
    "chapter_display_title",
    "html_escape",
    "is_appendix",
    "resolve_output_dir",
    "safe_filename",
]

#: 归入 EPUB「附录」节点的章节类型（parse/classifier.py 产出的 extra / author_note）。
APPENDIX_TYPES: tuple[str, ...] = ("extra", "author_note")

#: 章节类型对应的中文标题前缀，txt/md/epub 三种格式共用，保证展示一致。
TYPE_PREFIXES: dict[str, str] = {"extra": "【番外】", "author_note": "【作者说】"}

#: 前缀里的关键词；标题本身已含该词时不再重复加前缀（避免「【番外】番外 后记」）。
TYPE_MARKERS: dict[str, str] = {"extra": "番外", "author_note": "作者说"}

#: 盐选页面不提供稳定作者字段时使用的占位作者名。
AUTHOR_PLACEHOLDER = "佚名"

#: 名称全部由非法字符组成时的兜底文件名（与 v4 行为一致）。
FALLBACK_NAME = "zhihu"

_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\r\n\t]')
_WHITESPACE_RE = re.compile(r"\s+")

#: NTFS 保留设备名（不区分大小写，与扩展名无关）：主平台是 Windows，
#: 书名恰为这些词时直接写 CON.epub 会抛 OSError，统一加下划线前缀规避。
_RESERVED_WIN32 = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_filename(name: str, max_len: int = 80) -> str:
    """把任意标题变成跨平台安全的文件名片段（不含扩展名）。

    规则（移植 v4）：
      1. `\\ / : * ? " < > |` 以及制表/换行符替换为下划线；
      2. 连续空白折叠为单个空格，去掉首尾空白与结尾英文句点（Windows 禁忌）；
      3. 结果只剩分隔符或为空时回退为 `"zhihu"`；
      4. 截断到 `max_len`，并再次去掉结尾空白/句点，避免截出非法名。

    Args:
        name: 原始名称（通常是书名或章节标题）。
        max_len: 允许的最大长度，默认 80。

    Returns:
        非空的安全文件名字符串。
    """
    cleaned = _ILLEGAL_RE.sub("_", name or "")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip().strip(".")
    if not cleaned or not cleaned.strip("_ "):
        cleaned = FALLBACK_NAME
    cleaned = cleaned[:max_len].rstrip(".").rstrip(" ")
    # 极端情况：截断后什么都不剩（例如 max_len=0），仍回退兜底名。
    cleaned = cleaned or FALLBACK_NAME
    # 截断也可能截出保留名（"CON 1984" → "CON"），故守卫放在最后一步。
    if cleaned.split(".", 1)[0].upper() in _RESERVED_WIN32:
        cleaned = "_" + cleaned
    return cleaned


def resolve_output_dir(output_dir: str | Path) -> Path:
    """解析输出目录并按需创建（含多级目录），返回目录 Path。

    R1 审查 M5：output_dir 指向已存在的普通文件时，mkdir 抛 FileExistsError；
    export_book 的契约是失败一律 ExportError（CLI/server 按 SaltError 渲染
    中文提示），裸 OSError 会直通成 traceback / HTTP 500。此处统一包装。

    Args:
        output_dir: 目标目录，字符串或 Path；已存在时不报错。

    Returns:
        可直接写入的目录 Path（保持调用方给定的相对/绝对形态）。

    Raises:
        ExportError: 目录不可创建/不可写（中文消息，含下一步建议）。
    """
    path = Path(output_dir).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ExportError(
            f"无法创建输出目录：{path}（{type(e).__name__}: {e}）。"
            "若该路径已存在同名文件请先删除或改名，或换一个输出目录重试："
            "zhihu-downloader download <url> --output ./books"
        ) from e
    if not path.is_dir():  # pragma: no cover - mkdir 成功后理论不可能，防御兜底
        raise ExportError(f"输出路径不是目录：{path}。请换一个输出目录重试（--output ./books）")
    return path


def book_identifier(title: str, articles: list[Article]) -> str:
    """EPUB 的稳定唯一标识：`sha1(f"{title}|{首章 url}")` 十六进制。

    刻意不使用 Python 内置 `hash()`（其结果随进程哈希随机化变化），保证同一本书
    多次导出的 identifier 完全一致，便于阅读器识别并合并同一本书。

    Args:
        title: 书名。
        articles: 有序章节列表；为空时以空 URL 参与计算。

    Returns:
        40 位十六进制字符串。
    """
    first_url = articles[0].url if articles else ""
    return hashlib.sha1(f"{title}|{first_url}".encode()).hexdigest()


def is_appendix(article: Article) -> bool:
    """该章节是否应归入 EPUB「附录」节点（番外 / 作者说）。"""
    return article.chapter_type in APPENDIX_TYPES


def chapter_display_title(article: Article) -> str:
    """章节展示标题：番外/作者说加中文前缀，正文章原样返回。

    标题里已经写了「番外」「作者说」时不再重复加前缀，避免出现
    「【番外】番外 后记」这种啰嗦标题。
    """
    prefix = TYPE_PREFIXES.get(article.chapter_type, "")
    marker = TYPE_MARKERS.get(article.chapter_type, "")
    if prefix and marker and marker in article.title:
        return article.title
    return f"{prefix}{article.title}"


def html_escape(text: str) -> str:
    """最小 HTML/XML 文本转义（含双引号，可安全用于属性值）。"""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
