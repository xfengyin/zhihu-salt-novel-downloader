"""URL 类型识别 —— 移植自旧版 plugins/sources/zhihu_salt.py 的 detect_url_type。

识别七种 URL 类型（见 ARCHITECTURE_SPEC §2.8）：
answer / column / section / app_column / app_section / zhuanlan / unknown。

其中 story.zhihu.com（「仅 APP 内阅读」，需知乎移动端私有 mst/xsec 签名）
当前版本无法下载，detect 会返回 app_column/app_section，
friendly_hint 给出 story→market 网页版替换建议。
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

__all__ = ["URL_TYPES", "detect", "is_app_only", "friendly_hint"]

#: detect() 的全部合法返回值（供调用方校验/穷举）。
URL_TYPES: tuple[str, ...] = (
    "answer",
    "column",
    "section",
    "app_column",
    "app_section",
    "zhuanlan",
    "unknown",
)

#: 知乎系域名根：host 等于它或以 ".<它>" 结尾即视为知乎链接。
_ZHIHU_HOST = "zhihu.com"

#: 移动端手稿路径：/manuscript/paid_column/<col_id>[/<sec_id>]（移植旧版 MANUSCRIPT_PATTERN）。
MANUSCRIPT_PATTERN: re.Pattern[str] = re.compile(r"/manuscript/paid_column/(\d+)(?:/(\d+))?")


def _zhihu_host(url: str) -> str:
    """返回小写主机名；非知乎系域名或无法解析时返回空字符串。"""
    if not url:
        return ""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host == _ZHIHU_HOST or host.endswith("." + _ZHIHU_HOST):
        return host
    return ""


def detect(url: str) -> str:
    """检测 URL 类型。

    Args:
        url: 用户提供的链接（可为空串/乱码，一律安全返回 "unknown"）。

    Returns:
        - "answer"      公开回答（https://www.zhihu.com/question/x/answer/y）
        - "column"      盐选专栏目录页（/market/paid_column/<id>），以及兜底按专栏处理的知乎页
        - "section"     盐选单章节（/market/paid_column/<id>/section/<sid>）
        - "app_column"  仅 APP 内阅读的移动端付费专栏（story.zhihu.com，暂不支持）
        - "app_section" 仅 APP 内阅读的移动端单章节（暂不支持）
        - "zhuanlan"    知乎专栏文章（zhuanlan.zhihu.com/p/<id>）
        - "unknown"     非知乎系链接或无法解析
    """
    host = _zhihu_host(url)
    if not host:
        return "unknown"

    try:
        path = urlparse(url).path
    except ValueError:
        return "unknown"

    # story.zhihu.com：移动端签名内容。section 路径不带 /section/ 关键词，
    # 形如 /manuscript/paid_column/<col_id>/<sec_id>（斜杠数 >= 4 判定为章节）。
    if host == "story.zhihu.com" or host.endswith(".story.zhihu.com"):
        if MANUSCRIPT_PATTERN.search(path) and path.count("/") >= 4:
            return "app_section"
        return "app_column"

    # 盐选市场付费
    if "/market/paid_column/" in path:
        return "section" if "/section/" in path else "column"

    # 公开回答
    if "/answer/" in path:
        return "answer"

    # 专栏文章（v5 起从 column 中独立出来，按单篇文章处理）
    if host == "zhuanlan.zhihu.com" or host.endswith(".zhuanlan.zhihu.com"):
        return "zhuanlan"

    # 兜底：其余知乎页面沿用旧版行为，按专栏处理
    return "column"


def is_app_only(url: str) -> bool:
    """是否为「仅 APP 内阅读」类 URL（需 mst/xsec 签名，当前版本无法下载）。"""
    return detect(url) in ("app_column", "app_section")


#: 各类型的中文提示（app_* 含 story→market 替换建议）。
_HINTS: dict[str, str] = {
    "answer": "这是知乎公开回答页，可直接下载该回答的正文。",
    "column": (
        "这是盐选专栏目录页，下载时会先抓取全部章节目录再逐章下载。"
        "需要登录 Cookie（z_c0/d_c0）有效，可先执行 zhihu-downloader login。"
    ),
    "section": "这是盐选单章节链接，仅下载该章节正文；如需整本请提供专栏目录页链接。",
    "app_column": (
        "这是知乎 APP「仅 APP 内阅读」专栏链接（story.zhihu.com），"
        "需要知乎移动端私有签名，当前版本无法直接下载。"
        "替代方法：把链接中的 story.zhihu.com/manuscript/paid_column/<专栏ID> "
        "替换为 www.zhihu.com/market/paid_column/<专栏ID>，"
        "用替换后的网页版链接重新下载即可。"
    ),
    "app_section": (
        "这是知乎 APP「仅 APP 内阅读」单章链接（story.zhihu.com），"
        "需要知乎移动端私有签名，当前版本无法直接下载。"
        "替代方法：把链接中的 story.zhihu.com/manuscript/paid_column/<专栏ID>/<章节ID> "
        "替换为 www.zhihu.com/market/paid_column/<专栏ID>/section/<章节ID>，"
        "用替换后的网页版链接重新下载即可。"
    ),
    "zhuanlan": "这是知乎专栏文章页（zhuanlan.zhihu.com），将按单篇文章下载正文。",
    "unknown": (
        "无法识别该链接（不是知乎系域名或格式有误）。"
        "请提供知乎回答、盐选专栏目录页或章节链接后重试。"
    ),
}


def friendly_hint(url_type: str) -> str:
    """返回指定 URL 类型的中文提示；app_* 类型附带 story→market 替换建议。

    Args:
        url_type: detect() 的返回值。未知类型返回通用兜底提示。
    """
    hint = _HINTS.get(url_type)
    if hint is not None:
        return hint
    return (
        f"未识别的 URL 类型「{url_type}」。请使用知乎回答/盐选专栏/章节链接，"
        "或先执行 zhihu-downloader doctor 检查环境。"
    )
