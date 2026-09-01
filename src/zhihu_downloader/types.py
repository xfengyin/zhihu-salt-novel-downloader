"""跨模块共享的数据契约（全部为可 JSON 序列化的 dataclass）。

⚠️ 本文件是团队并行开发的对齐锚点：任何签名/字段变更必须先改这里。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ----------------------------------------------------------------------
# 解析层产物
# ----------------------------------------------------------------------

@dataclass
class Block:
    """正文内容块。kind 取值：h2 | h3 | p | li | quote | img。

    - 文本块使用 text；img 块使用 src/alt。
    """

    kind: str
    text: str = ""
    src: str = ""
    alt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Block:
        return cls(kind=d.get("kind", "p"), text=d.get("text", ""),
                   src=d.get("src", ""), alt=d.get("alt", ""))


@dataclass
class Article:
    """单章解析结果。"""

    title: str
    url: str
    blocks: list[Block] = field(default_factory=list)
    chapter_type: str = "normal"  # normal | extra | author_note（来自分类器）

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "chapter_type": self.chapter_type,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Article:
        return cls(
            title=d["title"],
            url=d.get("url", ""),
            chapter_type=d.get("chapter_type", "normal"),
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
        )

    def plain_text(self) -> str:
        """拍平为纯文本（txt 导出与测试断言用）。"""
        parts: list[str] = []
        for b in self.blocks:
            if b.kind == "img":
                continue
            if b.kind in ("h2", "h3"):
                parts.append(b.text)
            elif b.kind == "li":
                parts.append(f"- {b.text}")
            elif b.kind == "quote":
                parts.append(f"> {b.text}")
            else:
                parts.append(b.text)
        return "\n\n".join(p for p in parts if p.strip())


# ----------------------------------------------------------------------
# 下载编排产物
# ----------------------------------------------------------------------

@dataclass
class ChapterRef:
    """目录中的一个章节引用。"""

    url: str
    title: str
    index: int
    type: str = "normal"  # 分类器结果


@dataclass
class BookMeta:
    """一本书（专栏）的元信息。"""

    title: str
    url: str
    chapters: list[ChapterRef] = field(default_factory=list)


@dataclass
class ProgressEvent:
    """进度协议：CLI 进度条与 Web SSE 共用。

    kind 取值：
      toc      —— 目录解析完成（total 首次可知）
      chapter  —— 完成一章（current += 1，title 为当前章）
      retry    —— 某章请求失败进入重试
      export   —— 开始导出（message 含格式）
      done     —— 全部完成（files 见 result）
      error    —— 终止性错误（message 为中文可读原因）
    """

    kind: str
    current: int = 0
    total: int = 0
    title: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BookResult:
    """一次下载任务的最终结果。"""

    title: str
    url: str
    chapters: int = 0
    files: list[str] = field(default_factory=list)
    skipped_existing: int = 0  # 续传/追更时跳过的章节数


# ----------------------------------------------------------------------
# 书架
# ----------------------------------------------------------------------

@dataclass
class ShelfBook:
    """书架条目（shelf.json 持久化单元）。"""

    id: str            # sha1(column_url)[:12]
    title: str
    url: str           # 专栏 market URL
    fmt: str           # 上次导出格式
    files: list[str] = field(default_factory=list)
    chapter_urls: list[str] = field(default_factory=list)  # 已下载章节 URL（有序）
    downloaded_at: str = ""  # ISO 时间
    updated_at: str = ""     # ISO 时间

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ShelfBook:
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            url=d.get("url", ""),
            fmt=d.get("fmt", "md"),
            files=list(d.get("files", [])),
            chapter_urls=list(d.get("chapter_urls", [])),
            downloaded_at=d.get("downloaded_at", ""),
            updated_at=d.get("updated_at", ""),
        )
