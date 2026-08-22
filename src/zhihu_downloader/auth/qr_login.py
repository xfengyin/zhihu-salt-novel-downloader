"""知乎扫码登录服务 - 基于 aiohttp 的异步二维码登录。

核心流程（参考 DecryptLogin zhihuScanqr 类，作者 Charles 的皮卡丘）：
    1. POST https://www.zhihu.com/udid 获取 x-udid
    2. POST https://www.zhihu.com/api/v3/account/api/login/qrcode（带 Origin/Referer/x-udid）-> 返回 token
    3. GET  .../qrcode/{token}/image -> 二维码图片字节
    4. 轮询 GET .../qrcode/{token}/scan_info -> status(0等待/1已扫)、error、user_id、cookie
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .cookie_manager import CookieManager

logger = logging.getLogger(__name__)

# 知乎扫码登录相关 URL
UDID_URL = "https://www.zhihu.com/udid"
QRCODE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode"
QRCODE_IMAGE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/image"
SCAN_INFO_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/scan_info"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/86.0.4240.111 Safari/537.36"
)


class QrLoginError(Exception):
    """扫码登录过程中的错误（网络错误、响应异常等）。"""


class ZhihuQrLoginService:
    """知乎扫码登录服务。

    使用持久 aiohttp 会话（复用连接并保留响应 Set-Cookie），
    支持传入代理与超时；所有网络/协议错误统一包装为 :class:`QrLoginError`。
    """

    def __init__(
        self,
        cookie_manager: CookieManager | None = None,
        proxy: str | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> None:
        """
        Args:
            cookie_manager: Cookie 管理器，登录成功后把 cookie 保存到其中。
            proxy: 可选代理地址（如 "http://127.0.0.1:7890"）。
            timeout: 请求超时配置，默认 total=30、connect=10。
        """
        self.cookie_manager = cookie_manager or CookieManager()
        self.proxy = proxy
        self.timeout = timeout or aiohttp.ClientTimeout(total=30, connect=10)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话。"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """关闭底层 aiohttp 会话。"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @staticmethod
    def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
        """构建知乎登录请求头（Origin/Referer 固定为 web 端来源）。"""
        headers: dict[str, str] = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Host": "www.zhihu.com",
            "Origin": "https://www.zhihu.com",
            "Referer": "https://www.zhihu.com/signup?next=%2F",
        }
        if extra:
            headers.update(extra)
        return headers

    async def start(self) -> dict[str, Any]:
        """发起登录：获取 x-udid 与二维码 token。

        Returns:
            至少包含 ``token`` 与 ``image_url``；若知乎返回过期时间则附带
            ``expire_seconds``。

        Raises:
            QrLoginError: 获取 x-udid / token 失败时。
        """
        session = await self._get_session()

        # 1. 获取 x-udid
        try:
            async with session.post(
                UDID_URL, headers=self._headers(), proxy=self.proxy
            ) as resp:
                udid = (await resp.text()).strip()
        except aiohttp.ClientError as e:
            raise QrLoginError(f"获取 x-udid 失败: {e}") from e

        if not udid:
            raise QrLoginError("获取 x-udid 失败: 响应为空")

        # 2. 获取二维码 token
        headers = self._headers({"x-udid": udid})
        try:
            async with session.post(
                QRCODE_URL, headers=headers, proxy=self.proxy
            ) as resp:
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, ValueError) as e:
            raise QrLoginError(f"获取二维码 token 失败: {e}") from e

        if not isinstance(data, dict):
            raise QrLoginError(f"获取二维码 token 失败: 响应异常 {data!r}")

        token = data.get("token")
        if not token:
            raise QrLoginError(f"获取二维码 token 失败: 响应中无 token {data!r}")

        result: dict[str, Any] = {
            "token": token,
            "image_url": f"/api/auth/qrcode/{token}/image",
        }
        expire_seconds = (
            data.get("expires_in")
            or data.get("expire_seconds")
            or data.get("expire_in")
        )
        if expire_seconds is not None:
            result["expire_seconds"] = expire_seconds
        return result

    async def fetch_image(self, token: str) -> bytes:
        """获取二维码图片字节。

        Raises:
            QrLoginError: 请求失败时。
        """
        session = await self._get_session()
        try:
            async with session.get(
                QRCODE_IMAGE_URL.format(token=token),
                headers=self._headers(),
                proxy=self.proxy,
            ) as resp:
                resp.raise_for_status()
                return await resp.read()
        except aiohttp.ClientError as e:
            raise QrLoginError(f"获取二维码图片失败: {e}") from e

    async def poll(self, token: str) -> dict[str, Any]:
        """轮询扫码状态。

        Returns:
            包含 ``status``（waiting/scanned/confirmed/error/expired）、
            ``raw_status``（原始数值状态）、``error``、``user_id``；
            确认成功（``status == "confirmed"``）时额外携带 ``cookie`` 字典，
            并已把 cookie 保存到 :attr:`cookie_manager`。

        Raises:
            QrLoginError: 网络/协议错误时。
        """
        session = await self._get_session()
        try:
            async with session.get(
                SCAN_INFO_URL.format(token=token),
                headers=self._headers(),
                proxy=self.proxy,
            ) as resp:
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, ValueError) as e:
            raise QrLoginError(f"轮询登录状态失败: {e}") from e

        if not isinstance(data, dict):
            raise QrLoginError(f"轮询登录状态返回异常: {data!r}")

        raw_status = data.get("status")
        error = self._normalize_error(data)
        user_id = data.get("user_id") or ""

        result: dict[str, Any] = {
            "raw_status": raw_status,
            "error": error,
            "user_id": str(user_id) if user_id else None,
        }

        if error:
            result["status"] = "error"
            return result

        if user_id:
            cookie = self._extract_cookie(data)
            if cookie:
                self.cookie_manager.load_from_dict(cookie)
                logger.info("扫码登录成功 user_id=%s，已保存 %d 个 cookie", user_id, len(cookie))
            result["status"] = "confirmed"
            result["cookie"] = cookie
            return result

        if raw_status == 1:
            result["status"] = "scanned"
        elif raw_status == 0:
            result["status"] = "waiting"
        else:
            result["status"] = "expired"
        return result

    @staticmethod
    def _normalize_error(data: dict[str, Any]) -> str | None:
        """从响应中提取错误信息并规范化为字符串。"""
        error = data.get("error")
        if not error:
            return None
        if isinstance(error, dict):
            return str(
                error.get("message")
                or error.get("code")
                or error.get("name")
                or error
            )
        return str(error)

    @staticmethod
    def _extract_cookie(data: dict[str, Any]) -> dict[str, str]:
        """从响应中提取 cookie 字典（兼容 dict 与 "k=v; k2=v2" 字符串）。"""
        cookie = data.get("cookie")
        if isinstance(cookie, dict):
            return {str(k): str(v) for k, v in cookie.items() if k and v}
        if isinstance(cookie, str):
            result: dict[str, str] = {}
            for part in cookie.split(";"):
                part = part.strip()
                if "=" in part:
                    key, _, value = part.partition("=")
                    if key and value:
                        result[key] = value
            return result
        return {}
