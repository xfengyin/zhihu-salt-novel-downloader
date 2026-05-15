"""User-Agent轮换"""

from __future__ import annotations

import random


class UserAgentRotator:
    """User-Agent轮换器"""

    MOBILE_UA_LIST: list[str] = [
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
            "Mobile/15E148 Safari/604.1"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Linux; Android 13; SM-G991B) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Mobile Safari/537.36"
        ),
    ]

    DESKTOP_UA_LIST: list[str] = [
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 "
            "Safari/537.36"
        ),
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
            "Gecko/20100101 Firefox/121.0"
        ),
    ]

    def __init__(
        self,
        use_mobile: bool = True,
    ) -> None:
        """
        初始化User-Agent轮换器

        Args:
            use_mobile: 是否使用移动端User-Agent
        """
        self._use_mobile = use_mobile
        self._ua_list = self.MOBILE_UA_LIST if use_mobile else self.DESKTOP_UA_LIST

    def get_random(self) -> str:
        """获取随机User-Agent"""
        return random.choice(self._ua_list)

    def get_mobile_headers(self) -> dict[str, str]:
        """获取移动端请求头"""
        return {
            "User-Agent": self.get_random(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    def get_desktop_headers(self) -> dict[str, str]:
        """获取桌面端请求头"""
        return {
            "User-Agent": self.get_random(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
