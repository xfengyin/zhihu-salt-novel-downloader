"""urltype 测试：7 种 URL 分类 + app_only 判定与 story→market 友好提示。全部离线。"""

from __future__ import annotations

import pytest

from zhihu_downloader.parse.urltype import URL_TYPES, detect, friendly_hint, is_app_only


class TestDetect:
    """detect() 的七种分类。"""

    def test_answer(self) -> None:
        assert detect("https://www.zhihu.com/question/20300378/answer/99999999") == "answer"

    def test_column(self) -> None:
        assert detect("https://www.zhihu.com/market/paid_column/1234567890123") == "column"

    def test_section(self) -> None:
        assert detect("https://www.zhihu.com/market/paid_column/1234/section/5678") == "section"

    def test_app_column(self) -> None:
        assert detect("https://story.zhihu.com/manuscript/paid_column/1234") == "app_column"

    def test_app_section(self) -> None:
        assert detect("https://story.zhihu.com/manuscript/paid_column/1234/5678") == "app_section"

    def test_app_other_path_defaults_to_app_column(self) -> None:
        assert detect("https://story.zhihu.com/reader/foo") == "app_column"

    def test_zhuanlan(self) -> None:
        assert detect("https://zhuanlan.zhihu.com/p/123456") == "zhuanlan"

    def test_unknown_external_host(self) -> None:
        assert detect("https://example.com/market/paid_column/1") == "unknown"

    def test_unknown_empty_and_garbage(self) -> None:
        assert detect("") == "unknown"
        assert detect("not a url at all") == "unknown"

    def test_lookalike_hosts_are_unknown(self) -> None:
        # 仿冒域名不得判为知乎链接
        assert detect("https://zhihu.com.evil.net/market/paid_column/1/section/2") == "unknown"
        assert detect("https://notzhihu.com/p/1") == "unknown"

    def test_uppercase_host_normalized(self) -> None:
        assert detect("https://WWW.ZHIHU.COM/market/paid_column/1/section/2") == "section"

    def test_other_zhihu_page_falls_back_to_column(self) -> None:
        # 与旧版一致：知乎系其余页面默认按专栏处理
        assert detect("https://www.zhihu.com/pub/whatever") == "column"

    def test_all_results_are_declared_types(self) -> None:
        samples = [
            "https://www.zhihu.com/question/1/answer/2",
            "https://www.zhihu.com/market/paid_column/1",
            "https://www.zhihu.com/market/paid_column/1/section/2",
            "https://story.zhihu.com/manuscript/paid_column/1",
            "https://story.zhihu.com/manuscript/paid_column/1/2",
            "https://zhuanlan.zhihu.com/p/1",
            "https://example.com/",
        ]
        assert {detect(u) for u in samples} <= set(URL_TYPES)


class TestIsAppOnly:
    """is_app_only() 判定。"""

    @pytest.mark.parametrize(
        "url",
        [
            "https://story.zhihu.com/manuscript/paid_column/1234",
            "https://story.zhihu.com/manuscript/paid_column/1234/5678",
        ],
    )
    def test_app_urls(self, url: str) -> None:
        assert is_app_only(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.zhihu.com/market/paid_column/1234",
            "https://www.zhihu.com/market/paid_column/1234/section/5678",
            "https://zhuanlan.zhihu.com/p/1",
            "https://www.zhihu.com/question/1/answer/2",
            "https://example.com/x",
        ],
    )
    def test_non_app_urls(self, url: str) -> None:
        assert is_app_only(url) is False


class TestFriendlyHint:
    """friendly_hint() 中文提示。"""

    def test_every_declared_type_has_hint(self) -> None:
        for url_type in URL_TYPES:
            assert friendly_hint(url_type).strip(), f"{url_type} 缺少提示文案"

    @pytest.mark.parametrize("url_type", ["app_column", "app_section"])
    def test_app_hint_contains_story_to_market_suggestion(self, url_type: str) -> None:
        hint = friendly_hint(url_type)
        assert "story.zhihu.com" in hint, "提示应说明原链接形态"
        assert "www.zhihu.com/market/paid_column" in hint, "提示应给出网页版替换地址"
        assert "仅 APP 内阅读" in hint

    def test_unknown_hint_mentions_zhihu(self) -> None:
        assert "知乎" in friendly_hint("unknown")

    def test_section_hint_is_actionable(self) -> None:
        hint = friendly_hint("section")
        assert "章节" in hint

    def test_unregistered_type_fallback(self) -> None:
        hint = friendly_hint("mars_landing")
        assert "mars_landing" in hint
        assert hint.strip()
