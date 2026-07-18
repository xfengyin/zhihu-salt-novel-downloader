"""解析器测试"""

import pytest

from zhihu_downloader.parsers.article_parser import ArticleParser, ArticleInfo, Chapter
from zhihu_downloader.parsers.chapter_classifier import ChapterClassifier, ChapterType


class TestArticleParser:
    """文章解析器测试"""

    @pytest.fixture
    def parser(self) -> ArticleParser:
        return ArticleParser()

    def test_extract_chapter_id_from_answer(self, parser: ArticleParser) -> None:
        """测试从answer URL提取ID"""
        chapter_id = parser._extract_chapter_id("/answer/123456789")
        assert chapter_id == "123456789"

    def test_extract_chapter_id_from_article(self, parser: ArticleParser) -> None:
        """测试从article URL提取ID"""
        chapter_id = parser._extract_chapter_id("/article/987654321")
        assert chapter_id == "987654321"

    def test_build_url(self, parser: ArticleParser) -> None:
        """测试URL构建"""
        assert parser._build_url("http://example.com") == "http://example.com"
        assert parser._build_url("/answer/123") == "https://www.zhihu.com/answer/123"
        assert parser._build_url("answer/123") == "https://www.zhihu.com/answer/123"

    def test_clean_text(self, parser: ArticleParser) -> None:
        """测试文本清理"""
        assert parser._clean_text("  hello   world  ") == "hello world"
        assert parser._clean_text("") == ""
        assert parser._clean_text("   ") == ""


class TestChapterClassifier:
    """章节分类器测试"""

    @pytest.fixture
    def classifier(self) -> ChapterClassifier:
        return ChapterClassifier()

    def test_classify_normal(self, classifier: ChapterClassifier) -> None:
        """测试普通章节"""
        assert classifier.classify("第一章 开端") == ChapterType.NORMAL
        assert classifier.classify("第10章 真相") == ChapterType.NORMAL

    def test_classify_extra(self, classifier: ChapterClassifier) -> None:
        """测试番外章节"""
        assert classifier.classify("番外 童年") == ChapterType.EXTRA
        assert classifier.classify("外传 特别篇") == ChapterType.EXTRA
        assert classifier.classify("第5章 番外") == ChapterType.EXTRA

    def test_classify_author_note(self, classifier: ChapterClassifier) -> None:
        """测试作者说章节"""
        assert classifier.classify("作者说") == ChapterType.AUTHOR_NOTE
        assert classifier.classify("完结感言") == ChapterType.AUTHOR_NOTE
        assert classifier.classify("后记") == ChapterType.AUTHOR_NOTE

    def test_is_extra(self, classifier: ChapterClassifier) -> None:
        """测试is_extra方法"""
        assert classifier.is_extra("番外篇") is True
        assert classifier.is_extra("第一章") is False

    def test_is_author_note(self, classifier: ChapterClassifier) -> None:
        """测试is_author_note方法"""
        assert classifier.is_author_note("作者说") is True
        assert classifier.is_author_note("正文") is False


class TestChapter:
    """章节数据类测试"""

    def test_chapter_creation(self) -> None:
        """测试章节创建"""
        chapter = Chapter(
            id="123",
            title="第一章",
            url="http://example.com",
            order=1,
        )
        assert chapter.id == "123"
        assert chapter.title == "第一章"
        assert chapter.url == "http://example.com"
        assert chapter.order == 1
        assert chapter.content == ""
        assert chapter.type == "normal"


class TestArticleInfo:
    """文章信息数据类测试"""

    def test_article_info_creation(self) -> None:
        """测试文章信息创建"""
        article = ArticleInfo(
            title="测试小说",
            author="测试作者",
        )
        assert article.title == "测试小说"
        assert article.author == "测试作者"
        assert article.chapter_count == 0

    def test_to_dict(self) -> None:
        """测试转换为字典"""
        article = ArticleInfo(
            title="测试小说",
            author="测试作者",
            chapters=[
                Chapter(id="1", title="第一章", url="http://example.com", order=1),
            ],
        )
        data = article.to_dict()
        assert data["title"] == "测试小说"
        assert data["author"] == "测试作者"
        assert data["chapter_count"] == 1


class TestPaidColumnIdExtraction:
    """issue #2：盐选付费专栏与移动端 manuscript 章节 ID 提取"""

    @pytest.fixture
    def parser(self) -> ArticleParser:
        return ArticleParser()

    def test_paid_column_book(self, parser: ArticleParser) -> None:
        """盐选付费专栏（市场）整书入口"""
        chapter_id = parser._extract_chapter_id(
            "/market/paid_column/1738171776255660032"
        )
        assert chapter_id == "col-1738171776255660032"

    def test_paid_column_section(self, parser: ArticleParser) -> None:
        """盐选付费单章节（市场 section）"""
        chapter_id = parser._extract_chapter_id(
            "/market/paid_column/1864671270639165440/section/2037497376336819335"
        )
        assert chapter_id == "sec-2037497376336819335"

    def test_manuscript_book(self, parser: ArticleParser) -> None:
        """移动端 manuscript 专栏入口"""
        chapter_id = parser._extract_chapter_id(
            "/manuscript/paid_column/1738171776255660032"
        )
        assert chapter_id == "col-1738171776255660032"

    def test_manuscript_section(self, parser: ArticleParser) -> None:
        """移动端 manuscript 单章节"""
        chapter_id = parser._extract_chapter_id(
            "/manuscript/paid_column/1738171776255660032/1822560690113748992"
        )
        assert chapter_id == "sec-1822560690113748992"

    def test_full_url_paid_column(self, parser: ArticleParser) -> None:
        """完整 URL 同样能识别"""
        chapter_id = parser._extract_chapter_id(
            "https://www.zhihu.com/market/paid_column/1864671270639165440/section/2037497376336819335"
        )
        assert chapter_id == "sec-2037497376336819335"

    def test_full_url_manuscript(self, parser: ArticleParser) -> None:
        """完整移动端 URL"""
        chapter_id = parser._extract_chapter_id(
            "https://story.zhihu.com/manuscript/paid_column/1738171776255660032/1822560690113748992"
        )
        assert chapter_id == "sec-1822560690113748992"

    def test_answer_still_works(self, parser: ArticleParser) -> None:
        """回归：answer 路径仍正确"""
        chapter_id = parser._extract_chapter_id("/answer/12345")
        assert chapter_id == "12345"

    def test_article_still_works(self, parser: ArticleParser) -> None:
        """回归：article 路径仍正确"""
        chapter_id = parser._extract_chapter_id("/article/12345")
        assert chapter_id == "12345"
