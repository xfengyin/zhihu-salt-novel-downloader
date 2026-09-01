"""认证模块：Cookie 存取、扫码登录、浏览器导入、环境诊断。

公共 API（详见 docs/ARCHITECTURE_SPEC.md §2.4-§2.7）：

* cookies —— JSON / Netscape / 原始串三种格式解析，0600 原子落盘，logout；
* qr      —— start / image / poll 三函数（鸭子类型客户端，confirmed 自动落盘）；
* browser —— fetch_zhihu_cookies（可选依赖 browser-cookie3，缺失时中文提示安装）；
* doctor  —— run_checks 诊断清单（区分"Cookie 缺失"与"签名失效"两条排障路径）。
"""

from __future__ import annotations

from . import browser, cookies, doctor, qr
from .browser import fetch_zhihu_cookies, is_available
from .cookies import (
    DEFAULT_COOKIE_FILE,
    KEY_COOKIES,
    load,
    logout,
    parse_content,
    parse_cookie_string,
    save,
)
from .doctor import run_checks
from .qr import image, poll, start

__all__ = [
    "DEFAULT_COOKIE_FILE",
    "KEY_COOKIES",
    "browser",
    "cookies",
    "doctor",
    "fetch_zhihu_cookies",
    "image",
    "is_available",
    "load",
    "logout",
    "parse_content",
    "parse_cookie_string",
    "poll",
    "qr",
    "run_checks",
    "save",
    "start",
]
