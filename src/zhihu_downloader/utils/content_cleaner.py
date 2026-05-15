"""内容清洗器"""

from __future__ import annotations

import re
from typing import Pattern


class ContentCleaner:
    """内容清洗器"""

    AD_PATTERNS: list[Pattern[str]] = [
        re.compile(r"关注公众号|扫码关注|微信搜索"),
        re.compile(r"知乎.*?会员|盐选.*?会员"),
        re.compile(r"付费内容|购买全文|解锁全文"),
        re.compile(r"广告|AD|推广"),
        re.compile(r"下载.*?APP|打开.*?APP"),
        re.compile(r"点击.*?查看|点击.*?阅读"),
    ]

    WATERMARK_PATTERNS: list[Pattern[str]] = [
        re.compile(r"@知乎|zhihu\.com"),
        re.compile(r"\[.*?@.*?\]"),
        re.compile(r"来源：.*?|出处：.*?"),
    ]

    TRASH_PATTERNS: list[Pattern[str]] = [
        re.compile(r"^\s*\[.*?\]\s*$"),
        re.compile(r"^\s*\{.*?\}\s*$"),
        re.compile(r"^\s*<!--.*?-->\s*$", re.DOTALL),
        re.compile(r"^\s*相关推荐\s*$"),
        re.compile(r"^\s*相关阅读\s*$"),
    ]

    def __init__(
        self,
        remove_ads: bool = True,
        remove_watermarks: bool = True,
    ) -> None:
        """
        初始化内容清洗器

        Args:
            remove_ads: 是否移除广告
            remove_watermarks: 是否移除水印
        """
        self._remove_ads = remove_ads
        self._remove_watermarks = remove_watermarks
        self._ad_patterns = self.AD_PATTERNS
        self._watermark_patterns = self.WATERMARK_PATTERNS
        self._trash_patterns = self.TRASH_PATTERNS

    def clean(self, content: str) -> str:
        """
        清洗内容

        Args:
            content: 原始内容

        Returns:
            清洗后的内容
        """
        if not content:
            return ""

        lines = content.split("\n")
        cleaned_lines: list[str] = []

        for line in lines:
            line = self._clean_line(line)
            if line and not self._is_trash_line(line):
                cleaned_lines.append(line)

        return "\n\n".join(cleaned_lines)

    def _clean_line(self, line: str) -> str:
        """清洗单行文本"""
        if not line:
            return ""

        line = line.strip()

        if self._remove_ads:
            for pattern in self._ad_patterns:
                line = pattern.sub("", line)

        if self._remove_watermarks:
            for pattern in self._watermark_patterns:
                line = pattern.sub("", line)

        line = re.sub(r"\s+", " ", line)
        line = line.strip()

        return line

    def _is_trash_line(self, line: str) -> bool:
        """判断是否为垃圾行"""
        if len(line) < 3:
            return True

        for pattern in self._trash_patterns:
            if pattern.match(line):
                return True

        return False
