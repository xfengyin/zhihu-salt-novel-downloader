"""classifier 测试：normal/extra/author_note 三分类与判定优先级。全部离线。"""

from __future__ import annotations

import re

import pytest

from zhihu_downloader.parse.classifier import (
    AUTHOR_NOTE_PATTERNS,
    EXTRA_PATTERNS,
    classify,
    is_author_note,
    is_extra,
    is_normal,
)


class TestClassify:
    @pytest.mark.parametrize(
        "title",
        ["第一章 雪夜来客", "第12章", "013 转折", "第 1 节", ""],
    )
    def test_normal(self, title: str) -> None:
        assert classify(title) == "normal"

    @pytest.mark.parametrize(
        "title",
        ["番外 重逢", "【番外】若我归来", "[番外] 雪", "特别篇：外传", "附录：人物设定", "某某·番外", "extra 篇"],
    )
    def test_extra(self, title: str) -> None:
        assert classify(title) == "extra"

    @pytest.mark.parametrize(
        "title",
        ["作者说", "作者的话", "作者留言", "完结感言", "完本感言", "感谢支持", "致谢", "后记", "前言"],
    )
    def test_author_note(self, title: str) -> None:
        assert classify(title) == "author_note"

    def test_author_note_wins_over_extra(self) -> None:
        # 旧版判定顺序：先作者说、再番外（移植不改语义）
        assert classify("番外·作者的话") == "author_note"

    def test_returns_plain_str(self) -> None:
        result = classify("第一章")
        assert isinstance(result, str) and result == "normal"

    def test_substring_match_semantics_kept(self) -> None:
        # 「感谢」「序」为子串匹配属旧版行为，v5 原样移植并在此钉死
        assert classify("第一章 感谢有你") == "author_note"
        assert classify("序幕") == "author_note"


class TestHelpers:
    def test_is_extra(self) -> None:
        assert is_extra("番外") is True
        assert is_extra("第一章") is False

    def test_is_author_note(self) -> None:
        assert is_author_note("作者说") is True
        assert is_author_note("第一章") is False

    def test_is_normal(self) -> None:
        assert is_normal("第一章") is True
        assert is_normal("番外") is False


class TestPatternTables:
    def test_tables_are_compiled_regexes(self) -> None:
        assert EXTRA_PATTERNS and AUTHOR_NOTE_PATTERNS
        assert all(isinstance(p, type(re.compile(""))) for p in EXTRA_PATTERNS + AUTHOR_NOTE_PATTERNS)

    def test_extra_and_note_tables_disjoint_kinds(self) -> None:
        assert all("作者" not in p.pattern for p in EXTRA_PATTERNS)
        assert all("番外" not in p.pattern for p in AUTHOR_NOTE_PATTERNS)
