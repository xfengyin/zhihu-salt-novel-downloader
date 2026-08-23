"""parser 测试 - 用样例 HTML 测标题/正文/目录解析。"""

from zhihu_downloader.parser import (
    ParseError,
    parse_article,
    parse_section_links,
)

SECTION_HTML = """
<html>
<head>
  <meta property="og:title" content="测试章节标题" />
</head>
<body>
  <div class="Post-RichTextContainer">
    <div class="RichText">
      <p>第一段内容</p>
      <p>第二段内容</p>
      <p>点击下载 App 立即阅读全文</p>
      <h2>小标题</h2>
      <blockquote>引用内容</blockquote>
    </div>
  </div>
</body>
</html>
"""

COLUMN_HTML = """
<html>
<body>
  <a href="/market/paid_column/12345/section/6789">章节一</a>
  <a href="/market/paid_column/12345/section/6790">章节二</a>
  <a href="https://www.zhihu.com/market/paid_column/12345/section/6791">章节三</a>
  <a href="/market/paid_column/99999/section/1">别的专栏</a>
  <a href="/market/paid_column/12345/section/6789">重复章节</a>
</body>
</html>
"""


class TestParseArticle:
    def test_title_and_content(self) -> None:
        article = parse_article(SECTION_HTML, "https://www.zhihu.com/market/paid_column/12345/section/6789")
        assert article["title"] == "测试章节标题"
        assert "第一段内容" in article["content"]
        assert "第二段内容" in article["content"]
        assert "小标题" in article["content"]
        assert "引用内容" in article["content"]

    def test_ad_paragraph_filtered(self) -> None:
        article = parse_article(SECTION_HTML)
        assert "点击下载" not in article["content"]

    def test_missing_title_raises(self) -> None:
        html = "<html><body><p>只有正文没有标题</p></body></html>"
        # body 无标题节点，parse_title 会抛 ParseError
        try:
            parse_article(html)
        except ParseError:
            return
        raise AssertionError("应抛出 ParseError")

    def test_missing_content_raises(self) -> None:
        html = "<html><head><title>只有标题</title></head><body></body></html>"
        try:
            parse_article(html)
        except ParseError:
            return
        raise AssertionError("应抛出 ParseError")


class TestParseSectionLinks:
    def test_links_absolute_dedup_same_column(self) -> None:
        links = parse_section_links(COLUMN_HTML, "https://www.zhihu.com/market/paid_column/12345")
        assert len(links) == 3
        assert links == [
            "https://www.zhihu.com/market/paid_column/12345/section/6789",
            "https://www.zhihu.com/market/paid_column/12345/section/6790",
            "https://www.zhihu.com/market/paid_column/12345/section/6791",
        ]

    def test_empty_when_no_sections(self) -> None:
        html = "<html><body><a href='/other'>无章节</a></body></html>"
        assert parse_section_links(html, "https://www.zhihu.com/market/paid_column/12345") == []
