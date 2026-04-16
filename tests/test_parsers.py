"""解析器测试"""

import pytest

from parsers.article_parser import ArticleParser, Chapter
from parsers.chapter_classifier import ChapterClassifier, ChapterType


class TestArticleParser:
    """文章解析器测试"""
    
    @pytest.fixture
    def parser(self):
        return ArticleParser()
    
    def test_extract_title(self, parser, sample_html):
        """测试提取标题"""
        soup = parser._extract_title(__import__('bs4').BeautifulSoup(sample_html, 'lxml'))
        assert '测试文章' in soup or '测试' in soup
    
    def test_clean_text(self, parser):
        """测试文本清理"""
        text = "  测试   文本  "
        cleaned = parser._clean_text(text)
        assert cleaned == "测试 文本"
    
    def test_extract_chapter_id(self, parser):
        """测试提取章节ID"""
        # 测试answer URL
        id1 = parser._extract_chapter_id('/answer/123456')
        assert id1 == '123456'
        
        # 测试article URL
        id2 = parser._extract_chapter_id('/article/789')
        assert id2 == '789'
    
    def test_build_url(self, parser):
        """测试构建URL"""
        # 完整URL
        url1 = parser._build_url('https://www.zhihu.com/answer/123')
        assert url1 == 'https://www.zhihu.com/answer/123'
        
        # 相对路径
        url2 = parser._build_url('/answer/456')
        assert url2 == 'https://www.zhihu.com/answer/456'


class TestChapterClassifier:
    """章节分类器测试"""
    
    @pytest.fixture
    def classifier(self):
        return ChapterClassifier()
    
    def test_classify_normal(self, classifier):
        """测试正文分类"""
        # 普通章节
        result = classifier.classify('第一章：开始')
        assert result == ChapterType.NORMAL
        
        result = classifier.classify('第10章 测试章节')
        assert result == ChapterType.NORMAL
    
    def test_classify_extra(self, classifier):
        """测试番外分类"""
        result = classifier.classify('番外篇：前传')
        assert result == ChapterType.EXTRA
        
        result = classifier.classify('外传：最终章')
        assert result == ChapterType.EXTRA
        
        result = classifier.classify('Extra: Side Story')
        assert result == ChapterType.EXTRA
    
    def test_classify_author_note(self, classifier):
        """测试作者说分类"""
        result = classifier.classify('作者说')
        assert result == ChapterType.AUTHOR_NOTE
        
        result = classifier.classify('作者的话')
        assert result == ChapterType.AUTHOR_NOTE
    
    def test_get_type_label(self, classifier):
        """测试类型标签"""
        assert classifier.get_type_label(ChapterType.NORMAL) == '正文'
        assert classifier.get_type_label(ChapterType.EXTRA) == '番外'
        assert classifier.get_type_label(ChapterType.AUTHOR_NOTE) == '作者说'
    
    def test_group_by_type(self, classifier):
        """测试按类型分组"""
        chapters = [
            {'title': '第一章', 'type': 'normal'},
            {'title': '番外篇', 'type': 'extra'},
            {'title': '作者说', 'type': 'author_note'},
            {'title': '第二章', 'type': 'normal'}
        ]
        
        grouped = classifier.group_by_type(chapters)
        
        assert len(grouped[ChapterType.NORMAL]) == 2
        assert len(grouped[ChapterType.EXTRA]) == 1
        assert len(grouped[ChapterType.AUTHOR_NOTE]) == 1
    
    def test_add_extra_pattern(self, classifier):
        """测试添加番外规则"""
        classifier.add_extra_pattern(r'特别版')
        result = classifier.classify('特别版：结局')
        assert result == ChapterType.EXTRA
