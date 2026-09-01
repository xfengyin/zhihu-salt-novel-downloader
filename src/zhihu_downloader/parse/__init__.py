"""parse 包：URL 类型识别 + 结构化解析 + 广告清洗 + 章节分类。

公共 API 重导出（见 ARCHITECTURE_SPEC §2.8-2.11）。
"""

from .classifier import classify
from .cleaner import clean
from .parser import parse_article, parse_page_title, parse_toc
from .urltype import URL_TYPES, detect, friendly_hint, is_app_only

__all__ = [
    "URL_TYPES",
    "classify",
    "clean",
    "detect",
    "friendly_hint",
    "is_app_only",
    "parse_article",
    "parse_page_title",
    "parse_toc",
]
