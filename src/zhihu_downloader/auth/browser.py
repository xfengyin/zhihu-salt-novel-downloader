"""从本机浏览器导入知乎 Cookie（可选依赖 browser-cookie3）。

移植自旧版 src/auth/browser_cookie.py（Chrome/Firefox/Edge），但改用
browser-cookie3 统一读取各浏览器加密后的 Cookie 库（旧实现手解 sqlite/json
在 Chrome 83+ 的 AES 加密下已不可用）。

依赖策略（架构规格 §0 铁律 1）：browser-cookie3 **不是**运行时依赖，
import 必须 try/except 降级——缺失时抛 AuthError 并给出可安装的 extras 提示。

用法：

    from zhihu_downloader.auth import browser, cookies
    jar = browser.fetch_zhihu_cookies()      # {"z_c0": "...", "d_c0": "..."}
    cookies.save(jar)                        # 0600 落盘

或一步到位：browser.fetch_zhihu_cookies(save_to=path)。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..errors import AuthError
from . import cookies

__all__ = [
    "DEFAULT_BROWSERS",
    "SUPPORTED_BROWSERS",
    "ZHIHU_DOMAIN",
    "fetch_zhihu_cookies",
    "is_available",
    "load_backend",
]

#: 需要匹配的 Cookie 域（zhihu.com 及其子域）
ZHIHU_DOMAIN = "zhihu.com"

#: browser-cookie3 提供的读取器：(函数名, 中文名)
SUPPORTED_BROWSERS: tuple[tuple[str, str], ...] = (
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("edge", "Edge"),
    ("chromium", "Chromium"),
    ("brave", "Brave"),
)

#: 默认尝试顺序（与规格 §2.6 一致：Chrome -> Firefox -> Edge）
DEFAULT_BROWSERS: tuple[str, ...] = ("chrome", "firefox", "edge")

_INSTALL_HINT = (
    "未安装 browser-cookie3，无法从浏览器导入 Cookie。"
    "请执行 pip install \"zhihu-salt-novel-downloader[browser]\" 后重试，"
    "或改用扫码登录：zhihu-downloader login"
)


def load_backend() -> Any:
    """导入并返回 browser_cookie3 模块。

    Returns:
        browser_cookie3 模块对象。

    Raises:
        AuthError: 未安装该可选依赖（消息含 pip 安装命令与扫码登录替代方案）。
    """
    try:
        import browser_cookie3  # noqa: PLC0415 - 可选依赖，必须惰性导入
    except ImportError as e:
        raise AuthError(_INSTALL_HINT) from e
    return browser_cookie3


def is_available() -> bool:
    """当前环境是否具备浏览器导入能力（browser-cookie3 已安装）。"""
    try:
        load_backend()
    except AuthError:
        return False
    return True


def _labels(names: Iterable[str]) -> list[tuple[str, str]]:
    """把浏览器名列表映射为 (函数名, 中文名)；未知名字直接报错。"""
    table = dict(SUPPORTED_BROWSERS)
    out: list[tuple[str, str]] = []
    for name in names:
        key = str(name).strip().lower()
        if not key:
            continue
        if key not in table:
            raise AuthError(
                f"不支持的浏览器类型：{name}。可选值："
                + "、".join(label for _, label in SUPPORTED_BROWSERS)
            )
        out.append((key, table[key]))
    if not out:
        raise AuthError("浏览器列表为空：请至少指定一个来源（Chrome / Firefox / Edge）")
    return out


def _domain_matches(domain: str) -> bool:
    """判断 Cookie 域是否属于知乎（zhihu.com 及其子域）。

    浏览器导出的域常带前导点（.zhihu.com）或 #HttpOnly_ 标记；必须按后缀精确匹配，
    不能用子串包含——否则 notzhihu.com.evil.cn 这类仿冒域会被误收。
    """
    text = str(domain or "").strip().lower()
    if text.startswith("#httponly_"):
        text = text[len("#httponly_"):]
    text = text.lstrip(".")
    if not text:
        return False
    return text == ZHIHU_DOMAIN or text.endswith("." + ZHIHU_DOMAIN)


def _pick_zhihu(cookies_obj: Any) -> dict[str, str]:
    """从 cookiejar / cookie 列表中挑出知乎域的 name -> value。"""
    result: dict[str, str] = {}
    for cookie in cookies_obj or []:
        name = getattr(cookie, "name", None)
        value = getattr(cookie, "value", None)
        if not name or value is None:
            continue
        if not _domain_matches(str(getattr(cookie, "domain", "") or "")):
            continue
        result[str(name)] = str(value)
    return result


def _read_one(backend: Any, func_name: str, label: str) -> tuple[dict[str, str], str | None]:
    """读取单个浏览器的知乎 Cookie。

    Returns:
        (cookie 字典, 失败原因)。失败原因为 None 表示读取成功（字典可能为空）。
    """
    getter = getattr(backend, func_name, None)
    if not callable(getter):
        return {}, f"{label}: 当前 browser-cookie3 版本不支持该浏览器"
    try:
        try:
            jar = getter(domain_name=ZHIHU_DOMAIN)
        except TypeError:
            # 极老版本没有 domain_name 关键字参数，退化为全量读取后自行过滤
            jar = getter()
    except Exception as e:  # noqa: BLE001 - 浏览器锁库/权限/解密失败都要降级为可读提示
        return {}, f"{label}: {type(e).__name__}: {e}"
    return _pick_zhihu(jar), None


def fetch_zhihu_cookies(
    browsers: Iterable[str] | None = None,
    *,
    save_to: str | Path | None = None,
) -> dict[str, str]:
    """按顺序尝试从浏览器读取知乎 Cookie，返回第一个非空结果。

    Args:
        browsers: 浏览器名（chrome/firefox/edge/chromium/brave）；None 表示按
            DEFAULT_BROWSERS（Chrome -> Firefox -> Edge）顺序尝试。
        save_to: 非 None 时把结果经 auth.cookies.save 落盘（0600）到该路径。

    Returns:
        Cookie 字典（登录态通常应含 z_c0 / zse_ck / d_c0）。

    Raises:
        AuthError: 未安装 browser-cookie3；浏览器名不支持；或所有指定浏览器都没
            读到知乎 Cookie（消息逐个列出失败原因，并提示先登录知乎或改用扫码登录）。
    """
    backend = load_backend()
    targets = _labels(browsers or DEFAULT_BROWSERS)

    notes: list[str] = []
    found: dict[str, str] | None = None
    for func_name, label in targets:
        cookies_map, err = _read_one(backend, func_name, label)
        if err:
            notes.append(err)
            continue
        if cookies_map:
            found = cookies_map
            break
        notes.append(f"{label}: 未读到 {ZHIHU_DOMAIN} 的 Cookie")

    if found is None:
        raise AuthError(
            "未能从浏览器导入知乎 Cookie（" + "；".join(notes) + "）。"
            "请先在该浏览器中登录 https://www.zhihu.com 并完全退出浏览器后重试；"
            "也可以改用扫码登录：zhihu-downloader login"
        )

    if save_to is not None:
        cookies.save(found, save_to)
    return found
