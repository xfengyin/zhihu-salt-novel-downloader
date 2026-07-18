"""源插件测试 - 重点覆盖 issue #2 修复"""

from __future__ import annotations

import pytest

from zhihu_downloader.plugins.sources.zhihu_salt import ZhihuSaltSource


class TestZhihuSaltSourceCanHandle:
    """can_handle 应识别所有知乎系域名"""

    @pytest.fixture
    def plugin(self) -> ZhihuSaltSource:
        return ZhihuSaltSource()

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.zhihu.com/question/123/answer/456",
            "https://zhihu.com/question/123/answer/456",
            "https://zhuanlan.zhihu.com/p/123",
            "https://www.zhihu.com/market/paid_column/123",
            "https://www.zhihu.com/market/paid_column/123/section/456",
            # issue #2 关键场景
            "https://story.zhihu.com/manuscript/paid_column/1738171776255660032",
            "https://story.zhihu.com/manuscript/paid_column/1738171776255660032/1822560690113748992",
        ],
    )
    def test_can_handle_zhihu_urls(self, plugin: ZhihuSaltSource, url: str) -> None:
        assert plugin.can_handle(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/foo",
            "https://baidu.com/answer/123",
            "https://notzhihu.com/question/1",
            "",
        ],
    )
    def test_cannot_handle_other_urls(
        self, plugin: ZhihuSaltSource, url: str
    ) -> None:
        assert plugin.can_handle(url) is False


class TestZhihuSaltSourceDetectUrlType:
    """detect_url_type 应正确分类 URL"""

    @pytest.fixture
    def plugin(self) -> ZhihuSaltSource:
        return ZhihuSaltSource()

    def test_answer_url(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.detect_url_type("https://www.zhihu.com/question/1/answer/2")
            == "answer"
        )

    def test_zhuanlan_url(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.detect_url_type("https://zhuanlan.zhihu.com/p/123")
            == "column"
        )

    def test_paid_column_book(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.detect_url_type(
                "https://www.zhihu.com/market/paid_column/1738171776255660032"
            )
            == "column"
        )

    def test_paid_column_section(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.detect_url_type(
                "https://www.zhihu.com/market/paid_column/1864671270639165440/section/2037497376336819335"
            )
            == "section"
        )

    def test_app_column_issue2(self, plugin: ZhihuSaltSource) -> None:
        """issue #2 关键场景：story.zhihu.com 移动端"""
        assert (
            plugin.detect_url_type(
                "https://story.zhihu.com/manuscript/paid_column/1738171776255660032"
            )
            == "app_column"
        )

    def test_app_section_issue2(self, plugin: ZhihuSaltSource) -> None:
        """issue #2 关键场景：移动端单章节"""
        assert (
            plugin.detect_url_type(
                "https://story.zhihu.com/manuscript/paid_column/1738171776255660032/1822560690113748992"
            )
            == "app_section"
        )

    def test_unknown_url(self, plugin: ZhihuSaltSource) -> None:
        assert plugin.detect_url_type("https://example.com/foo") == "unknown"


class TestZhihuSaltSourceIsAppOnly:
    """is_app_only 应正确识别「仅 APP 内阅读」类 URL"""

    @pytest.fixture
    def plugin(self) -> ZhihuSaltSource:
        return ZhihuSaltSource()

    def test_app_column_is_app_only(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.is_app_only(
                "https://story.zhihu.com/manuscript/paid_column/123"
            )
            is True
        )

    def test_app_section_is_app_only(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.is_app_only(
                "https://story.zhihu.com/manuscript/paid_column/123/456"
            )
            is True
        )

    def test_market_column_not_app_only(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.is_app_only(
                "https://www.zhihu.com/market/paid_column/123"
            )
            is False
        )

    def test_answer_not_app_only(self, plugin: ZhihuSaltSource) -> None:
        assert (
            plugin.is_app_only("https://www.zhihu.com/question/1/answer/2")
            is False
        )


class TestDownloadServiceUrlHint:
    """DownloadService 应发出 URL 类型提示"""

    @pytest.fixture
    def service(self):  # type: ignore[no-untyped-def]
        from zhihu_downloader.services.download_service import DownloadService

        return DownloadService()

    def test_app_only_emits_warning(self, service) -> None:  # type: ignore[no-untyped-def]
        """issue #2：传入 APP 端 URL 应触发明确提示"""
        events = service._emit_url_hint(
            "https://story.zhihu.com/manuscript/paid_column/1738171776255660032/1822560690113748992"
        )
        # 至少 3 条提示：检测提示 + 原因说明 + 建议方案
        assert len(events) >= 3
        messages = " | ".join(e.message for e in events)
        assert "仅 APP 内阅读" in messages
        assert "mst" in messages or "签名" in messages

    def test_section_emits_hint(self, service) -> None:  # type: ignore[no-untyped-def]
        """section 类 URL 给出说明"""
        events = service._emit_url_hint(
            "https://www.zhihu.com/market/paid_column/123/section/456"
        )
        assert len(events) >= 1
        assert "单章节" in events[0].message

    def test_column_emits_hint(self, service) -> None:  # type: ignore[no-untyped-def]
        """column 类 URL 给出说明"""
        events = service._emit_url_hint(
            "https://www.zhihu.com/market/paid_column/123"
        )
        assert len(events) >= 1
        assert "Cookie" in events[0].message or "z_c0" in events[0].message

    def test_unknown_url_emits_hint(self, service) -> None:  # type: ignore[no-untyped-def]
        events = service._emit_url_hint("https://example.com/foo")
        assert len(events) == 1
        assert "知乎" in events[0].message
