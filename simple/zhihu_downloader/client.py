"""ZhihuClient - 基于 requests.Session 的同步知乎客户端。

职责：扫码登录、Cookie 管理、带 x-zse-96 签名的请求、下载。
刻意保持同步与简单：易读、易 mock、易维护。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import __version__
from .exporters import export
from .parser import parse_article, parse_page_title, parse_section_links
from .signature import XZSE_93_VERSION, generate_zhihu_sign

logger = logging.getLogger(__name__)

UDID_URL = "https://www.zhihu.com/udid"
QRCODE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode"
QRCODE_IMAGE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/image"
SCAN_INFO_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/scan_info"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/86.0.4240.111 Safari/537.36 zhihu-salt/{__version__}"
)

DEFAULT_COOKIE_FILE = Path.home() / ".zhihu_downloader" / "cookies.json"


class ZhihuError(Exception):
    """知乎请求/登录错误（中文可读信息）。"""


class ZhihuClient:
    """知乎客户端（同步）。"""

    def __init__(
        self,
        cookie_file: str | Path | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.timeout = timeout
        self.cookie_file = Path(cookie_file) if cookie_file else DEFAULT_COOKIE_FILE
        self._cookies: dict[str, str] = {}
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        if self.cookie_file.exists():
            self.load_cookies(self.cookie_file)

    # ------------------------------------------------------------------
    # Cookie 管理
    # ------------------------------------------------------------------

    def get_cookies(self) -> dict[str, str]:
        """返回已加载的 Cookie 字典副本。"""
        return dict(self._cookies)

    def save_cookies(self, cookie_file: str | Path | None = None) -> Path:
        """把当前 Cookie 保存为 JSON 文件，返回保存路径。"""
        path = Path(cookie_file) if cookie_file else self.cookie_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_cookies(self, source: str | Path | dict[str, str]) -> None:
        """加载 Cookie。

        ``source`` 支持三种形式：
        - ``dict[str, str]``：直接使用；
        - JSON 文件路径（内容为 ``{"name": "value"}``）；
        - 文本文件路径（Netscape ``name\\tvalue`` 或 ``name=value`` 行）。

        加载后同时更新内部字典与 requests 会话。
        """
        if isinstance(source, dict):
            cookies = dict(source)
        else:
            path = Path(source).expanduser()
            if not path.exists():
                raise ZhihuError(f"Cookie 文件不存在: {path}")
            text = path.read_text(encoding="utf-8")
            cookies = self._parse_cookie_content(text)

        self._cookies.update(cookies)
        self.session.cookies.update(cookies)

    @staticmethod
    def _parse_cookie_content(text: str) -> dict[str, str]:
        """解析 Cookie 文本内容（JSON 或 Netscape/name=value 行）。"""
        stripped = text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                data = json.loads(stripped)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if k and v}
            except json.JSONDecodeError:
                pass

        cookies: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Chrome/Firefox 导出的 HttpOnly cookie 域名带 "#HttpOnly_" 前缀
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]
            if line.startswith("#"):
                continue
            # Netscape cookies.txt：domain flag path secure expiry name value
            parts = line.split("\t")
            if len(parts) >= 7:
                if parts[5] and parts[6]:
                    cookies[parts[5]] = parts[6]
                continue
            # name=value; name2=value2
            for chunk in line.split(";"):
                chunk = chunk.strip()
                if "=" in chunk:
                    key, _, value = chunk.partition("=")
                    if key:
                        cookies[key] = value
        return cookies

    # ------------------------------------------------------------------
    # 扫码登录
    # ------------------------------------------------------------------

    def _qr_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Origin": "https://www.zhihu.com",
            "Referer": "https://www.zhihu.com/signup?next=%2F",
        }
        if extra:
            headers.update(extra)
        return headers

    def login_qr_start(self) -> dict[str, str]:
        """发起扫码登录：获取 x-udid 与二维码 token。"""
        try:
            resp = self.session.post(UDID_URL, headers=self._qr_headers(), timeout=self.timeout)
            udid = resp.text.strip()
        except requests.RequestException as e:
            raise ZhihuError(f"获取 x-udid 失败: {e}") from e
        if not udid:
            raise ZhihuError("获取 x-udid 失败: 响应为空")

        try:
            resp = self.session.post(
                QRCODE_URL,
                headers=self._qr_headers({"x-udid": udid}),
                timeout=self.timeout,
            )
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise ZhihuError(f"获取二维码 token 失败: {e}") from e

        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise ZhihuError(f"获取二维码 token 失败: 响应无 token {data!r}")
        return {
            "token": token,
            "image_url": QRCODE_IMAGE_URL.format(token=token),
        }

    def login_qr_image(self, token: str) -> bytes:
        """获取二维码图片字节。"""
        try:
            resp = self.session.get(
                QRCODE_IMAGE_URL.format(token=token),
                headers=self._qr_headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            raise ZhihuError(f"获取二维码图片失败: {e}") from e

    def login_qr_poll(self, token: str) -> dict:
        """轮询扫码状态。

        Returns:
            {"status": "waiting"|"scanned"|"confirmed"|"error"|"expired",
             "user_id": str|None, "error": str|None}
            confirmed 时会把响应中的 cookie 保存到本地文件与会话。
        """
        try:
            resp = self.session.get(
                SCAN_INFO_URL.format(token=token),
                headers=self._qr_headers(),
                timeout=self.timeout,
            )
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise ZhihuError(f"轮询登录状态失败: {e}") from e

        if not isinstance(data, dict):
            raise ZhihuError(f"轮询登录状态返回异常: {data!r}")

        raw_status = data.get("status")
        error = self._normalize_error(data)
        user_id = data.get("user_id") or ""

        if error:
            return {"status": "error", "user_id": None, "error": error}

        if user_id:
            cookie = self._extract_cookie(data)
            if cookie:
                self._cookies.update(cookie)
                self.session.cookies.update(cookie)
                self.save_cookies()
            return {"status": "confirmed", "user_id": str(user_id), "error": None}

        if raw_status == 1:
            return {"status": "scanned", "user_id": None, "error": None}
        if raw_status == 0:
            return {"status": "waiting", "user_id": None, "error": None}
        return {"status": "expired", "user_id": None, "error": None}

    @staticmethod
    def _normalize_error(data: dict) -> str | None:
        error = data.get("error")
        if not error:
            return None
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)
        return str(error)

    @staticmethod
    def _extract_cookie(data: dict) -> dict[str, str]:
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

    # ------------------------------------------------------------------
    # 请求与下载
    # ------------------------------------------------------------------

    @staticmethod
    def _is_zhihu_url(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "zhihu.com" or host.endswith(".zhihu.com")

    def _sign_headers(self, url: str) -> dict[str, str]:
        """若为知乎域名且含 d_c0，则返回 x-zse-96/x-zst-81/x-zse-93 头。"""
        if not self._is_zhihu_url(url) or "d_c0" not in self._cookies:
            return {}
        sig = generate_zhihu_sign(url, self._cookies)
        if not sig:
            return {}
        return {
            "x-zse-96": sig["x-zse-96"],
            "x-zst-81": sig["x-zst-81"],
            "x-zse-93": XZSE_93_VERSION,
        }

    def fetch(self, url: str) -> str:
        """GET 请求并返回文本，自动注入签名头，403/429 抛出中文异常。"""
        headers = self._sign_headers(url)
        try:
            resp = self.session.get(url, headers=headers or None, timeout=self.timeout)
        except requests.RequestException as e:
            raise ZhihuError(f"请求失败 {url}: {e}") from e

        if resp.status_code in (403, 429):
            raise ZhihuError(
                f"请求被知乎反爬拦截（HTTP {resp.status_code}），"
                "请更新 Cookie（z_c0/zse_ck）后重试"
            )
        if resp.status_code == 404:
            raise ZhihuError(f"内容不存在（HTTP 404）: {url}")
        if resp.status_code != 200:
            raise ZhihuError(f"请求失败（HTTP {resp.status_code}）: {url}")
        return resp.text

    def download(self, url: str, fmt: str = "md", output_dir: str | Path = ".") -> dict:
        """下载盐选章节或专栏并导出。

        - section URL（含 ``/section/``）：只下载该章节。
        - column URL：先解析目录，再逐章下载合并导出。

        Returns:
            {"title": str, "files": [str, ...]}
        """
        if "/section/" in url:
            html = self.fetch(url)
            article = parse_article(html, url)
            title = article["title"]
            articles = [article]
        else:
            html = self.fetch(url)
            links = parse_section_links(html, url)
            if not links:
                raise ZhihuError(f"未在专栏页解析到任何章节链接: {url}")
            column_title = parse_page_title(html)
            articles = []
            for link in links:
                chapter_html = self.fetch(link)
                articles.append(parse_article(chapter_html, link))
            title = column_title or (articles[0]["title"] if articles else "zhihu-column")

        files = export(title, articles, fmt, output_dir)
        return {"title": title, "files": files}
