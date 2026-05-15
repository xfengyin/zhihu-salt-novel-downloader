"""导出器测试"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from zhihu_downloader.exporters.base_exporter import BaseExporter
from zhihu_downloader.exporters.txt_exporter import TxtExporter
from zhihu_downloader.exporters.md_exporter import MarkdownExporter
from zhihu_downloader.exporters.epub_exporter import EpubExporter


class TestBaseExporter:
    """基础导出器测试"""

    def test_sanitize_filename(self) -> None:
        """测试文件名清理"""
        assert BaseExporter.sanitize_filename("normal.txt") == "normal.txt"
        assert BaseExporter.sanitize_filename("file<name>.txt") == "file_name_.txt"
        assert BaseExporter.sanitize_filename("  spaces  ") == "spaces"
        assert BaseExporter.sanitize_filename("<>:\"/\\|?*") == "_________"
        assert BaseExporter.sanitize_filename("") == "untitled"

    def test_group_chapters(self) -> None:
        """测试章节分组"""
        exporter = TxtExporter(Path("./output"))
        chapters = [
            {"title": "第1章", "type": "normal"},
            {"title": "第2章", "type": "normal"},
            {"title": "番外1", "type": "extra"},
            {"title": "作者说", "type": "author_note"},
        ]
        grouped = exporter.group_chapters(chapters)
        assert len(grouped["normal"]) == 2
        assert len(grouped["extra"]) == 1
        assert len(grouped["author_note"]) == 1

    def test_build_toc(self) -> None:
        """测试目录构建"""
        exporter = TxtExporter(Path("./output"))
        chapters = [
            {"title": "第1章", "type": "normal"},
            {"title": "番外1", "type": "extra"},
            {"title": "作者说", "type": "author_note"},
        ]
        toc = exporter.build_toc(chapters)
        assert "第1章" in toc
        assert "【番外】番外1" in toc
        assert "【作者说】作者说" in toc


class TestTxtExporter:
    """TXT导出器测试"""

    @pytest.fixture
    def temp_output_dir(self, tmp_path: Path) -> Path:
        """临时输出目录"""
        return tmp_path / "txt_output"

    @pytest.fixture
    def exporter(self, temp_output_dir: Path) -> TxtExporter:
        return TxtExporter(temp_output_dir)

    def test_export(self, exporter: TxtExporter) -> None:
        """测试导出"""
        article_info = {
            "title": "测试小说",
            "author": "测试作者",
            "chapters": [
                {"title": "第1章", "content": "第一章内容", "type": "normal"},
            ],
        }
        output_path = exporter.export(article_info)
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "测试小说" in content
        assert "测试作者" in content
        assert "第1章" in content


class TestMarkdownExporter:
    """Markdown导出器测试"""

    @pytest.fixture
    def temp_output_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "md_output"

    @pytest.fixture
    def exporter(self, temp_output_dir: Path) -> MarkdownExporter:
        return MarkdownExporter(temp_output_dir)

    def test_export(self, exporter: MarkdownExporter) -> None:
        """测试导出"""
        article_info = {
            "title": "测试小说",
            "author": "测试作者",
            "chapters": [
                {"title": "第1章", "content": "第一章内容", "type": "normal"},
            ],
        }
        output_path = exporter.export(article_info)
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "# 测试小说" in content
        assert "> 作者：测试作者" in content
        assert "## 第1章" in content


class TestEpubExporter:
    """EPUB导出器测试"""

    @pytest.fixture
    def temp_output_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "epub_output"

    @pytest.fixture
    def exporter(self, temp_output_dir: Path) -> EpubExporter:
        return EpubExporter(temp_output_dir)

    @pytest.mark.skip(reason="ebooklib 0.18+ has breaking changes with EpubNav")
    def test_export(self, exporter: EpubExporter) -> None:
        """测试导出"""
        article_info = {
            "title": "测试小说",
            "author": "测试作者",
            "chapters": [
                {"title": "第1章", "content": "第一章内容", "type": "normal"},
            ],
        }
        output_path = exporter.export(article_info)
        assert output_path.exists()
        assert output_path.suffix == ".epub"
