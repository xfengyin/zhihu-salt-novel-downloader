"""依赖注入 - 为路由提供 Service/Config/TaskManager 单例

所有提供者从 app.state 获取单例实例，确保：
- ShelfService 与 DownloadService 共享同一个 ShelfManager（内存一致）
- TaskManager 全局唯一，跨请求可见
- Config 全局唯一，配置统一
"""

from __future__ import annotations

import logging

from fastapi import Request

from zhihu_downloader.api.schemas import DownloadRequest
from zhihu_downloader.api.tasks import TaskManager
from zhihu_downloader.auth.browser_cookie import BrowserCookieFetcher
from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.shelf_service import ShelfService
from zhihu_downloader.utils.config import Config

logger = logging.getLogger(__name__)


def get_config(request: Request) -> Config:
    """从应用状态获取全局配置单例"""
    return request.app.state.config


def get_task_manager(request: Request) -> TaskManager:
    """从应用状态获取任务管理器单例"""
    return request.app.state.task_manager


def get_download_service(request: Request) -> DownloadService:
    """从应用状态获取下载服务单例"""
    return request.app.state.download_service


def get_shelf_service(request: Request) -> ShelfService:
    """从应用状态获取书架服务单例"""
    return request.app.state.shelf_service


def build_cookie_manager(request: DownloadRequest) -> CookieManager | None:
    """根据下载请求装配 CookieManager

    优先级：cookie_file > auto_cookie(浏览器自动读取) > token。
    若三者均未提供有效凭证，返回 None 表示匿名访问。

    Args:
        request: 下载请求 schema

    Returns:
        装配好的 CookieManager，或 None

    Raises:
        FileNotFoundError: cookie_file 指定的文件不存在
    """
    cm = CookieManager()

    if request.cookie_file:
        # 显式指定 cookie 文件，文件不存在时抛异常由调用方处理
        cm.load_from_file(request.cookie_file)
    elif request.auto_cookie:
        # 尽力从浏览器读取，失败则降级为匿名
        cookies = BrowserCookieFetcher.fetch_zhihu_cookies()
        if cookies:
            cm.load_from_dict(cookies)
        else:
            logger.warning("自动读取浏览器 Cookie 失败，将匿名访问")

    if request.token:
        cm.set_token(request.token)

    # 无任何凭证时返回 None，service 层按匿名处理
    if not cm.get_cookies():
        return None

    return cm
