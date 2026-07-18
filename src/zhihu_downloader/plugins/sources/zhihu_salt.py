"""知乎盐选源插件

支持的 URL 类型：
- https://www.zhihu.com/question/xxx/answer/yyy   旧版回答
- https://zhuanlan.zhihu.com/p/xxx                 专栏文章
- https://www.zhihu.com/market/paid_column/xxx     盐选专栏（市场付费）
- https://www.zhihu.com/market/paid_column/xxx/section/yyy  盐选单章节
- https://story.zhihu.com/manuscript/paid_column/xxx  APP 端付费专栏
- https://story.zhihu.com/manuscript/paid_column/xxx/section/yyy  APP 端单章节

注：
- "仅 APP 内阅读"的盐选小说（mst/xsec 签名）需要调用知乎移动端 API，
  本插件暂不实现签名算法。用户传入此类 URL 时会给出明确提示。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

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
        return [
            "zhihu.com",
            "www.zhihu.com",
            "story.zhihu.com",
            "zhuanlan.zhihu.com",
        ]

    def __init__(self) -> None:
        self._parser = ArticleParser()

    def can_handle(self, url: str) -> bool:
        """匹配所有知乎系域名（含 APP 端 story.zhihu.com）

        后续会通过 URL 路径判断属于哪种类型（公开回答 / 盐选 / 仅 APP），
        不同类型走不同的解析与下载策略。
        """
        if not url:
            return False
        try:
            host = urlparse(url).netloc.lower()
        except Exception:
            return False
        return any(host == d or host.endswith(f".{d}") for d in self.domains)

    def detect_url_type(self, url: str) -> str:
        """检测 URL 类型，便于给出友好提示

        Returns:
            - "answer"        公开回答（默认最佳支持）
            - "column"        盐选专栏（市场/付费）
            - "section"       盐选单章节（最常见入口）
            - "app_column"    移动端付费专栏（需 mst 签名，暂不支持）
            - "app_section"   移动端单章节（需 mst 签名，暂不支持）
            - "unknown"       非知乎系 URL
        """
        if not self.can_handle(url):
            return "unknown"

        path = urlparse(url).path

        # story.zhihu.com 移动端签名内容
        if "story.zhihu.com" in url:
            # 移动端 section 不带 /section/ 关键词，路径形如
            # /manuscript/paid_column/<col_id>/<sec_id>
            if self._parser.MANUSCRIPT_PATTERN.search(path) and path.count("/") >= 4:
                return "app_section"
            return "app_column"

        # 盐选市场付费
        if "/market/paid_column/" in path:
            if "/section/" in path:
                return "section"
            return "column"

        # 公开回答
        if "/answer/" in path:
            return "answer"

        # 专栏文章
        if "zhuanlan.zhihu.com" in url:
            return "column"

        return "column"  # 默认按专栏处理

    def is_app_only(self, url: str) -> bool:
        """判断是否为「仅 APP 内阅读」类 URL（需 mst/xsec 签名）

        此类 URL 当前版本无法下载，但应给出明确提示而非静默失败。
        """
        url_type = self.detect_url_type(url)
        return url_type in ("app_column", "app_section")

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

