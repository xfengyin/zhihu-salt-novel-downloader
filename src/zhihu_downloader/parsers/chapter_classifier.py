"""章节分类器"""

from __future__ import annotations

import re
from enum import Enum
from typing import ClassVar


class ChapterType(str, Enum):
    """章节类型"""

    NORMAL = "normal"
    EXTRA = "extra"
    AUTHOR_NOTE = "author_note"
    UNKNOWN = "unknown"


class ChapterClassifier:
    """章节分类器"""

    EXTRA_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"番外|外传|特别篇|extra|番·|附录"),
        re.compile(r"第.*?番外"),
        re.compile(r"\【番外\】|\[番外\]"),
    ]

    AUTHOR_NOTE_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"作者说|作者的话|作者留言"),
        re.compile(r"完结感言|完本感言"),
        re.compile(r"感谢|致谢"),
        re.compile(r"后记|前言|序"),
    ]

    def __init__(self) -> None:
        self._extra_patterns = self.EXTRA_PATTERNS
        self._author_note_patterns = self.AUTHOR_NOTE_PATTERNS

    def classify(self, title: str) -> ChapterType:
        """
        分类章节

        Args:
            title: 章节标题

        Returns:
            章节类型
        """
        for pattern in self._author_note_patterns:
            if pattern.search(title):
                return ChapterType.AUTHOR_NOTE

        for pattern in self._extra_patterns:
            if pattern.search(title):
                return ChapterType.EXTRA

        return ChapterType.NORMAL

    def is_extra(self, title: str) -> bool:
        """判断是否为番外"""
        return self.classify(title) == ChapterType.EXTRA

    def is_author_note(self, title: str) -> bool:
        """判断是否为作者说"""
        return self.classify(title) == ChapterType.AUTHOR_NOTE

    def is_normal(self, title: str) -> bool:
        """判断是否为正文"""
        return self.classify(title) == ChapterType.NORMAL
