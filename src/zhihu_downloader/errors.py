"""统一异常层级：所有面向用户的错误消息为中文可读。"""

from __future__ import annotations


class SaltError(Exception):
    """所有可预期错误的基类，message 直接展示给用户。"""


class AuthError(SaltError):
    """登录/Cookie 相关错误（未登录、Cookie 过期、扫码失败）。"""


class ZhihuError(SaltError):
    """知乎请求错误（反爬 403/429、404、网络失败、签名失效）。"""


class ParseError(SaltError):
    """HTML 解析失败（找不到标题/正文/目录）。"""


class UnsupportedUrlError(SaltError):
    """URL 类型不支持（如仅 APP 内阅读内容），message 含替代方案提示。"""


class ExportError(SaltError):
    """导出失败。"""


class CheckpointError(SaltError):
    """断点文件损坏/不可写。"""
