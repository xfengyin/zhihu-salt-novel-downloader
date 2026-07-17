"""知乎盐选小说下载器 - 企业级异步并发下载工具"""

__version__ = "3.0.0"
__author__ = "xfengyin"
__license__ = "MIT"

from zhihu_downloader.core.downloader import AsyncDownloader
from zhihu_downloader.exporters.epub_exporter import EpubExporter
from zhihu_downloader.parsers.article_parser import ArticleParser
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.shelf_service import ShelfService

__all__ = [
    "ArticleParser",
    "AsyncDownloader",
    "DownloadService",
    "EpubExporter",
    "ShelfService",
]
