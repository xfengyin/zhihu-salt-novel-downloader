"""下载服务 - 业务编排核心

从原 cli.py 抽离下载编排逻辑，封装为可复用的 async generator。
上层（API/CLI）通过消费 ProgressEvent 流获得实时进度，无需回调。

设计要点：
- 单一职责：只负责下载编排，不关心 HTTP/CLI 细节
- 依赖倒置：依赖 Config/AsyncDownloader 等抽象，可注入 mock 测试
- 可观测：关键节点产出 ProgressEvent，全链路可追踪
- 幂等：断点续传基于 checkpoint，重复执行安全
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.core.downloader import AsyncDownloader
from zhihu_downloader.exporters.epub_exporter import EpubExporter
from zhihu_downloader.exporters.md_exporter import MarkdownExporter
from zhihu_downloader.exporters.mobi_exporter import MobiExporter
from zhihu_downloader.exporters.txt_exporter import TxtExporter
from zhihu_downloader.parsers.article_parser import ArticleParser
from zhihu_downloader.parsers.chapter_classifier import ChapterClassifier
from zhihu_downloader.shelf.shelf_manager import ShelfManager
from zhihu_downloader.utils.checkpoint import CheckpointManager
from zhihu_downloader.utils.config import Config
from zhihu_downloader.utils.content_cleaner import ContentCleaner

from .events import ProgressEvent

logger = logging.getLogger(__name__)


class DownloadService:
    """下载服务 - 编排解析、下载、清洗、导出全流程

    通过 async generator 产出 ProgressEvent，上层可：
    - CLI: 打印到终端
    - API: 转为 SSE 推送给前端
    """

    def __init__(
        self,
        config: Config | None = None,
        shelf: ShelfManager | None = None,
    ) -> None:
        """
        Args:
            config: 配置管理器，为 None 时使用默认配置
            shelf: 书架管理器，为 None 时使用默认路径
        """
        self._config = config or Config()
        self._shelf = shelf or ShelfManager()
        self._parser = ArticleParser()
        self._classifier = ChapterClassifier()

    # ------------------------------------------------------------------
    # 公开能力
    # ------------------------------------------------------------------

    async def download(
        self,
        urls: list[str],
        *,
        cookie_manager: CookieManager | None = None,
        max_concurrent: int | None = None,
        rate_limit: float | None = None,
        output_dir: str | None = None,
        export_format: str = "md",
        list_only: bool = False,
        clean_content: bool | None = None,
        resume: bool = False,
        update_check: bool = False,
    ) -> AsyncIterator[ProgressEvent]:
        """批量下载多本书

        Args:
            urls: 待下载的 URL 列表
            cookie_manager: 认证管理器，None 表示匿名访问
            max_concurrent: 最大并发数，None 取配置
            rate_limit: 每秒请求数，None 取配置
            output_dir: 输出目录，None 取配置
            export_format: 导出格式 txt/md/epub/mobi/all
            list_only: 仅列出章节不下载
            clean_content: 是否清洗内容，None 取配置
            resume: 是否启用断点续传
            update_check: 是否检查章节更新

        Yields:
            ProgressEvent 进度事件流
        """
        # 解析参数，缺省回退到配置（统一使用点号 key，修复原 cli 的层级错位 bug）
        max_concurrent = max_concurrent or self._config.get("download.max_concurrent", 3)
        rate_limit = rate_limit or self._config.get("download.rate_limit", 2.0)
        output_dir = output_dir or self._config.get("output.output_dir", "./output")
        if clean_content is None:
            clean_content = self._config.get("content.clean_content", True)

        cookies = cookie_manager.get_cookies() if cookie_manager else {}

        downloader = AsyncDownloader(
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            cookies=cookies,
        )

        yield ProgressEvent.info(f"开始处理 {len(urls)} 本书")

        try:
            for idx, url in enumerate(urls, 1):
                yield ProgressEvent.info(f"[{idx}/{len(urls)}] {url}")
                async for event in self._download_single_book(
                    url=url,
                    downloader=downloader,
                    output_dir=output_dir,
                    export_format=export_format,
                    list_only=list_only,
                    clean_content=clean_content,
                    resume=resume,
                    update_check=update_check,
                ):
                    yield event
        finally:
            await downloader.close()

    async def download_single(
        self,
        url: str,
        *,
        cookie_manager: CookieManager | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ProgressEvent]:
        """下载单本书 - download 的便捷封装"""
        async for event in self.download(
            [url], cookie_manager=cookie_manager, **kwargs
        ):
            yield event

    async def update_shelf(
        self,
        cookie_manager: CookieManager | None = None,
        output_dir: str | None = None,
        export_format: str = "md",
    ) -> AsyncIterator[ProgressEvent]:
        """更新书架中所有书籍

        Args:
            cookie_manager: 认证管理器
            output_dir: 输出目录
            export_format: 导出格式

        Yields:
            ProgressEvent 进度事件流
        """
        books = self._shelf.list_books()
        if not books:
            yield ProgressEvent.info("书架为空")
            return

        yield ProgressEvent.info(f"正在更新书架中的 {len(books)} 本书")

        output_dir = output_dir or self._config.get("output.output_dir", "./output")
        cookies = cookie_manager.get_cookies() if cookie_manager else {}

        downloader = AsyncDownloader(
            max_concurrent=self._config.get("download.max_concurrent", 3),
            rate_limit=self._config.get("download.rate_limit", 2.0),
            cookies=cookies,
        )

        try:
            for book in books:
                url = book.get("url")
                if not url:
                    continue

                title = book.get("title", "未知")
                yield ProgressEvent.info(f"检查: {title}", book_title=title)

                try:
                    html = await downloader.fetch(url)
                    info = self._parser.parse_article_info(html)

                    existing_count = book.get("chapter_count", 0)
                    if info.chapter_count > existing_count:
                        new_chapters = info.chapter_count - existing_count
                        yield ProgressEvent.info(
                            f"发现 {new_chapters} 个新章节", book_title=title
                        )
                        async for event in self._download_single_book(
                            url=url,
                            downloader=downloader,
                            output_dir=output_dir,
                            export_format=export_format,
                            list_only=False,
                            clean_content=self._config.get("content.clean_content", True),
                            resume=True,
                            update_check=False,
                        ):
                            yield event
                    else:
                        yield ProgressEvent.info("已是最新", book_title=title)

                except Exception as e:
                    logger.exception("更新书架书籍失败: %s", url)
                    yield ProgressEvent.error(
                        f"检查失败: {e}", book_title=title
                    )
        finally:
            await downloader.close()

    # ------------------------------------------------------------------
    # 内部编排
    # ------------------------------------------------------------------

    async def _download_single_book(
        self,
        url: str,
        downloader: AsyncDownloader,
        output_dir: str,
        export_format: str,
        list_only: bool,
        clean_content: bool,
        resume: bool,
        update_check: bool,
    ) -> AsyncIterator[ProgressEvent]:
        """下载单本书的完整编排流程"""
        try:
            yield ProgressEvent.info(f"正在获取内容: {url}")

            html = await downloader.fetch(url)
            article_info = self._parser.parse_article_info(html)

            yield ProgressEvent.info(
                f"《{article_info.title}》 作者: {article_info.author} "
                f"章节数: {article_info.chapter_count}",
                book_title=article_info.title,
            )

            # 更新检查
            if update_check:
                existing_info = self._shelf.get_book(url)
                if existing_info:
                    existing_chapters = existing_info.get("chapter_count", 0)
                    if article_info.chapter_count > existing_chapters:
                        new_count = article_info.chapter_count - existing_chapters
                        yield ProgressEvent.info(
                            f"发现更新！新增 {new_count} 章节",
                            book_title=article_info.title,
                        )
                    else:
                        yield ProgressEvent.info(
                            "已是最新版本，无需更新",
                            book_title=article_info.title,
                        )
                        return

            # 仅列出章节
            if list_only:
                for ch in article_info.chapters:
                    yield ProgressEvent.progress(
                        message=ch.title,
                        total=article_info.chapter_count,
                        downloaded=ch.order,
                        current=ch.title,
                        book_title=article_info.title,
                    )
                return

            # 断点续传
            checkpoint_mgr = CheckpointManager(output_dir, article_info.title)
            downloaded_ids: set[str] = set()

            if resume and checkpoint_mgr.get_checkpoint_file().exists():
                downloaded_ids = checkpoint_mgr.load_checkpoint()
                yield ProgressEvent.info(
                    f"断点续传: 已下载 {len(downloaded_ids)} 章节",
                    book_title=article_info.title,
                )

            chapters_to_download = [
                ch for ch in article_info.chapters if ch.id not in downloaded_ids
            ]

            if not chapters_to_download:
                yield ProgressEvent.info(
                    "所有章节已下载完成",
                    book_title=article_info.title,
                )
            else:
                yield ProgressEvent.info(
                    f"开始下载 {len(chapters_to_download)} 个章节",
                    book_title=article_info.title,
                )

                cleaner = ContentCleaner() if clean_content else None

                for chapter in chapters_to_download:
                    try:
                        chapter_html = await downloader.fetch(chapter.url)
                        chapter_content = self._parser.parse_chapter_content(chapter_html)

                        if cleaner:
                            chapter_content = cleaner.clean(chapter_content)

                        chapter.type = self._classifier.classify(chapter.title).value
                        chapter.content = chapter_content

                        downloaded_ids.add(chapter.id)
                        if resume:
                            checkpoint_mgr.save_checkpoint(downloaded_ids)

                        yield ProgressEvent.progress(
                            message=f"完成: {chapter.title}",
                            total=len(article_info.chapters),
                            downloaded=len(downloaded_ids),
                            current=chapter.title,
                            book_title=article_info.title,
                        )

                    except Exception as e:
                        logger.exception("章节下载失败: %s", chapter.url)
                        yield ProgressEvent.error(
                            f"章节失败 {chapter.title}: {e}",
                            book_title=article_info.title,
                        )

            # 导出
            output_files = await self._export(
                article_info=article_info,
                output_dir=output_dir,
                export_format=export_format,
            )

            file_list = [str(p) for p in output_files]
            yield ProgressEvent.complete(
                message=f"完成！共 {len(downloaded_ids)} 章节",
                book_title=article_info.title,
                output_files=file_list,
            )

            # 写入书架
            self._shelf.add_book(url, article_info.to_dict())

        except Exception as e:
            logger.exception("下载失败: %s", url)
            yield ProgressEvent.error(f"下载失败: {e}")

    async def _export(
        self,
        article_info: Any,
        output_dir: str,
        export_format: str,
    ) -> list[Path]:
        """执行导出，返回输出文件路径列表

        统一接收导出器返回的 Path，修复原 cli 未接收返回值的问题。
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        exporters: dict[str, Any] = {
            "txt": TxtExporter(output_path),
            "md": MarkdownExporter(output_path),
            "epub": EpubExporter(output_path),
            "mobi": MobiExporter(output_path),
        }

        article_dict = (
            article_info.to_dict()
            if hasattr(article_info, "to_dict")
            else article_info
        )

        results: list[Path] = []

        if export_format == "all":
            for _fmt, exporter in exporters.items():
                path = exporter.export(article_dict)
                results.append(path)
        else:
            exporter = exporters.get(export_format)
            if exporter:
                path = exporter.export(article_dict)
                results.append(path)

        return results
