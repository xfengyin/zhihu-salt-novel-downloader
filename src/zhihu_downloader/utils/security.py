"""安全工具集

提供 Cookie/Token/URL/路径的脱敏与校验，用于日志输出防泄漏、SSRF 防护、
路径穿越防护。所有函数均为纯函数，便于单元测试。
"""

from __future__ import annotations

import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# 敏感 Cookie / 表单 key 集合（小写比对，大小写不敏感）
SENSITIVE_COOKIE_KEYS: frozenset[str] = frozenset(
    {"z_c0", "d_c0", "_xsrf", "captcha", "token", "password"}
)

# URL query 中需要脱敏的参数名（小写比对）
SENSITIVE_URL_PARAMS: frozenset[str] = frozenset(
    {"token", "key", "password", "passwd", "secret", "access_token", "auth"}
)

# 允许访问的知乎域名白名单，防止 SSRF 到内网或第三方
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {"zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"}
)


def mask_token(token: str) -> str:
    """
    脱敏单个 token：保留前4后4，中间用 *** 代替

    短 token（<=8 字符）全部掩码为 ***，避免泄漏全部内容。

    Args:
        token: 原始 token 字符串

    Returns:
        脱敏后的字符串
    """
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}***{token[-4:]}"


def mask_cookie(cookies: dict[str, str]) -> dict[str, str]:
    """
    脱敏 Cookie 字典，用于日志输出

    敏感 key（z_c0/d_c0/_xsrf/captcha/token/password，大小写不敏感）的值
    只保留前4后4，中间用 *** 代替；其余 key 原样保留。

    Args:
        cookies: 原始 Cookie 字典

    Returns:
        脱敏后的新字典（不修改入参）
    """
    masked: dict[str, str] = {}
    for key, value in cookies.items():
        if key.lower() in SENSITIVE_COOKIE_KEYS:
            masked[key] = mask_token(value)
        else:
            masked[key] = value
    return masked


def sanitize_url(url: str) -> str:
    """
    URL 脱敏：移除 query 中的敏感参数值（替换为 ***）

    保留 URL 结构与参数名，仅对敏感参数的值做掩码，便于日志排查。

    Args:
        url: 原始 URL

    Returns:
        脱敏后的 URL
    """
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.query:
        return url

    safe_pairs: list[tuple[str, str]] = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        if k.lower() in SENSITIVE_URL_PARAMS:
            safe_pairs.append((k, "***"))
        else:
            safe_pairs.append((k, v))

    new_query = urlencode(safe_pairs)
    return urlunparse(parsed._replace(query=new_query))


def validate_url(url: str) -> bool:
    """
    校验 URL 是否合法且指向知乎域，防止 SSRF

    规则：
    1. scheme 必须为 http 或 https
    2. host 必须在 ALLOWED_HOSTS 白名单内（精确匹配，非后缀匹配）
    3. 不允许 IP 字面量、内网域名、其他公网域名

    Args:
        url: 待校验 URL

    Returns:
        True 表示安全可访问
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False

    # 精确匹配白名单，避免 "evil-zhihu.com" / "zhihu.com.evil.com" 绕过
    return host in ALLOWED_HOSTS


def is_safe_path(path: str, base_dir: str) -> bool:
    """
    校验路径不会逃逸出 base_dir，防止路径穿越攻击

    将 path 与 base_dir 都解析为绝对路径后比较前缀，确保最终落点在 base_dir 之内。
    同时拒绝包含 NUL 字节等异常字符的路径。

    Args:
        path: 待校验路径（可为相对或绝对）
        base_dir: 允许的根目录

    Returns:
        True 表示路径安全（位于 base_dir 之内）
    """
    if not path or not base_dir:
        return False
    # NUL 字节在某些系统下可截断路径，必须拒绝
    if "\x00" in path or "\x00" in base_dir:
        return False

    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(os.path.join(base_real, path))

    # 用 os.path.commonpath 严格判断前缀关系，避免字符串前缀误判
    try:
        common = os.path.commonpath([base_real, target_real])
    except ValueError:
        # 跨盘符等无法比较的情况
        return False
    return common == base_real


__all__ = [
    "ALLOWED_HOSTS",
    "SENSITIVE_COOKIE_KEYS",
    "SENSITIVE_URL_PARAMS",
    "is_safe_path",
    "mask_cookie",
    "mask_token",
    "sanitize_url",
    "validate_url",
]
