"""Cookie管理器"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiohttp


class CookieManager:
    """Cookie管理器"""

    def __init__(self) -> None:
        self._cookies: dict[str, str] = {}
        self._token: str | None = None

    def load_from_file(self, cookie_file: str | Path) -> None:
        """
        从JSON文件加载Cookie

        Args:
            cookie_file: Cookie文件路径
        """
        path = Path(cookie_file)
        if not path.exists():
            msg = f"Cookie文件不存在: {path}"
            raise FileNotFoundError(msg)

        with open(path, "r", encoding="utf-8") as f:
            cookies_data: list[dict[str, Any]] = json.load(f)

        for item in cookies_data:
            name = item.get("name")
            value = item.get("value")
            if name and value:
                self._cookies[name] = value

                if name == "z_c0":
                    self._token = value

    def load_from_dict(self, cookies: dict[str, str]) -> None:
        """
        从字典加载Cookie

        Args:
            cookies: Cookie字典
        """
        self._cookies.update(cookies)

        if "z_c0" in cookies:
            self._token = cookies["z_c0"]

    def set_token(self, token: str) -> None:
        """
        设置z_c0 token

        Args:
            token: z_c0 token值
        """
        self._token = token
        self._cookies["z_c0"] = token

    def get_cookies(self) -> dict[str, str]:
        """
        获取Cookie字典

        Returns:
            Cookie字典
        """
        return self._cookies.copy()

    def get_token(self) -> str | None:
        """获取z_c0 token"""
        return self._token

    def to_aiohttp_cookies(self) -> aiohttp.CookieJar:
        """
        转换为aiohttp CookieJar

        Returns:
            aiohttp CookieJar对象
        """
        jar = aiohttp.CookieJar()
        for name, value in self._cookies.items():
            jar.update_cookies({name: value})
        return jar

    def clear(self) -> None:
        """清除所有Cookie"""
        self._cookies.clear()
        self._token = None
