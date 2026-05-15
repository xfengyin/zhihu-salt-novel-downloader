"""文章内容解析器"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup


@dataclass
class Chapter:
    """章节数据"""

    id: str
    title: str
    url: str
    order: int
    content: str = ""
    type: str = "normal"


@dataclass
class ArticleInfo:
    """文章信息"""

    title: str
    author: str
    chapters: list[Chapter] = field(default_factory=list)
    description: str = ""
    cover_url: str = ""

    @property
    def chapter_count(self) -> int:
        """章节数量"""
        return len(self.chapters)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "author": self.author,
            "chapters": [
                {
                    "id": ch.id,
                    "title": ch.title,
                    "url": ch.url,
                    "order": ch.order,
                    "content": ch.content,
                    "type": ch.type,
                }
                for ch in self.chapters
            ],
            "chapter_count": self.chapter_count,
            "description": self.description,
            "cover_url": self.cover_url,
        }


class ArticleParser:
    """文章解析器"""

    CHAPTER_ID_PATTERN: re.Pattern[str] = re.compile(r"/answer/(\d+)|/article/(\d+)")
    TITLE_PATTERN: re.Pattern[str] = re.compile(r"<title>(.*?)</title>")

    def __init__(self) -> None:
        self._title_pattern = self.TITLE_PATTERN

    def parse_article_info(self, html: str) -> ArticleInfo:
        """
        解析文章信息

        Args:
            html: 页面HTML

        Returns:
            ArticleInfo对象
        """
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        author = self._extract_author(soup)
        chapters = self._extract_chapters(soup)
        description = self._extract_description(soup)
        cover_url = self._extract_cover(soup)

        return ArticleInfo(
            title=title,
            author=author,
            chapters=chapters,
            description=description,
            cover_url=cover_url,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取标题"""
        meta_title = soup.find("meta", property="og:title")
        if meta_title and meta_title.get("content"):
            return meta_title["content"].strip()

        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text().strip()

        h1 = soup.find("h1")
        if h1:
            return h1.get_text().strip()

        return "未知标题"

    def _extract_author(self, soup: BeautifulSoup) -> str:
        """提取作者"""
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            return meta_author["content"].strip()

        author_elem = soup.find(attrs={"data-author-name": True})
        if author_elem:
            return author_elem["data-author-name"]

        author_link = soup.find("a", href=re.compile(r"/people/"))
        if author_link:
            return author_link.get_text().strip()

        return "未知作者"

    def _extract_description(self, soup: BeautifulSoup) -> str:
        """提取描述"""
        meta_desc = soup.find("meta", property="og:description")
        if meta_desc and meta_desc.get("content"):
            return meta_desc["content"].strip()

        meta_desc2 = soup.find("meta", attrs={"name": "description"})
        if meta_desc2 and meta_desc2.get("content"):
            return meta_desc2["content"].strip()

        return ""

    def _extract_cover(self, soup: BeautifulSoup) -> str:
        """提取封面图"""
        meta_image = soup.find("meta", property="og:image")
        if meta_image and meta_image.get("content"):
            return meta_image["content"].strip()
        return ""

    def _extract_chapters(self, soup: BeautifulSoup) -> list[Chapter]:
        """提取章节列表"""
        chapters: list[Chapter] = []
        order = 0

        toc_items = soup.find_all("li", class_=re.compile(r"toc-item|chapter"))
        for item in toc_items:
            link = item.find("a", href=True)
            if link:
                order += 1
                chapters.append(
                    Chapter(
                        id=self._extract_chapter_id(link["href"]),
                        title=self._clean_text(link.get_text()),
                        url=self._build_url(link["href"]),
                        order=order,
                    )
                )

        if not chapters:
            articles = soup.find_all(
                "div", class_=re.compile(r"article-item|content-item")
            )
            for article in articles:
                link = article.find("a", href=True)
                if link and (
                    "/answer/" in link["href"] or "/article/" in link["href"]
                ):
                    order += 1
                    title = link.get_text().strip() or article.get_text().strip()[:50]
                    chapters.append(
                        Chapter(
                            id=self._extract_chapter_id(link["href"]),
                            title=self._clean_text(title),
                            url=self._build_url(link["href"]),
                            order=order,
                        )
                    )

        if not chapters:
            article_content = soup.find(
                "div", class_=re.compile(r"RichText|article-content")
            )
            if article_content:
                current_url = ""
                link = soup.find("link", rel="canonical")
                if link and link.get("href"):
                    current_url = link["href"]

                order = 1
                title_tag = soup.find("title")
                title_text = (
                    title_tag.get_text().strip() if title_tag else "全文"
                )

                chapters.append(
                    Chapter(
                        id=self._extract_chapter_id(current_url),
                        title=title_text,
                        url=current_url,
                        order=order,
                    )
                )

        return chapters

    def _extract_chapter_id(self, href: str) -> str:
        """从URL提取章节ID"""
        if not href:
            return ""

        match = self.CHAPTER_ID_PATTERN.search(href)
        if match:
            return match.group(1) or match.group(2)

        return href.split("/")[-1]

    def _build_url(self, href: str) -> str:
        """构建完整URL"""
        if href.startswith("http"):
            return href
        elif href.startswith("/"):
            return f"https://www.zhihu.com{href}"
        else:
            return f"https://www.zhihu.com/{href}"

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ""

        text = re.sub(r"\s+", " ", text)
        text = text.strip()

        return text

    def parse_chapter_content(self, html: str) -> str:
        """
        解析章节正文内容

        Args:
            html: 章节页面HTML

        Returns:
            清洗后的纯文本内容
        """
        soup = BeautifulSoup(html, "lxml")

        for elem in soup.find_all(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "aside",
                "iframe",
                "noscript",
                "svg",
            ]
        ):
            elem.decompose()

        content: BeautifulSoup | None = None

        selectors: list[tuple[str, dict[str, Any]]] = [
            ("div", {"class": re.compile(r"RichText|article-content|post-content")}),
            ("div", {"id": re.compile(r"content|article")}),
            ("article", {}),
            ("div", {"itemprop": "articleBody"}),
        ]

        for tag, attrs in selectors:
            content = soup.find(tag, attrs)
            if content:
                break

        if not content:
            content = soup.body

        if not content:
            return ""

        text = content.get_text(separator="\n\n", strip=True)

        paragraphs = [
            p.strip()
            for p in text.split("\n\n")
            if p.strip() and len(p.strip()) > 10
        ]

        return "\n\n".join(paragraphs)

    def extract_images(self, html: str) -> list[str]:
        """
        提取图片URL列表

        Args:
            html: 页面HTML

        Returns:
            图片URL列表
        """
        soup = BeautifulSoup(html, "lxml")
        images: list[str] = []

        for img in soup.find_all("img", src=True):
            src = img["src"]

            if any(x in src.lower() for x in ["placeholder", "blank", "loading"]):
                continue

            images.append(src)

        return images
