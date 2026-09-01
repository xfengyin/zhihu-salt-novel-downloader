"""章节分类器 —— 移植旧版 parsers/chapter_classifier.py。

见 ARCHITECTURE_SPEC §2.11：classify(title) 返回 "normal" | "extra" | "author_note"。
判定顺序与旧版一致：先作者说、再番外、最后正文（「番外·作者的话」归 author_note）。
"""

from __future__ import annotations

import re

__all__ = ["EXTRA_PATTERNS", "AUTHOR_NOTE_PATTERNS", "classify", "is_extra", "is_author_note", "is_normal"]

#: 番外类标题正则（移植旧版 ChapterClassifier.EXTRA_PATTERNS；
#: 旧版 \\【 转义已改为直接字符，语义不变）
EXTRA_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"番外|外传|特别篇|extra|番·|附录"),
    re.compile(r"第.*?番外"),
    re.compile(r"【番外】|\[番外\]"),
]

#: 作者说类标题正则（移植旧版 ChapterClassifier.AUTHOR_NOTE_PATTERNS）
AUTHOR_NOTE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"作者说|作者的话|作者留言"),
    re.compile(r"完结感言|完本感言"),
    re.compile(r"感谢|致谢"),
    re.compile(r"后记|前言|序"),
]


def classify(title: str) -> str:
    """按标题把章节分类。

    Args:
        title: 章节标题（可为空串，空串归为 normal）。

    Returns:
        "author_note"（作者说/感言/后记等） > "extra"（番外/附录等） > "normal"。
    """
    if not title:
        return "normal"
    for pattern in AUTHOR_NOTE_PATTERNS:
        if pattern.search(title):
            return "author_note"
    for pattern in EXTRA_PATTERNS:
        if pattern.search(title):
            return "extra"
    return "normal"


def is_extra(title: str) -> bool:
    """是否为番外/附录类章节。"""
    return classify(title) == "extra"


def is_author_note(title: str) -> bool:
    """是否为作者说/感言类章节。"""
    return classify(title) == "author_note"


def is_normal(title: str) -> bool:
    """是否为正文章节。"""
    return classify(title) == "normal"
