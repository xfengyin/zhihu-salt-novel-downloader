"""正文清洗 —— 移植旧版 utils/content_cleaner.py 的广告/水印正则表。

R1 审查 m4：英文词形（AD/APP/zhihu.com）不得作为裸子串误杀正常文本——
"READ/SHADOW/HEADER/APPLE" 都含裸子串却必须保留。边界刻意用
`(?<![A-Za-z])X(?![A-Za-z])` 而非反斜杠 b 词边界：Python re 里 CJK 也算词字符，
词边界会把「下载知乎APP」这类中英夹杂真广告漏掉；排除式环视只挡 ASCII
字母拼接，中文邻接照常命中。中文词表曾按裁决维持原语义；主审 round49 依据 D1 反查改判：
「来源：.*?」无锚定导致任何含「这段引文的出处：《清史稿》」的正常段落整块被删（数据丢失
劣于脚标漏删），该条已锚定为「块首 + 短块」——漏删脚标可接受，误杀正文不可接受。

v5 与旧版的差异（见 ARCHITECTURE_SPEC §2.10）：清洗对象从「拍平后的文本行」
改为结构化的 Article.blocks——命中广告/水印/垃圾正则的文本块整块过滤，
img 块不受影响；支持 extra_patterns 追加自定义正则。

说明：旧版对 <3 字符的短行做垃圾判定，v5 不再沿用（小说正文存在
「好。」「走！」等合法短段落，整块过滤策略下误伤代价更高）。
"""

from __future__ import annotations

import re

from ..types import Article, Block

__all__ = ["AD_PATTERNS", "WATERMARK_PATTERNS", "TRASH_PATTERNS", "clean"]

#: 广告类正则（移植旧版 ContentCleaner.AD_PATTERNS）
AD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"关注公众号|扫码关注|微信搜索"),
    re.compile(r"知乎.*?会员|盐选.*?会员"),
    re.compile(r"付费内容|购买全文|解锁全文"),
    # 词形边界（R1 m4）：(?<![A-Za-z])AD(?![A-Za-z]) 挡 READ/SHADOW/HEADER，
    # 而 【AD】"AD 已发布" 与中文邻接形态照常命中。
    re.compile(r"广告|(?<![A-Za-z])AD(?![A-Za-z])|推广"),
    re.compile(r"下载.*?(?<![A-Za-z])APP(?![A-Za-z])|打开.*?(?<![A-Za-z])APP(?![A-Za-z])"),
    re.compile(r"点击.*?查看|点击.*?阅读"),
]

#: 水印类正则（移植旧版 ContentCleaner.WATERMARK_PATTERNS）
WATERMARK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"@知乎|(?<![A-Za-z0-9])zhihu\.com"),
    re.compile(r"\[.*?@.*?\]"),
    # 主审 round49 改判（D1 证据）：原 r"来源：.*?|出处：.*?" 无锚定，命中任意段落
    # 中部即整块误删。锚定形态专杀独立脚标行（「来源：xxx」整块且冒号后短）；
    # 「本文来源：xxx」类脚标现按设计漏删——收紧误杀面优先于扩大删除面。
    re.compile(r"^\s*(?:来源|出处)[:：][^。\n]{0,30}$"),
]

#: 垃圾块正则（移植旧版 ContentCleaner.TRASH_PATTERNS，整块锚定）
TRASH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*\[.*?\]\s*$"),
    re.compile(r"^\s*\{.*?\}\s*$"),
    re.compile(r"^\s*<!--.*?-->\s*$", re.DOTALL),
    re.compile(r"^\s*相关推荐\s*$"),
    re.compile(r"^\s*相关阅读\s*$"),
]


def _is_junk(text: str, patterns: list[re.Pattern[str]]) -> bool:
    """文本块是否应被过滤：空白块，或命中任一正则。"""
    stripped = text.strip()
    if not stripped:
        return True
    return any(pattern.search(stripped) for pattern in patterns)


def clean(article: Article, extra_patterns: list[str] | None = None) -> Article:
    """就地过滤 article.blocks 中的广告/水印/垃圾文本块。

    Args:
        article: 待清洗文章（blocks 被原地替换）。
        extra_patterns: 追加的自定义正则（字符串形式，按 re.search 语义，
            命中即整块过滤）。非法正则会抛出 re.error。

    Returns:
        同一个 Article 对象（便于链式调用）。img 块全部保留。
    """
    patterns = AD_PATTERNS + WATERMARK_PATTERNS + TRASH_PATTERNS
    if extra_patterns:
        patterns = patterns + [re.compile(p) for p in extra_patterns]

    kept: list[Block] = []
    for block in article.blocks:
        if block.kind == "img":
            kept.append(block)
            continue
        if _is_junk(block.text, patterns):
            continue
        kept.append(block)
    article.blocks[:] = kept
    return article
