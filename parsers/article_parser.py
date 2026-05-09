"""文章内容解析器"""

import re
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    """章节数据"""
    id: str
    title: str
    url: str
    order: int
    content: Optional[str] = None
    type: Optional[str] = None


class ArticleParser:
    """文章解析器"""

    CHAPTER_ID_PATTERN = re.compile(r'/answer/(\d+)|/article/(\d+)')

    def __init__(self, preferred_parser: Optional[str] = None):
        self._preferred_parser = preferred_parser
        self._title_pattern = re.compile(r'<title>(.*?)</title>')

    def parse_html(self, html: str, use_fallback: bool = True) -> BeautifulSoup:
        """解析HTML，支持容错"""
        try:
            if self._preferred_parser:
                return BeautifulSoup(html, self._preferred_parser)
            return BeautifulSoup(html, 'lxml')
        except Exception:
            if use_fallback:
                logger.warning("lxml解析失败，回退到html.parser")
                return BeautifulSoup(html, 'html.parser')
            raise

    def parse_article_info(self, html: str) -> Dict[str, Any]:
        """解析文章信息"""
        soup = self.parse_html(html)

        title = self._extract_title(soup)
        author = self._extract_author(soup)
        chapters = self._extract_chapters(soup)

        return {
            'title': title,
            'author': author,
            'chapters': chapters,
            'chapter_count': len(chapters)
        }

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取标题"""
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            return meta_title['content'].strip()

        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text().strip()

        h1 = soup.find('h1')
        if h1:
            return h1.get_text().strip()

        return '未知标题'

    def _extract_author(self, soup: BeautifulSoup) -> str:
        """提取作者"""
        meta_author = soup.find('meta', attrs={'name': 'author'})
        if meta_author and meta_author.get('content'):
            return meta_author['content'].strip()

        author_elem = soup.find(attrs={'data-author-name': True})
        if author_elem:
            return author_elem['data-author-name']

        author_link = soup.find('a', href=re.compile(r'/people/'))
        if author_link:
            return author_link.get_text().strip()

        return '未知作者'

    def _extract_chapters(self, soup: BeautifulSoup) -> List[Chapter]:
        """提取章节列表"""
        chapters: List[Chapter] = []
        order = 0

        toc_items = soup.find_all('li', class_=re.compile(r'toc-item|chapter'))
        for item in toc_items:
            link = item.find('a', href=True)
            if link:
                order += 1
                chapters.append(Chapter(
                    id=self._extract_chapter_id(link['href']),
                    title=self._clean_text(link.get_text()),
                    url=self._build_url(link['href']),
                    order=order
                ))

        if not chapters:
            articles = soup.find_all('div', class_=re.compile(r'article-item|content-item'))
            for article in articles:
                link = article.find('a', href=True)
                if link and ('/answer/' in link['href'] or '/article/' in link['href']):
                    order += 1
                    title = link.get_text().strip() or article.get_text().strip()[:50]
                    chapters.append(Chapter(
                        id=self._extract_chapter_id(link['href']),
                        title=self._clean_text(title),
                        url=self._build_url(link['href']),
                        order=order
                    ))

        if not chapters:
            article_content = soup.find('div', class_=re.compile(r'RichText|article-content'))
            if article_content:
                current_url = ''
                link = soup.find('link', rel='canonical')
                if link and link.get('href'):
                    current_url = link['href']

                order = 1
                title = soup.find('title')
                title_text = title.get_text().strip() if title else '全文'

                chapters.append(Chapter(
                    id=self._extract_chapter_id(current_url),
                    title=title_text,
                    url=current_url,
                    order=order
                ))

        return chapters

    def _extract_chapter_id(self, href: str) -> str:
        """从URL提取章节ID"""
        if not href:
            return ''

        match = self.CHAPTER_ID_PATTERN.search(href)
        if match:
            return match.group(1) or match.group(2)

        return href.split('/')[-1]

    def _build_url(self, href: str) -> str:
        """构建完整URL"""
        if href.startswith('http'):
            return href
        elif href.startswith('/'):
            return f'https://www.zhihu.com{href}'
        else:
            return f'https://www.zhihu.com/{href}'

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ''

        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        return text

    def parse_chapter_content(self, html: str) -> str:
        """解析章节正文内容"""
        soup = self.parse_html(html)

        for elem in soup.find_all([
            'script', 'style', 'nav', 'header', 'footer',
            'aside', 'iframe', 'noscript', 'svg'
        ]):
            elem.decompose()

        content: Optional[BeautifulSoup] = None

        selectors = [
            ('div', {'class': re.compile(r'RichText|article-content|post-content')}),
            ('div', {'id': re.compile(r'content|article')}),
            ('article', {}),
            ('div', {'itemprop': 'articleBody'})
        ]

        for tag, attrs in selectors:
            content = soup.find(tag, attrs)
            if content:
                break

        if not content:
            content = soup.body

        if not content:
            return ''

        text = content.get_text(separator='\n\n', strip=True)

        paragraphs = [
            p.strip() for p in text.split('\n\n')
            if p.strip() and len(p.strip()) > 10
        ]

        return '\n\n'.join(paragraphs)

    def extract_images(self, html: str) -> List[str]:
        """提取图片URL列表"""
        soup = self.parse_html(html)
        images: List[str] = []

        for img in soup.find_all('img', src=True):
            src = img['src']

            if any(x in src.lower() for x in ['placeholder', 'blank', 'loading']):
                continue

            images.append(src)

        return images
