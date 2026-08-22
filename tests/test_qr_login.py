"""知乎扫码登录服务测试"""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.auth.qr_login import QrLoginError, ZhihuQrLoginService

UDID_URL = "https://www.zhihu.com/udid"
QRCODE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode"
IMAGE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/tk-xyz/image"
SCAN_INFO_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/tk-xyz/scan_info"


class FakeResponse:
    """模拟 aiohttp 响应（同时作为异步上下文管理器）。"""

    def __init__(
        self,
        json_data: Any = None,
        content: bytes = b"",
        text: str = "",
    ) -> None:
        self._json = json_data
        self._content = content
        self._text = text

    async def json(self, **kwargs: Any) -> Any:
        return self._json

    async def read(self) -> bytes:
        return self._content

    async def text(self, **kwargs: Any) -> str:
        return self._text

    def raise_for_status(self) -> None:
        return None

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False


class HttpErrorResponse(FakeResponse):
    """模拟 HTTP 非 2xx 响应，raise_for_status 抛出 ClientError。"""

    def raise_for_status(self) -> None:
        raise aiohttp.ClientError("HTTP 500")


class BrokenJsonResponse(FakeResponse):
    """模拟返回非法 JSON 的响应。"""

    async def json(self, **kwargs: Any) -> Any:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class FakeSession:
    """模拟 aiohttp.ClientSession，按完整 URL 精确分发响应。"""

    def __init__(
        self,
        post_map: dict[str, Any] | None = None,
        get_map: dict[str, Any] | None = None,
    ) -> None:
        self._post = post_map or {}
        self._get = get_map or {}
        self.closed = False

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._dispatch(self._post, url)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self._dispatch(self._get, url)

    @staticmethod
    def _dispatch(mapping: dict[str, Any], url: str) -> FakeResponse:
        if url not in mapping:
            raise AssertionError(f"测试未注册该 URL 的 mock: {url}")
        resp = mapping[url]
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def close(self) -> None:
        self.closed = True


class ErrorSession:
    """所有请求均抛出网络错误的会话。"""

    def __init__(self) -> None:
        self.closed = False

    def post(self, url: str, **kwargs: Any) -> None:
        raise aiohttp.ClientError("connection refused")

    def get(self, url: str, **kwargs: Any) -> None:
        raise aiohttp.ClientError("connection refused")

    async def close(self) -> None:
        self.closed = True


def make_service(
    session: Any, cookie_manager: CookieManager | None = None
) -> ZhihuQrLoginService:
    """构造使用注入 session 的服务，避免真实网络。"""
    svc = ZhihuQrLoginService(cookie_manager=cookie_manager)
    svc._session = session
    return svc


class TestStart:
    @pytest.mark.asyncio
    async def test_start_returns_token(self) -> None:
        session = FakeSession(
            post_map={
                UDID_URL: FakeResponse(text="udid-abc123"),
                QRCODE_URL: FakeResponse(json_data={"token": "tk-xyz", "expires_in": 180}),
            }
        )
        svc = make_service(session)
        result = await svc.start()
        assert result["token"] == "tk-xyz"
        assert result["image_url"] == "/api/auth/qrcode/tk-xyz/image"
        assert result["expire_seconds"] == 180

    @pytest.mark.asyncio
    async def test_start_missing_token_raises(self) -> None:
        session = FakeSession(
            post_map={
                UDID_URL: FakeResponse(text="udid-abc123"),
                QRCODE_URL: FakeResponse(json_data={"no_token": True}),
            }
        )
        svc = make_service(session)
        with pytest.raises(QrLoginError):
            await svc.start()

    @pytest.mark.asyncio
    async def test_start_empty_udid_raises(self) -> None:
        session = FakeSession(post_map={UDID_URL: FakeResponse(text="")})
        svc = make_service(session)
        with pytest.raises(QrLoginError):
            await svc.start()


class TestFetchImage:
    @pytest.mark.asyncio
    async def test_fetch_image_returns_bytes(self) -> None:
        png = b"\x89PNG\r\n\x1a\nfake-qr"
        session = FakeSession(get_map={IMAGE_URL: FakeResponse(content=png)})
        svc = make_service(session)
        assert await svc.fetch_image("tk-xyz") == png

    @pytest.mark.asyncio
    async def test_fetch_image_http_error_raises(self) -> None:
        session = FakeSession(get_map={IMAGE_URL: HttpErrorResponse(content=b"")})
        svc = make_service(session)
        with pytest.raises(QrLoginError):
            await svc.fetch_image("tk-xyz")


class TestPoll:
    @pytest.mark.asyncio
    async def test_poll_waiting(self) -> None:
        session = FakeSession(get_map={SCAN_INFO_URL: FakeResponse(json_data={"status": 0})})
        svc = make_service(session)
        result = await svc.poll("tk-xyz")
        assert result["status"] == "waiting"
        assert result["raw_status"] == 0
        assert result["user_id"] is None

    @pytest.mark.asyncio
    async def test_poll_scanned(self) -> None:
        session = FakeSession(get_map={SCAN_INFO_URL: FakeResponse(json_data={"status": 1})})
        svc = make_service(session)
        result = await svc.poll("tk-xyz")
        assert result["status"] == "scanned"
        assert result["raw_status"] == 1

    @pytest.mark.asyncio
    async def test_poll_expired(self) -> None:
        session = FakeSession(get_map={SCAN_INFO_URL: FakeResponse(json_data={"status": 2})})
        svc = make_service(session)
        result = await svc.poll("tk-xyz")
        assert result["status"] == "expired"
        assert result["raw_status"] == 2

    @pytest.mark.asyncio
    async def test_poll_error(self) -> None:
        session = FakeSession(
            get_map={
                SCAN_INFO_URL: FakeResponse(
                    json_data={"status": 0, "error": {"code": 100, "message": "二维码已过期"}}
                )
            }
        )
        svc = make_service(session)
        result = await svc.poll("tk-xyz")
        assert result["status"] == "error"
        assert result["error"] == "二维码已过期"

    @pytest.mark.asyncio
    async def test_poll_confirmed_saves_cookie_dict(self) -> None:
        cm = CookieManager()
        session = FakeSession(
            get_map={
                SCAN_INFO_URL: FakeResponse(
                    json_data={
                        "status": 2,
                        "user_id": "12345",
                        "cookie": {"z_c0": "z-token-abc", "zse_ck": "zse-value"},
                    }
                )
            }
        )
        svc = make_service(session, cookie_manager=cm)
        result = await svc.poll("tk-xyz")
        assert result["status"] == "confirmed"
        assert result["user_id"] == "12345"
        assert result["cookie"]["z_c0"] == "z-token-abc"
        # 已保存到 CookieManager
        assert cm.get_cookies()["z_c0"] == "z-token-abc"
        assert cm.get_cookies()["zse_ck"] == "zse-value"
        assert cm.get_token() == "z-token-abc"

    @pytest.mark.asyncio
    async def test_poll_confirmed_saves_cookie_string(self) -> None:
        cm = CookieManager()
        session = FakeSession(
            get_map={
                SCAN_INFO_URL: FakeResponse(
                    json_data={
                        "user_id": "9",
                        "cookie": "z_c0=AAA; zse_ck=BBB",
                    }
                )
            }
        )
        svc = make_service(session, cookie_manager=cm)
        result = await svc.poll("tk-xyz")
        assert result["status"] == "confirmed"
        assert cm.get_cookies()["z_c0"] == "AAA"
        assert cm.get_cookies()["zse_ck"] == "BBB"


class TestErrors:
    @pytest.mark.asyncio
    async def test_network_error_raises(self) -> None:
        svc = make_service(ErrorSession())
        with pytest.raises(QrLoginError):
            await svc.start()
        with pytest.raises(QrLoginError):
            await svc.fetch_image("tk-xyz")
        with pytest.raises(QrLoginError):
            await svc.poll("tk-xyz")

    @pytest.mark.asyncio
    async def test_json_parse_error_raises(self) -> None:
        session = FakeSession(
            post_map={
                UDID_URL: FakeResponse(text="udid-abc123"),
                QRCODE_URL: BrokenJsonResponse(),
            }
        )
        svc = make_service(session)
        with pytest.raises(QrLoginError):
            await svc.start()

    @pytest.mark.asyncio
    async def test_non_dict_response_raises(self) -> None:
        session = FakeSession(
            post_map={
                UDID_URL: FakeResponse(text="udid-abc123"),
                QRCODE_URL: FakeResponse(json_data=["not", "a", "dict"]),
            }
        )
        svc = make_service(session)
        with pytest.raises(QrLoginError):
            await svc.start()


class TestClose:
    @pytest.mark.asyncio
    async def test_close_closes_session(self) -> None:
        session = FakeSession()
        svc = make_service(session)
        await svc.close()
        assert svc._session is None
