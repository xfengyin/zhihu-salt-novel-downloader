"""Service 层测试 - DownloadService / ShelfService / ProgressEvent

通过 mock AsyncDownloader 与 ShelfManager，验证业务编排逻辑，
不依赖真实网络与文件系统。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zhihu_downloader.parsers.article_parser import ArticleInfo, Chapter
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.events import ProgressEvent
from zhihu_downloader.services.shelf_service import ShelfService
from zhihu_downloader.shelf.shelf_manager import ShelfManager
from zhihu_downloader.utils.config import Config

# ---------------------------------------------------------------------------
# ProgressEvent 测试
# ---------------------------------------------------------------------------


class TestProgressEvent:
    """进度事件工厂方法测试"""

    def test_info_factory(self) -> None:
        e = ProgressEvent.info("开始", book_title="书名")
        assert e.type == "info"
        assert e.message == "开始"
        assert e.book_title == "书名"

    def test_progress_factory(self) -> None:
        e = ProgressEvent.progress("完成", total=10, downloaded=3, current="ch3")
        assert e.type == "progress"
        assert e.total == 10
        assert e.downloaded == 3
        assert e.current == "ch3"

    def test_complete_factory(self) -> None:
        e = ProgressEvent.complete("done", output_files=["a.md"])
        assert e.type == "complete"
        assert e.output_files == ["a.md"]

    def test_error_factory(self) -> None:
        e = ProgressEvent.error("失败")
        assert e.type == "error"
        assert e.message == "失败"

    def test_export_factory(self) -> None:
        e = ProgressEvent.export("导出中")
        assert e.type == "export"


# ---------------------------------------------------------------------------
# DownloadService 测试
# ---------------------------------------------------------------------------


def _make_article_info() -> ArticleInfo:
    """构造测试用文章信息"""
    return ArticleInfo(
        title="测试书",
        author="测试作者",
        chapters=[
            Chapter(id="c1", title="第1章", url="https://www.zhihu.com/c1", order=1),
            Chapter(id="c2", title="第2章", url="https://www.zhihu.com/c2", order=2),
        ],
    )


@pytest.fixture
def mock_downloader() -> Any:
    """mock AsyncDownloader，fetch 返回固定 HTML"""
    downloader = AsyncMock()
    # 第一次 fetch 返回目录页 HTML，后续返回章节正文
    downloader.fetch = AsyncMock(side_effect=["<html>toc</html>", "ch1 content", "ch2 content"])
    downloader.close = AsyncMock()
    return downloader


@pytest.fixture
def tmp_shelf(tmp_path: Path) -> ShelfManager:
    """临时书架管理器，隔离测试"""
    return ShelfManager(shelf_file=str(tmp_path / "shelf.json"))


@pytest.fixture
def service(tmp_shelf: ShelfManager) -> DownloadService:
    """DownloadService 实例，使用临时书架"""
    return DownloadService(config=Config(), shelf=tmp_shelf)


class TestDownloadService:
    """下载服务编排测试"""

    @pytest.mark.asyncio
    async def test_download_list_only(
        self,
        service: DownloadService,
        mock_downloader: Any,
        tmp_path: Path,
    ) -> None:
        """list_only 模式应产出章节列表事件，不下载正文"""
        with patch.object(service, "_parser") as mock_parser, \
             patch("zhihu_downloader.services.download_service.AsyncDownloader", return_value=mock_downloader):
            mock_parser.parse_article_info.return_value = _make_article_info()
            mock_parser.parse_chapter_content.return_value = ""

            events = []
            async for e in service.download(
                ["https://www.zhihu.com/x"],
                output_dir=str(tmp_path),
                list_only=True,
            ):
                events.append(e)

        # 至少有 info 事件 + 2 个章节 progress 事件
        types = [e.type for e in events]
        assert "info" in types
        assert types.count("progress") == 2

    @pytest.mark.asyncio
    async def test_download_full_flow(
        self,
        service: DownloadService,
        mock_downloader: Any,
        tmp_path: Path,
    ) -> None:
        """完整下载流程应产出 complete 事件并写入书架"""
        with patch.object(service, "_parser") as mock_parser, \
             patch("zhihu_downloader.services.download_service.AsyncDownloader", return_value=mock_downloader), \
             patch("zhihu_downloader.services.download_service.TxtExporter") as mock_exporter_cls:
            article_info = _make_article_info()
            mock_parser.parse_article_info.return_value = article_info
            mock_parser.parse_chapter_content.return_value = "正文内容"

            mock_exporter = MagicMock()
            mock_exporter.export.return_value = tmp_path / "测试书.txt"
            mock_exporter_cls.return_value = mock_exporter

            events = []
            async for e in service.download(
                ["https://www.zhihu.com/x"],
                output_dir=str(tmp_path),
                export_format="txt",
            ):
                events.append(e)

        # 应有 complete 事件
        complete_events = [e for e in events if e.type == "complete"]
        assert len(complete_events) == 1
        assert complete_events[0].book_title == "测试书"

        # 书架应记录该书
        book = service._shelf.get_book("https://www.zhihu.com/x")
        assert book is not None
        assert book["title"] == "测试书"

    @pytest.mark.asyncio
    async def test_download_error_handling(
        self,
        service: DownloadService,
        tmp_path: Path,
    ) -> None:
        """fetch 异常应产出 error 事件而非崩溃"""
        mock_downloader = AsyncMock()
        mock_downloader.fetch = AsyncMock(side_effect=Exception("网络错误"))
        mock_downloader.close = AsyncMock()

        with patch("zhihu_downloader.services.download_service.AsyncDownloader", return_value=mock_downloader):
            events = []
            async for e in service.download(
                ["https://www.zhihu.com/x"],
                output_dir=str(tmp_path),
            ):
                events.append(e)

        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) >= 1
        assert "网络错误" in error_events[0].message

    @pytest.mark.asyncio
    async def test_download_resume(
        self,
        service: DownloadService,
        mock_downloader: Any,
        tmp_path: Path,
    ) -> None:
        """resume 模式应跳过已下载章节"""
        with patch.object(service, "_parser") as mock_parser, \
             patch("zhihu_downloader.services.download_service.AsyncDownloader", return_value=mock_downloader), \
             patch("zhihu_downloader.services.download_service.TxtExporter") as mock_exporter_cls:
            article_info = _make_article_info()
            mock_parser.parse_article_info.return_value = article_info
            mock_parser.parse_chapter_content.return_value = "正文"

            mock_exporter = MagicMock()
            mock_exporter.export.return_value = tmp_path / "x.txt"
            mock_exporter_cls.return_value = mock_exporter

            # 预置 checkpoint：c1 已下载
            from zhihu_downloader.utils.checkpoint import CheckpointManager
            ckpt = CheckpointManager(str(tmp_path), article_info.title)
            ckpt.save_checkpoint({"c1"})

            events = []
            async for e in service.download(
                ["https://www.zhihu.com/x"],
                output_dir=str(tmp_path),
                export_format="txt",
                resume=True,
            ):
                events.append(e)

        # 应有断点续传 info 事件
        resume_events = [e for e in events if "断点续传" in e.message]
        assert len(resume_events) == 1


# ---------------------------------------------------------------------------
# ShelfService 测试
# ---------------------------------------------------------------------------


class TestShelfService:
    """书架服务测试"""

    def test_add_and_list(self, tmp_shelf: ShelfManager) -> None:
        """添加书籍后应能列出"""
        svc = ShelfService(shelf=tmp_shelf)
        result = svc.add_book("https://www.zhihu.com/a", {"title": "书A"})
        assert result["success"] is True

        books = svc.list_books()
        assert len(books) == 1
        assert books[0]["title"] == "书A"

    def test_remove_book(self, tmp_shelf: ShelfManager) -> None:
        """移除书籍后列表应为空"""
        svc = ShelfService(shelf=tmp_shelf)
        svc.add_book("https://www.zhihu.com/a", {"title": "书A"})
        result = svc.remove_book("书A")
        assert result["success"] is True
        assert svc.list_books() == []

    def test_get_statistics(self, tmp_shelf: ShelfManager) -> None:
        """统计信息应正确反映完成状态"""
        svc = ShelfService(shelf=tmp_shelf)
        svc.add_book("https://www.zhihu.com/a", {"title": "A", "completed": True})
        svc.add_book("https://www.zhihu.com/b", {"title": "B"})

        stats = svc.get_statistics()
        assert stats["total"] == 2
        assert stats["completed"] == 1
        assert stats["in_progress"] == 1

    def test_clean_cache(self, tmp_shelf: ShelfManager) -> None:
        """清空后书架应为空"""
        svc = ShelfService(shelf=tmp_shelf)
        svc.add_book("https://www.zhihu.com/a")
        result = svc.clean_cache()
        assert result["success"] is True
        assert svc.list_books() == []

    def test_mark_completed(self, tmp_shelf: ShelfManager) -> None:
        """标记完成后统计应更新"""
        svc = ShelfService(shelf=tmp_shelf)
        svc.add_book("https://www.zhihu.com/a")
        svc.mark_completed("https://www.zhihu.com/a")
        stats = svc.get_statistics()
        assert stats["completed"] == 1
