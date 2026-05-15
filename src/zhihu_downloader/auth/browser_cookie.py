"""浏览器Cookie自动读取器"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class BrowserCookieFetcher:
    """浏览器Cookie获取器"""

    @staticmethod
    def fetch_zhihu_cookies() -> dict[str, str]:
        """
        从浏览器自动获取知乎Cookie

        Returns:
            Cookie字典，如果未找到返回空字典
        """
        browsers = [
            ("Chrome", BrowserCookieFetcher._get_chrome_cookies),
            ("Firefox", BrowserCookieFetcher._get_firefox_cookies),
            ("Edge", BrowserCookieFetcher._get_edge_cookies),
        ]

        for browser_name, getter in browsers:
            try:
                cookies = getter()
                if cookies:
                    return cookies
            except Exception:
                continue

        return {}

    @staticmethod
    def _get_chrome_cookies() -> dict[str, str]:
        """获取Chrome浏览器Cookie"""
        import json

        cookie_dir = BrowserCookieFetcher._get_chrome_cookie_dir()
        if not cookie_dir:
            return {}

        cookies: dict[str, str] = {}
        for cookie_file in cookie_dir.glob("*.json"):
            try:
                with open(cookie_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for cookie in data:
                        if cookie.get("domain") and ("zhihu" in cookie["domain"]):
                            cookies[cookie["name"]] = cookie["value"]
            except Exception:
                continue

        return cookies

    @staticmethod
    def _get_firefox_cookies() -> dict[str, str]:
        """获取Firefox浏览器Cookie"""
        import sqlite3

        cookie_file = BrowserCookieFetcher._get_firefox_cookie_file()
        if not cookie_file:
            return {}

        cookies: dict[str, str] = {}
        try:
            conn = sqlite3.connect(f"file:{cookie_file}?immutable=1", uri=True)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, value FROM moz_cookies WHERE host LIKE ?",
                ("%zhihu%",)
            )
            for name, value in cursor.fetchall():
                cookies[name] = value
            conn.close()
        except Exception:
            pass

        return cookies

    @staticmethod
    def _get_edge_cookies() -> dict[str, str]:
        """获取Edge浏览器Cookie"""
        return BrowserCookieFetcher._get_chrome_cookies()

    @staticmethod
    def _get_chrome_cookie_dir() -> Path | None:
        """获取Chrome Cookie目录"""
        if sys.platform == "win32":
            app_data = os.environ.get("APPDATA")
            if app_data:
                path = Path(app_data) / "Google" / "Chrome" / "User Data" / "Default" / "Network"
                if path.exists():
                    return path
        elif sys.platform == "darwin":
            home = os.environ.get("HOME")
            if home:
                path = Path(home) / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Network"
                if path.exists():
                    return path
        else:
            home = os.environ.get("HOME")
            if home:
                path = Path(home) / ".config" / "google-chrome" / "Default" / "Network"
                if path.exists():
                    return path
        return None

    @staticmethod
    def _get_firefox_cookie_file() -> Path | None:
        """获取Firefox Cookie文件"""
        if sys.platform == "win32":
            app_data = os.environ.get("APPDATA")
            if app_data:
                path = Path(app_data) / "Mozilla" / "Firefox" / "Profiles"
                if path.exists():
                    for profile in path.iterdir():
                        if profile.is_dir():
                            cookie_file = profile / "cookies.sqlite"
                            if cookie_file.exists():
                                return cookie_file
        elif sys.platform == "darwin":
            home = os.environ.get("HOME")
            if home:
                path = Path(home) / "Library" / "Application Support" / "Firefox" / "Profiles"
                if path.exists():
                    for profile in path.iterdir():
                        if profile.is_dir():
                            cookie_file = profile / "cookies.sqlite"
                            if cookie_file.exists():
                                return cookie_file
        else:
            home = os.environ.get("HOME")
            if home:
                path = Path(home) / ".mozilla" / "firefox"
                if path.exists():
                    for profile in path.iterdir():
                        if profile.is_dir():
                            cookie_file = profile / "cookies.sqlite"
                            if cookie_file.exists():
                                return cookie_file
        return None
