"""Pydantic 契约定义 - API 层入参/出参 schema

与前端 web/src/types/index.ts 严格对齐，作为前后端接口契约的唯一事实来源。
所有模型启用 pydantic v2 严格校验，确保边界数据安全。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class ExportFormat(str, Enum):
    """导出格式枚举"""

    TXT = "txt"
    MD = "md"
    EPUB = "epub"
    MOBI = "mobi"
    ALL = "all"


class DownloadStatus(str, Enum):
    """下载状态枚举 - 与前端 DownloadProgress.status 对齐"""

    IDLE = "idle"
    DOWNLOADING = "downloading"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    ERROR = "error"


class ChapterType(str, Enum):
    """章节类型枚举"""

    NORMAL = "normal"
    EXTRA = "extra"
    AUTHOR_NOTE = "author_note"
    UNKNOWN = "unknown"


class ProgressEventType(str, Enum):
    """进度事件类型 - SSE 推送的事件分类"""

    INFO = "info"          # 普通信息（如开始处理某本书）
    PROGRESS = "progress"  # 章节级进度更新
    EXPORT = "export"      # 导出阶段事件
    COMPLETE = "complete"  # 全部完成
    ERROR = "error"        # 错误


# ---------------------------------------------------------------------------
# 章节与文章
# ---------------------------------------------------------------------------


class ChapterSchema(BaseModel):
    """章节 schema - 与前端 Chapter 对齐"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="章节ID")
    title: str = Field(description="章节标题")
    url: str = Field(description="章节URL")
    order: int = Field(ge=0, description="章节序号")
    content: str = Field(default="", description="章节正文")
    type: ChapterType = Field(default=ChapterType.NORMAL, description="章节类型")


class ArticleInfoSchema(BaseModel):
    """文章信息 schema - 与前端 ArticleInfo 对齐"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description="文章标题")
    author: str = Field(description="作者")
    chapters: list[ChapterSchema] = Field(default_factory=list, description="章节列表")
    chapter_count: int = Field(default=0, ge=0, description="章节数量")
    description: str = Field(default="", description="文章描述")
    cover_url: str = Field(default="", description="封面图URL")


# ---------------------------------------------------------------------------
# 下载请求与进度
# ---------------------------------------------------------------------------


class DownloadRequest(BaseModel):
    """下载请求 schema - 与前端 DownloadConfig 对齐"""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(default="", description="知乎盐选小说URL")
    batch_urls: list[str] = Field(default_factory=list, description="批量下载URL列表")
    cookie_file: str | None = Field(default=None, description="Cookie JSON文件路径")
    auto_cookie: bool = Field(default=False, description="自动从浏览器读取Cookie")
    token: str | None = Field(default=None, description="z_c0 token值")
    output_dir: str = Field(default="./output", description="输出目录")
    export_format: ExportFormat = Field(default=ExportFormat.MD, description="导出格式")
    list_only: bool = Field(default=False, description="仅列出章节不下载")
    max_concurrent: int = Field(default=3, ge=1, le=20, description="最大并发数")
    rate_limit: float = Field(default=2.0, gt=0, le=50, description="每秒请求数")
    clean_content: bool = Field(default=True, description="是否清洗内容")
    resume: bool = Field(default=False, description="是否启用断点续传")
    update_check: bool = Field(default=False, description="是否检查章节更新")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """URL 基础校验：非空时必须是 http(s) 链接"""
        if v and not (v.startswith("http://") or v.startswith("https://")):
            msg = "URL 必须以 http:// 或 https:// 开头"
            raise ValueError(msg)
        return v

    @field_validator("batch_urls")
    @classmethod
    def validate_batch_urls(cls, v: list[str]) -> list[str]:
        """批量 URL 校验：过滤空行与注释行"""
        return [u.strip() for u in v if u.strip() and not u.strip().startswith("#")]


class DownloadProgressSchema(BaseModel):
    """下载进度 schema - 与前端 DownloadProgress 对齐"""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(default=0, ge=0, description="总章节数")
    downloaded: int = Field(default=0, ge=0, description="已下载数")
    current: str = Field(default="", description="当前正在下载的章节标题")
    status: DownloadStatus = Field(default=DownloadStatus.IDLE, description="下载状态")
    error: str = Field(default="", description="错误信息")


# ---------------------------------------------------------------------------
# SSE 进度事件
# ---------------------------------------------------------------------------


class ProgressEventSchema(BaseModel):
    """SSE 进度事件 schema - 单次推送的事件载荷"""

    model_config = ConfigDict(extra="forbid")

    type: ProgressEventType = Field(description="事件类型")
    message: str = Field(default="", description="人类可读消息")
    total: int = Field(default=0, ge=0, description="总章节数")
    downloaded: int = Field(default=0, ge=0, description="已下载数")
    current: str = Field(default="", description="当前章节标题")
    book_title: str = Field(default="", description="当前书名")
    output_files: list[str] = Field(default_factory=list, description="导出文件路径列表")


# ---------------------------------------------------------------------------
# 书架
# ---------------------------------------------------------------------------


class BookSchema(BaseModel):
    """书架书籍 schema"""

    model_config = ConfigDict(extra="allow")

    url: str = Field(description="书籍URL")
    title: str = Field(default="未知标题", description="书籍标题")
    author: str = Field(default="未知作者", description="作者")
    chapter_count: int = Field(default=0, ge=0, description="章节数")
    completed: bool = Field(default=False, description="是否已完成")
    added_at: str = Field(default="", description="添加时间 ISO")
    last_update: str = Field(default="", description="最后更新时间 ISO")


class ShelfStatsSchema(BaseModel):
    """书架统计 schema"""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(default=0, ge=0, description="书籍总数")
    completed: int = Field(default=0, ge=0, description="已完成数")
    in_progress: int = Field(default=0, ge=0, description="进行中数")


class ShelfAddRequest(BaseModel):
    """书架添加请求"""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(description="书籍URL")


# ---------------------------------------------------------------------------
# 通用响应
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """通用消息响应"""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(description="消息内容")
    success: bool = Field(default=True, description="是否成功")


class ExportResultSchema(BaseModel):
    """导出结果 schema"""

    model_config = ConfigDict(extra="forbid")

    format: str = Field(description="导出格式")
    file_path: str = Field(description="输出文件绝对路径")
    file_name: str = Field(description="文件名")


class DownloadResultSchema(BaseModel):
    """单本书下载结果 schema"""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(description="书籍URL")
    title: str = Field(default="", description="书籍标题")
    author: str = Field(default="", description="作者")
    chapter_count: int = Field(default=0, ge=0, description="已下载章节数")
    exports: list[ExportResultSchema] = Field(default_factory=list, description="导出文件列表")
    success: bool = Field(default=True, description="是否成功")
    error: str = Field(default="", description="错误信息")


# ---------------------------------------------------------------------------
# 辅助转换：领域对象 -> schema
# ---------------------------------------------------------------------------


def article_info_to_schema(info_dict: dict) -> ArticleInfoSchema:
    """将 ArticleInfo.to_dict() 结果转换为 schema

    Args:
        info_dict: ArticleInfo.to_dict() 产出的字典

    Returns:
        ArticleInfoSchema 实例
    """
    chapters = [
        ChapterSchema(
            id=ch.get("id", ""),
            title=ch.get("title", ""),
            url=ch.get("url", ""),
            order=ch.get("order", 0),
            content=ch.get("content", ""),
            type=ch.get("type", "normal"),
        )
        for ch in info_dict.get("chapters", [])
    ]
    return ArticleInfoSchema(
        title=info_dict.get("title", "未知标题"),
        author=info_dict.get("author", "未知作者"),
        chapters=chapters,
        chapter_count=info_dict.get("chapter_count", len(chapters)),
        description=info_dict.get("description", ""),
        cover_url=info_dict.get("cover_url", ""),
    )


def export_path_to_result(fmt: str, path: Path) -> ExportResultSchema:
    """将导出路径转换为结果 schema"""
    return ExportResultSchema(
        format=fmt,
        file_path=str(path.absolute()),
        file_name=path.name,
    )
