"""文章内容解析器"""

import re
import logging
from typing import Dict, List, Optional, Any
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


class ArticleParser:
    """文章解析器"""
    
    # 章节ID提取正则
    CHAPTER_ID_PATTERN = re.compile(r'/answer/(\d+)|/article/(\d+)')
    
    def __init__(self):
        self._title_pattern = re.compile(r'<title>(.*?)</title>')
    
    def parse_article_info(self, html: str) -> Dict[str, Any]:
        """
        解析文章信息
        
        Args:
            html: 页面HTML
            
        Returns:
            包含title, author, chapters等信息的字典
        """
        soup = BeautifulSoup(html, 'lxml')
        
        # 提取标题
        title = self._extract_title(soup)
        
        # 提取作者
        author = self._extract_author(soup)
        
        # 提取章节列表
        chapters = self._extract_chapters(soup)
        
        return {
            'title': title,
            'author': author,
            'chapters': chapters,
            'chapter_count': len(chapters)
        }
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取标题"""
        # 优先从meta标签获取
        meta_title = soup.find('meta', property='og:title')
        if meta_title and meta_title.get('content'):
            return meta_title['content'].strip()
        
        # 从title标签获取
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text().strip()
        
        # 从h1标签获取
        h1 = soup.find('h1')
        if h1:
            return h1.get_text().strip()
        
        return '未知标题'
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """提取作者"""
        # 从meta标签获取
        meta_author = soup.find('meta', attrs={'name': 'author'})
        if meta_author and meta_author.get('content'):
            return meta_author['content'].strip()
        
        # 从data-*属性获取
        author_elem = soup.find(attrs={'data-author-name': True})
        if author_elem:
            return author_elem['data-author-name']
        
        # 从链接文本匹配
        author_link = soup.find('a', href=re.compile(r'/people/'))
        if author_link:
            return author_link.get_text().strip()
        
        return '未知作者'
    
    def _extract_chapters(self, soup: BeautifulSoup) -> List[Chapter]:
        """
        提取章节列表
        
        知乎盐选小说的章节可能以多种形式存在：
        1. 目录列表
        2. 文章列表项
        3. 分页内容
        """
        chapters = []
        order = 0
        
        # 方式1: 从目录列表获取
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
        
        # 方式2: 从文章列表获取
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
        
        # 方式3: 单文章模式（整篇内容）
        if not chapters:
            article_content = soup.find('div', class_=re.compile(r'RichText|article-content'))
            if article_content:
                # 提取URL
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
        
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text)
        
        # 移除特殊字符
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
        soup = BeautifulSoup(html, 'lxml')
        
        # 移除不需要的元素
        for elem in soup.find_all([
            'script', 'style', 'nav', 'header', 'footer',
            'aside', 'iframe', 'noscript', 'svg'
        ]):
            elem.decompose()
        
        # 定位正文区域
        content = None
        
        # 尝试多种选择器
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
        
        # 提取文本
        text = content.get_text(separator='\n\n', strip=True)
        
        # 分段处理
        paragraphs = [
            p.strip() for p in text.split('\n\n')
            if p.strip() and len(p.strip()) > 10
        ]
        
        return '\n\n'.join(paragraphs)
    
    def extract_images(self, html: str) -> List[str]:
        """
        提取图片URL列表
        
        Args:
            html: 页面HTML
            
        Returns:
            图片URL列表
        """
        soup = BeautifulSoup(html, 'lxml')
        images = []
        
        for img in soup.find_all('img', src=True):
            src = img['src']
            
            # 过滤占位图
            if any(x in src.lower() for x in ['placeholder', 'blank', 'loading']):
                continue
            
            images.append(src)
        
        return images
