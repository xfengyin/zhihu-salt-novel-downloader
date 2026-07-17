"""API 路由聚合 - 导出各业务路由器供 app.py 注册"""

from zhihu_downloader.api.routers.api_keys import router as api_keys_router
from zhihu_downloader.api.routers.auth import router as auth_router
from zhihu_downloader.api.routers.books import router as books_router
from zhihu_downloader.api.routers.download import router as download_router
from zhihu_downloader.api.routers.plugins import router as plugins_router
from zhihu_downloader.api.routers.shelf import router as shelf_router
from zhihu_downloader.api.routers.users import router as users_router

__all__ = [
    "api_keys_router",
    "auth_router",
    "books_router",
    "download_router",
    "plugins_router",
    "shelf_router",
    "users_router",
]
