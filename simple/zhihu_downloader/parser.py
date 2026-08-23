"""HTML 解析 - 提取盐选章节/专栏内容。

容错优先：按常见选择器依次尝试，找不到内容时给出明确错误。
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


class ParseError(Exception):
    """解析失败（找不到标题/正文）。"""


# 正文容器的候选 CSS 选择器（按优先级）
_CONTENT_SELECTORS = [
    "div.RichText",
    "div.Post-RichTextContainer",
    "div.RichContent-inner",
    "article",
    "div.Post-RichText",
]

# 标题的候选选择器
_TITLE_SELECTORS = [
    "h1.Post-Title",
    "h1",
    "meta[property='og:title']",
    "title",
]


def _text(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def parse_title(soup: BeautifulSoup) -> str:
    """提取标题：og:title 优先，其次 h1、title。"""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()

    for selector in ("h1.Post-Title", "h1"):
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return node.get_text(strip=True)

    title_node = soup.find("title")
    if title_node and title_node.get_text(strip=True):
        return title_node.get_text(strip=True)

    raise ParseError("未找到文章标题（og:title / h1 / title 均缺失）")


def _extract_content(soup: BeautifulSoup) -> str:
    """从候选容器提取正文段落文本，去广告/水印（空段落、常见广告词）。"""
    container = None
    for selector in _CONTENT_SELECTORS:
        container = soup.select_one(selector)
        if container:
            break

    if container is None:
        container = soup.body or soup

    # 只保留段落/标题/列表/引用等文本块
    blocks = []
    for node in container.find_all(["p", "h2", "h3", "h4", "li", "blockquote"]):
        text = node.get_text(strip=True)
        if not text:
            continue
        if any(word in text for word in ("点击下载", "扫码下载", "关注公众号")):
            continue
        blocks.append(text)

    if not blocks:
        # 兜底：整个容器的纯文本
        text = container.get_text("\n", strip=True)
        if text:
            return text
        raise ParseError("未找到文章正文（内容容器为空）")

    return "\n\n".join(blocks)


def parse_article(html: str, url: str = "") -> dict:
    """解析单章页面。

    Returns:
        {"title": str, "content": str, "url": str}
    """
    soup = _text(html)
    title = parse_title(soup)
    content = _extract_content(soup)
    return {"title": title, "content": content, "url": url}


def parse_page_title(html: str) -> str:
    """仅提取页面标题（找不到时返回空字符串）。"""
    try:
        return parse_title(_text(html))
    except ParseError:
        return ""


def parse_section_links(html: str, base_url: str) -> list[str]:
    """从专栏目录页提取章节链接（去重、绝对化、过滤到同专栏）。"""
    soup = _text(html)
    base = urlparse(base_url)
    base_path = base.path.rstrip("/")
    links: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/section/" not in href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.hostname != base.hostname:
            continue
        # 专栏页只保留同专栏下的章节链接
        if "/paid_column/" in base_path and not parsed.path.startswith(base_path + "/"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)

    return links
