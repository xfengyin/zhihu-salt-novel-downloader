"""知乎盐选源插件"""

from __future__ import annotations

import pluggy

from zhihu_downloader.parsers.article_parser import ArticleInfo, ArticleParser, Chapter
from zhihu_downloader.plugins.protocol import SourceContext, SourcePlugin

hookimpl = pluggy.HookimplMarker("zhihu_downloader")


class ZhihuSaltSource(SourcePlugin):
    """知乎盐选源插件"""

    @property
    def name(self) -> str:
        return "知乎盐选"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def domains(self) -> list[str]:
        return ["zhihu.com", "www.zhihu.com"]

    def __init__(self) -> None:
        self._parser = ArticleParser()

    def can_handle(self, url: str) -> bool:
        return any(domain in url for domain in self.domains)

    async def parse_book(self, html: str, ctx: SourceContext) -> ArticleInfo:
        return self._parser.parse_article_info(html)

    async def fetch_chapter(self, url: str, ctx: SourceContext) -> Chapter:
        html = await ctx.fetch(url)
        content = self._parser.parse_chapter_content(html)

        chapter_id = self._parser._extract_chapter_id(url)
        title = self._extract_chapter_title(html)

        return Chapter(
            id=chapter_id,
            title=title,
            url=url,
            order=0,
            content=content,
            type="normal",
        )

    def _extract_chapter_title(self, html: str) -> str:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        return self._parser._extract_title(soup)


@hookimpl
def zsd_register_source() -> list[type[SourcePlugin]]:
    """注册数据源插件"""
    return [ZhihuSaltSource]
