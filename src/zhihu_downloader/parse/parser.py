"""结构化 HTML 解析（v5 关键升级）—— 输出 types.Block 列表。

见 ARCHITECTURE_SPEC §2.9：
- parse_article：正文容器按 v4 选择器降级链定位，遍历 h2/h3/p/li/blockquote/img
  生成结构化 Block（img 优先取懒加载 data-original）；标题按
  og:title > h1.Post-Title > h1 > title 降级；找不到标题或正文抛 ParseError（中文消息）。
- parse_toc：从专栏目录页提取章节链接 + 标题文本，返回 list[ChapterRef]。
- parse_page_title：仅提取页面标题，找不到返回空串。

注意：本模块不做广告清洗（由 parse.cleaner 负责），保证解析层职责单一。
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ..errors import ParseError
from ..types import Article, Block, ChapterRef
from .classifier import classify

__all__ = ["parse_article", "parse_toc", "parse_page_title"]

#: 正文容器候选选择器（按优先级降级，同 v4 simple/parser.py）
_CONTENT_SELECTORS: tuple[str, ...] = (
    "div.RichText",
    "div.Post-RichTextContainer",
    "div.RichContent-inner",
    "article",
    "div.Post-RichText",
)

#: 参与结构化提取的正文标签
_BODY_TAGS: tuple[str, ...] = ("h2", "h3", "p", "li", "blockquote", "img")

#: 标签名 → Block.kind 映射（img 单独处理）
_KIND_BY_TAG: dict[str, str] = {
    "h2": "h2",
    "h3": "h3",
    "p": "p",
    "li": "li",
    "blockquote": "quote",
}

#: 正文容器内需要整体剔除的噪音标签
_NOISE_TAGS: tuple[str, ...] = ("script", "style", "noscript", "svg", "iframe", "button")

#: 图片懒加载属性优先级（data-original 为知乎真实地址）
_IMG_SRC_ATTRS: tuple[str, ...] = ("data-original", "data-src", "src")

_WS_RE = re.compile(r"\s+")


def _soup(html: str) -> BeautifulSoup:
    """用标准库 html.parser 构建文档树（零额外依赖）。"""
    return BeautifulSoup(html, "html.parser")


def _attr_str(node: Tag, name: str) -> str:
    """安全读取字符串属性（缺失/多值属性一律归一为 strip 后的字符串）。"""
    value = node.get(name)
    if isinstance(value, list):
        value = value[0] if value else ""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _collapse(text: str) -> str:
    """把连续空白（含全角空格）压成单个空格并去首尾。"""
    return _WS_RE.sub(" ", text).strip()


def _extract_title(soup: BeautifulSoup) -> str:
    """按 og:title > h1.Post-Title > h1 > title 降级提取标题，全部缺失抛 ParseError。"""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og is not None:
        content = _attr_str(og, "content")
        if content:
            return content

    for selector in ("h1.Post-Title", "h1"):
        node = soup.select_one(selector)
        if node is not None:
            text = _collapse(node.get_text(" ", strip=True))
            if text:
                return text

    title_node = soup.find("title")
    if title_node is not None:
        text = _collapse(title_node.get_text(" ", strip=True))
        if text:
            return text

    raise ParseError(
        "未找到文章标题（og:title / h1 / title 均缺失）。"
        "请确认链接指向回答或盐选章节页；若页面要求登录，请先执行 zhihu-downloader login 更新 Cookie。"
    )


def _node_text(node: Tag) -> str:
    """提取节点文本：<br> 等换行保留为 \\n，行内空白折叠。"""
    raw = node.get_text(separator="\n", strip=True)
    lines = [collapsed for collapsed in (_WS_RE.sub(" ", ln).strip() for ln in raw.splitlines()) if collapsed]
    return "\n".join(lines)


def _img_src(node: Tag) -> str:
    """取图片真实地址：data-original > data-src > src；跳过空值与 data: 占位图。"""
    for attr in _IMG_SRC_ATTRS:
        value = _attr_str(node, attr)
        if value and not value.startswith("data:"):
            return value
    return ""


def _extract_blocks(container: Tag) -> list[Block]:
    """遍历容器生成结构化 Block 列表（文档顺序，嵌套文本去重）。"""
    blocks: list[Block] = []
    collected_text_ids: set[int] = set()
    for node in container.find_all(list(_BODY_TAGS)):
        name = node.name or ""
        if name == "img":
            src = _img_src(node)
            if not src:
                continue
            blocks.append(Block(kind="img", src=src, alt=_attr_str(node, "alt")))
            continue
        # 祖先已是收集过的文本块（如 blockquote/li 内的 p）则跳过，避免重复
        if any(id(parent) in collected_text_ids for parent in node.parents):
            continue
        text = _node_text(node)
        if not text:
            continue
        blocks.append(Block(kind=_KIND_BY_TAG[name], text=text))
        collected_text_ids.add(id(node))
    return blocks


def parse_article(html: str, url: str = "") -> Article:
    """解析单章页面为 Article（结构化 blocks + 分类器给出的 chapter_type）。

    Args:
        html: 章节页面 HTML。
        url: 该章节的来源 URL（原样写入 Article.url）。

    Raises:
        ParseError: 找不到标题或正文（中文消息含下一步建议）。
    """
    soup = _soup(html)
    title = _extract_title(soup)

    container: Tag | None = None
    for selector in _CONTENT_SELECTORS:
        found = soup.select_one(selector)
        if found is not None:
            container = found
            break
    if container is None:
        container = soup.body if soup.body is not None else soup
    for noise in container.find_all(list(_NOISE_TAGS)):
        noise.decompose()

    blocks = _extract_blocks(container)
    if not blocks:
        # 兜底（容错优先，同 v4）：容器内无结构化标签时，整段文本作为单个 p 块
        text = _node_text(container)
        if text:
            blocks = [Block(kind="p", text=text)]
    if not blocks:
        raise ParseError(
            "未找到文章正文（内容容器为空）。"
            "可能原因：链接不是章节页、内容仅 APP 内可见，或 Cookie 已失效——"
            "请检查链接类型或重新登录后重试。"
        )

    return Article(title=title, url=url, blocks=blocks, chapter_type=classify(title))


def _link_title(node: Tag) -> str:
    """目录链接的标题文本：可见文字优先，其次 title/aria-label 属性。"""
    text = _collapse(node.get_text(" ", strip=True))
    if text:
        return text
    return _attr_str(node, "title") or _attr_str(node, "aria-label")


def parse_toc(html: str, base_url: str) -> list[ChapterRef]:
    """从专栏目录页提取章节引用（v4 parse_section_links 升级：同时抓标题文本）。

    规则：只保留含 /section/ 的链接；绝对化后要求与 base_url 同主机名；
    base 为付费专栏页（路径含 /paid_column/）时进一步限定同专栏前缀；按 URL 去重、
    保持文档顺序；index 从 1 开始；type 由章节标题经分类器得出。

    Args:
        html: 专栏目录页 HTML。
        base_url: 目录页自身的绝对 URL。

    Returns:
        章节引用列表；无章节时返回空列表。
    """
    soup = _soup(html)
    try:
        base = urlparse(base_url)
        base_host = (base.hostname or "").lower()
        base_path = base.path.rstrip("/")
    except ValueError:
        base_host, base_path = "", ""

    refs: list[ChapterRef] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = _attr_str(a, "href")
        if "/section/" not in href:
            continue
        absolute = urljoin(base_url, href)
        try:
            parsed = urlparse(absolute)
        except ValueError:
            continue
        host = (parsed.hostname or "").lower()
        if base_host and host != base_host:
            continue
        # 专栏目录页只保留同专栏下的章节链接
        if "/paid_column/" in base_path and not parsed.path.startswith(base_path + "/"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        title = _link_title(a)
        refs.append(
            ChapterRef(url=absolute, title=title, index=len(refs) + 1, type=classify(title))
        )
    return refs


def parse_page_title(html: str) -> str:
    """仅提取页面标题；找不到时返回空字符串（不抛异常）。"""
    try:
        return _extract_title(_soup(html))
    except ParseError:
        return ""
