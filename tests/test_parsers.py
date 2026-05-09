"""解析器测试"""

import pytest
from parsers.article_parser import ArticleParser, Chapter
from parsers.chapter_classifier import ChapterClassifier, ChapterType


class TestArticleParser:
    """文章解析器测试"""

    def test_extract_title(self, parser, sample_html):
        """测试提取标题"""
        info = parser.parse_article_info(sample_html)
        assert info['title'] == '测试小说'

    def test_clean_text(self, parser):
        """测试文本清理"""
        text = "  多个   空格   "
        cleaned = parser._clean_text(text)
        assert cleaned == "多个 空格"

    def test_extract_chapter_id(self, parser):
        """测试提取章节ID"""
        assert parser._extract_chapter_id('/answer/123456') == '123456'
        assert parser._extract_chapter_id('/article/789') == '789'

    def test_build_url(self, parser):
        """测试构建URL"""
        assert parser._build_url('http://example.com') == 'http://example.com'
        assert parser._build_url('/answer/123') == 'https://www.zhihu.com/answer/123'


class TestChapterClassifier:
    """章节分类器测试"""

    @pytest.fixture
    def classifier(self):
        return ChapterClassifier()

    def test_classify_normal(self, classifier):
        """测试普通章节"""
        result = classifier.classify('第一章：开端')
        assert result == ChapterType.NORMAL

    def test_classify_extra(self, classifier):
        """测试番外章节"""
        result = classifier.classify('番外：特别篇')
        assert result == ChapterType.EXTRA

        result = classifier.classify('外传：前传')
        assert result == ChapterType.EXTRA

    def test_classify_author_note(self, classifier):
        """测试作者说"""
        result = classifier.classify('作者说')
        assert result == ChapterType.AUTHOR_NOTE

        result = classifier.classify('作者的话')
        assert result == ChapterType.AUTHOR_NOTE

    def test_get_type_label(self, classifier):
        """测试获取类型标签"""
        assert classifier.get_type_label(ChapterType.NORMAL) == '正文'
        assert classifier.get_type_label(ChapterType.EXTRA) == '番外'
        assert classifier.get_type_label(ChapterType.AUTHOR_NOTE) == '作者说'
        assert classifier.get_type_label(ChapterType.UNKNOWN) == '其他'

    def test_group_by_type(self, classifier):
        """测试按类型分组"""
        chapters = [
            {'title': '第一章', 'type': 'normal'},
            {'title': '番外', 'type': 'extra'},
            {'title': '作者说', 'type': 'author_note'},
        ]

        grouped = classifier.group_by_type(chapters)

        assert ChapterType.NORMAL in grouped
        assert ChapterType.EXTRA in grouped
        assert ChapterType.AUTHOR_NOTE in grouped

    def test_add_extra_pattern(self, classifier):
        """测试添加额外模式"""
        classifier.add_extra_pattern('特典')
        result = classifier.classify('特典：新年篇')
        assert result == ChapterType.EXTRA
