"""client 测试 - 全部 mock 网络（requests.Session）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from zhihu_downloader.client import (
    QRCODE_IMAGE_URL,
    QRCODE_URL,
    SCAN_INFO_URL,
    UDID_URL,
    ZhihuClient,
    ZhihuError,
)

SECTION_HTML = """
<html><head><meta property="og:title" content="测试章节" /></head>
<body><div class="RichText"><p>正文内容一</p><p>正文内容二</p></div></body>
</html>
"""


class FakeResponse:
    def __init__(self, text="", content=b"", json_data=None, status_code=200):
        self.text = text
        self.content = content
        self._json = json_data
        self.status_code = status_code

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """记录调用并按完整 URL 分发响应的假 requests.Session。"""

    def __init__(self, post_map=None, get_map=None):
        self.headers: dict = {}
        self.cookies: dict = {}
        self.post_map = post_map or {}
        self.get_map = get_map or {}
        self.post_calls: list[tuple[str, dict]] = []
        self.get_calls: list[tuple[str, dict]] = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        resp = self.post_map.get(url)
        if resp is None:
            raise AssertionError(f"no post mock for {url}")
        if isinstance(resp, Exception):
            raise resp
        return resp

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        resp = self.get_map.get(url)
        if resp is None:
            raise AssertionError(f"no get mock for {url}")
        if isinstance(resp, Exception):
            raise resp
        return resp


def make_client(session: FakeSession, cookie_file: Path) -> ZhihuClient:
    client = ZhihuClient(cookie_file=cookie_file)
    client.session = session
    return client


class TestQrLogin:
    def test_login_qr_start(self, tmp_path: Path) -> None:
        session = FakeSession(
            post_map={
                UDID_URL: FakeResponse(text="udid-1"),
                QRCODE_URL: FakeResponse(json_data={"token": "tk-abc"}),
            }
        )
        client = make_client(session, tmp_path / "c.json")
        result = client.login_qr_start()
        assert result["token"] == "tk-abc"
        assert result["image_url"] == QRCODE_IMAGE_URL.format(token="tk-abc")

    def test_login_qr_image(self, tmp_path: Path) -> None:
        session = FakeSession(
            get_map={QRCODE_IMAGE_URL.format(token="tk"): FakeResponse(content=b"\xff\xd8img")}
        )
        client = make_client(session, tmp_path / "c.json")
        assert client.login_qr_image("tk") == b"\xff\xd8img"

    def test_login_qr_poll_waiting(self, tmp_path: Path) -> None:
        session = FakeSession(
            get_map={SCAN_INFO_URL.format(token="tk"): FakeResponse(json_data={"status": 0})}
        )
        client = make_client(session, tmp_path / "c.json")
        result = client.login_qr_poll("tk")
        assert result["status"] == "waiting"
        assert result["user_id"] is None

    def test_login_qr_poll_confirmed_saves_cookie(self, tmp_path: Path) -> None:
        cookie_file = tmp_path / "c.json"
        session = FakeSession(
            get_map={
                SCAN_INFO_URL.format(token="tk"): FakeResponse(
                    json_data={
                        "status": 2,
                        "user_id": "123",
                        "cookie": {"z_c0": "z-token", "zse_ck": "zse-val"},
                    }
                )
            }
        )
        client = make_client(session, cookie_file)
        result = client.login_qr_poll("tk")
        assert result["status"] == "confirmed"
        assert result["user_id"] == "123"
        # 更新了内部字典
        assert client.get_cookies()["z_c0"] == "z-token"
        assert client.get_cookies()["zse_ck"] == "zse-val"
        # 写入了本地文件
        saved = json.loads(cookie_file.read_text(encoding="utf-8"))
        assert saved["z_c0"] == "z-token"

    def test_login_qr_poll_error(self, tmp_path: Path) -> None:
        session = FakeSession(
            get_map={
                SCAN_INFO_URL.format(token="tk"): FakeResponse(
                    json_data={"status": 0, "error": {"message": "二维码已过期"}}
                )
            }
        )
        client = make_client(session, tmp_path / "c.json")
        result = client.login_qr_poll("tk")
        assert result["status"] == "error"
        assert result["error"] == "二维码已过期"


class TestFetch:
    def test_fetch_success_injects_signature(self, tmp_path: Path) -> None:
        session = FakeSession(get_map={"https://www.zhihu.com/api/v4/x": FakeResponse(text="<html>ok</html>")})
        client = make_client(session, tmp_path / "c.json")
        client._cookies["d_c0"] = "ABC123"
        assert client.fetch("https://www.zhihu.com/api/v4/x") == "<html>ok</html>"
        _, kwargs = session.get_calls[0]
        headers = kwargs.get("headers") or {}
        assert headers["x-zse-96"].startswith("2.0_")
        assert headers["x-zse-93"] == "101_3_3.0"
        assert "x-zst-81" in headers

    def test_fetch_non_zhihu_no_signature(self, tmp_path: Path) -> None:
        session = FakeSession(get_map={"https://example.com/x": FakeResponse(text="ok")})
        client = make_client(session, tmp_path / "c.json")
        client._cookies["d_c0"] = "ABC123"
        assert client.fetch("https://example.com/x") == "ok"
        _, kwargs = session.get_calls[0]
        assert kwargs.get("headers") is None

    def test_fetch_403_raises_chinese_error(self, tmp_path: Path) -> None:
        session = FakeSession(get_map={"https://www.zhihu.com/x": FakeResponse(status_code=403)})
        client = make_client(session, tmp_path / "c.json")
        with pytest.raises(ZhihuError, match="反爬"):
            client.fetch("https://www.zhihu.com/x")

    def test_fetch_network_error(self, tmp_path: Path) -> None:
        session = FakeSession(get_map={"https://www.zhihu.com/x": requests.ConnectionError("boom")})
        client = make_client(session, tmp_path / "c.json")
        with pytest.raises(ZhihuError):
            client.fetch("https://www.zhihu.com/x")


class TestLoadCookies:
    def test_load_dict(self, tmp_path: Path) -> None:
        client = make_client(FakeSession(), tmp_path / "c.json")
        client.load_cookies({"z_c0": "tok"})
        assert client.get_cookies()["z_c0"] == "tok"

    def test_load_json_file(self, tmp_path: Path) -> None:
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"d_c0": "d", "z_c0": "z"}), encoding="utf-8")
        client = make_client(FakeSession(), tmp_path / "c2.json")
        client.load_cookies(f)
        assert client.get_cookies()["d_c0"] == "d"
        assert client.get_cookies()["z_c0"] == "z"

    def test_load_netscape_file(self, tmp_path: Path) -> None:
        f = tmp_path / "cookies.txt"
        f.write_text(
            "#HttpOnly_.zhihu.com\tTRUE\t/\tFALSE\t0\tz_c0\ttokval\n"
            ".zhihu.com\tTRUE\t/\tFALSE\t0\tzse_ck\tzseval\n",
            encoding="utf-8",
        )
        client = make_client(FakeSession(), tmp_path / "c2.json")
        client.load_cookies(f)
        assert client.get_cookies()["z_c0"] == "tokval"
        assert client.get_cookies()["zse_ck"] == "zseval"

    def test_load_name_value_file(self, tmp_path: Path) -> None:
        f = tmp_path / "cookies.txt"
        f.write_text("z_c0=tok; zse_ck=zse\n", encoding="utf-8")
        client = make_client(FakeSession(), tmp_path / "c2.json")
        client.load_cookies(f)
        assert client.get_cookies()["z_c0"] == "tok"
        assert client.get_cookies()["zse_ck"] == "zse"


class TestDownload:
    def test_download_section(self, tmp_path: Path) -> None:
        client = make_client(FakeSession(), tmp_path / "c.json")
        client.fetch = MagicMock(return_value=SECTION_HTML)  # type: ignore[method-assign]
        result = client.download(
            "https://www.zhihu.com/market/paid_column/1/section/2",
            fmt="md",
            output_dir=tmp_path,
        )
        assert result["title"] == "测试章节"
        assert len(result["files"]) == 1
        assert Path(result["files"][0]).exists()

    def test_download_column_uses_catalog(self, tmp_path: Path) -> None:
        client = make_client(FakeSession(), tmp_path / "c.json")
        column_html = """
        <html><body>
          <a href="/market/paid_column/1/section/2">一</a>
          <a href="/market/paid_column/1/section/3">二</a>
        </body></html>
        """
        client.fetch = MagicMock(side_effect=[column_html, SECTION_HTML, SECTION_HTML])  # type: ignore[method-assign]
        result = client.download(
            "https://www.zhihu.com/market/paid_column/1",
            fmt="txt",
            output_dir=tmp_path,
        )
        assert len(result["files"]) == 1
        assert Path(result["files"][0]).exists()

    def test_download_column_no_links_raises(self, tmp_path: Path) -> None:
        client = make_client(FakeSession(), tmp_path / "c.json")
        client.fetch = MagicMock(return_value="<html><body>无链接</body></html>")  # type: ignore[method-assign]
        with pytest.raises(ZhihuError, match="章节链接"):
            client.download("https://www.zhihu.com/market/paid_column/1", output_dir=tmp_path)


class TestRateLimit:
    def test_default_rate_limit_is_2(self, tmp_path: Path) -> None:
        client = ZhihuClient(cookie_file=tmp_path / "c.json")
        assert client.rate_limit == 2.0

    def test_throttle_between_fetches(self, tmp_path: Path) -> None:
        session = FakeSession(get_map={"https://www.zhihu.com/x": FakeResponse(text="ok")})
        client = make_client(session, tmp_path / "c.json")
        client.rate_limit = 50  # 0.02s 间隔
        start = time.monotonic()
        client.fetch("https://www.zhihu.com/x")
        client.fetch("https://www.zhihu.com/x")
        assert time.monotonic() - start >= 0.02

    def test_rate_limit_zero_disables_throttle(self, tmp_path: Path) -> None:
        session = FakeSession(get_map={"https://www.zhihu.com/x": FakeResponse(text="ok")})
        client = make_client(session, tmp_path / "c.json")
        client.rate_limit = 0
        start = time.monotonic()
        client.fetch("https://www.zhihu.com/x")
        client.fetch("https://www.zhihu.com/x")
        assert time.monotonic() - start < 0.01

    def test_download_accepts_rate_limit_override(self, tmp_path: Path) -> None:
        client = make_client(FakeSession(), tmp_path / "c.json")
        client.fetch = MagicMock(return_value=SECTION_HTML)  # type: ignore[method-assign]
        client.download(
            "https://www.zhihu.com/market/paid_column/1/section/2",
            output_dir=tmp_path,
            rate_limit=10,
        )
        assert client.rate_limit == 10
