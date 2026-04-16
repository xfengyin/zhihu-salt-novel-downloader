"""导出器测试"""

import pytest
from pathlib import Path
import tempfile
import os

from exporters.base_exporter import BaseExporter
from exporters.txt_exporter import TxtExporter
from exporters.md_exporter import MarkdownExporter
from exporters.epub_exporter import EpubExporter


class TestTxtExporter:
    """TXT导出器测试"""
    
    @pytest.fixture
    def exporter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield TxtExporter(Path(tmpdir))
    
    def test_export(self, exporter, sample_article_info):
        """测试导出"""
        output_path = exporter.export(sample_article_info)
        
        assert output_path.exists()
        assert output_path.suffix == '.txt'
        
        content = output_path.read_text(encoding='utf-8')
        assert '测试小说' in content
        assert '测试作者' in content
        assert '第一章' in content


class TestMarkdownExporter:
    """Markdown导出器测试"""
    
    @pytest.fixture
    def exporter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield MarkdownExporter(Path(tmpdir))
    
    def test_export(self, exporter, sample_article_info):
        """测试导出"""
        output_path = exporter.export(sample_article_info)
        
        assert output_path.exists()
        assert output_path.suffix == '.md'
        
        content = output_path.read_text(encoding='utf-8')
        assert '# 测试小说' in content
        assert '**作者：**' in content
        assert '## 正文' in content


class TestEpubExporter:
    """EPUB导出器测试"""
    
    @pytest.fixture
    def exporter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield EpubExporter(Path(tmpdir))
    
    def test_export(self, exporter, sample_article_info):
        """测试导出"""
        output_path = exporter.export(sample_article_info)
        
        assert output_path.exists()
        assert output_path.suffix == '.epub'
        assert output_path.stat().st_size > 0


class TestBaseExporter:
    """基础导出器测试"""
    
    def test_sanitize_filename(self):
        """测试文件名清理"""
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = BaseExporter(Path(tmpdir))
            
            # 测试非法字符
            filename = exporter.sanitize_filename('test<file>name')
            assert '<' not in filename
            assert '>' not in filename
            
            # 测试长度限制
            long_name = 'a' * 300
            filename = exporter.sanitize_filename(long_name)
            assert len(filename) <= 200
    
    def test_group_chapters(self, sample_article_info):
        """测试章节分组"""
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = BaseExporter(Path(tmpdir))
            
            grouped = exporter.group_chapters(sample_article_info['chapters'])
            
            assert 'normal' in grouped
            assert 'extra' in grouped
            assert 'author_note' in grouped
    
    def test_format_chapter_title(self):
        """测试章节标题格式化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = BaseExporter(Path(tmpdir))
            
            # 番外
            title = exporter.format_chapter_title(
                {'title': '测试', 'type': 'extra'},
                1
            )
            assert '【番外】' in title
            
            # 作者说
            title = exporter.format_chapter_title(
                {'title': '测试', 'type': 'author_note'},
                1
            )
            assert '【作者说】' in title
