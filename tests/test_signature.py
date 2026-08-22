"""x-zse-96 签名模块与下载器接入测试"""

from unittest.mock import patch

from zhihu_downloader.core.downloader import AsyncDownloader
from zhihu_downloader.core.zhihu_signature import (
    XZSE_93_VERSION,
    generate_zhihu_sign,
)

D_C0 = "ABCDEFabcdef0123456789abcdef0123456789abcdef0123456789"
ZHIHU_URL = "https://www.zhihu.com/api/v4/articles/123?include=data%5B*%5D"


class TestGenerateZhihuSign:
    """签名生成函数测试"""

    def test_no_d_c0_returns_empty(self) -> None:
        """无 d_c0 时返回空字典"""
        assert generate_zhihu_sign(ZHIHU_URL, {}) == {}
        assert generate_zhihu_sign(ZHIHU_URL, {"z_c0": "xyz"}) == {}
        assert generate_zhihu_sign(ZHIHU_URL, {"d_c0": ""}) == {}

    def test_with_d_c0_returns_signed_headers(self) -> None:
        """有 d_c0 时返回带 2.0_ 前缀且长度合理的 x-zse-96"""
        headers = generate_zhihu_sign(ZHIHU_URL, {"d_c0": D_C0})
        assert "x-zse-96" in headers
        assert "x-zst-81" in headers
        assert headers["x-zse-96"].startswith("2.0_")
        # "2.0_" + 64 个编码字符 = 68
        assert len(headers["x-zse-96"]) == 68
        assert headers["x-zst-81"].startswith("3_2.0")

    def test_signature_is_reproducible_when_random_patched(self) -> None:
        """patch random.randint 后签名可复现"""
        with patch(
            "zhihu_downloader.core.zhihu_signature.random.randint", return_value=42
        ):
            first = generate_zhihu_sign(ZHIHU_URL, {"d_c0": D_C0})
            second = generate_zhihu_sign(ZHIHU_URL, {"d_c0": D_C0})
        assert first == second

    def test_signature_depends_on_url_and_query(self) -> None:
        """签名基于实际请求 URL（含 query string）"""
        with patch(
            "zhihu_downloader.core.zhihu_signature.random.randint", return_value=42
        ):
            base = generate_zhihu_sign(
                "https://www.zhihu.com/api/v4/articles/123", {"d_c0": D_C0}
            )
            with_query = generate_zhihu_sign(
                "https://www.zhihu.com/api/v4/articles/123?include=data",
                {"d_c0": D_C0},
            )
            other = generate_zhihu_sign(
                "https://www.zhihu.com/api/v4/articles/456", {"d_c0": D_C0}
            )
        assert base["x-zse-96"] != with_query["x-zse-96"]
        assert base["x-zse-96"] != other["x-zse-96"]
        # x-zst-81 为固定常量，不随 URL 变化
        assert base["x-zst-81"] == with_query["x-zst-81"] == other["x-zst-81"]

    def test_different_d_c0_produce_different_signature(self) -> None:
        """不同 d_c0 产生不同签名"""
        with patch(
            "zhihu_downloader.core.zhihu_signature.random.randint", return_value=42
        ):
            a = generate_zhihu_sign(ZHIHU_URL, {"d_c0": D_C0})
            b = generate_zhihu_sign(ZHIHU_URL, {"d_c0": D_C0 + "0"})
        assert a["x-zse-96"] != b["x-zse-96"]


class TestDownloaderSignatureIntegration:
    """下载器签名头接入测试"""

    def _downloader(self) -> AsyncDownloader:
        return AsyncDownloader(cookies={"d_c0": D_C0})

    def test_zhihu_url_with_d_c0_adds_signature_headers(self) -> None:
        """知乎系请求且含 d_c0 时自动追加签名头"""
        downloader = self._downloader()
        headers = downloader._build_headers(None, ZHIHU_URL)
        assert headers["x-zse-96"].startswith("2.0_")
        assert headers["x-zst-81"].startswith("3_2.0")
        assert headers["x-zse-93"] == XZSE_93_VERSION

    def test_non_zhihu_url_has_no_signature_headers(self) -> None:
        """非知乎系请求不追加签名头"""
        downloader = self._downloader()
        headers = downloader._build_headers(None, "https://example.com/api")
        assert "x-zse-96" not in headers
        assert "x-zst-81" not in headers
        assert "x-zse-93" not in headers

    def test_zhihu_url_without_d_c0_has_no_signature_headers(self) -> None:
        """知乎系请求但无 d_c0 时不追加签名头"""
        downloader = AsyncDownloader(cookies={"z_c0": "xyz"})
        headers = downloader._build_headers(None, ZHIHU_URL)
        assert "x-zse-96" not in headers
        assert "x-zst-81" not in headers
        assert "x-zse-93" not in headers

    def test_custom_headers_can_override_signature(self) -> None:
        """用户自定义 headers 可覆盖自动签名头"""
        downloader = self._downloader()
        headers = downloader._build_headers({"x-zse-96": "2.0_custom"}, ZHIHU_URL)
        assert headers["x-zse-96"] == "2.0_custom"
        # 其余签名头仍保留
        assert headers["x-zst-81"].startswith("3_2.0")
        assert headers["x-zse-93"] == XZSE_93_VERSION

    def test_zhihu_subdomain_is_detected(self) -> None:
        """zhihu.com 子域（api/zhuanlan）也能识别为知乎系"""
        downloader = self._downloader()
        for host in (
            "https://www.zhihu.com/x",
            "https://api.zhihu.com/x",
            "https://zhuanlan.zhihu.com/x",
        ):
            assert downloader._is_zhihu_url(host), host
        assert not downloader._is_zhihu_url("https://notzhihu.com/x")
        assert not downloader._is_zhihu_url("https://zhihu.com.evil.com/x")

    def test_signature_build_returns_empty_when_generation_fails(self) -> None:
        """当签名生成函数返回空 dict 时不注入任何签名头"""
        downloader = self._downloader()
        with patch(
            "zhihu_downloader.core.downloader.generate_zhihu_sign", return_value={}
        ):
            assert downloader._build_signature_headers(ZHIHU_URL) == {}
