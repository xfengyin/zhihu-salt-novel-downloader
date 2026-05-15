"""认证模块"""

from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.auth.browser_cookie import BrowserCookieFetcher

__all__ = ["CookieManager", "BrowserCookieFetcher"]
