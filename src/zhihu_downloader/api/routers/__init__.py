"""API 路由聚合 - 导出各业务路由器供 app.py 注册"""

from zhihu_downloader.api.routers.download import router as download_router
from zhihu_downloader.api.routers.shelf import router as shelf_router

__all__ = ["download_router", "shelf_router"]
