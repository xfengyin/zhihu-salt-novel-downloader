"""书架服务 - 封装书架管理业务

对 ShelfManager 做薄封装，提供面向 API/CLI 的统一接口，
并补充异常处理与日志，便于上层调用。
"""

from __future__ import annotations

import logging
from typing import Any

from zhihu_downloader.shelf.shelf_manager import ShelfManager

logger = logging.getLogger(__name__)


class ShelfService:
    """书架服务"""

    def __init__(self, shelf: ShelfManager | None = None) -> None:
        """
        Args:
            shelf: 书架管理器，为 None 时使用默认路径
        """
        self._shelf = shelf or ShelfManager()

    def list_books(self) -> list[dict[str, Any]]:
        """列出书架所有书籍"""
        return self._shelf.list_books()

    def get_book(self, url: str) -> dict[str, Any] | None:
        """根据 URL 获取书籍信息"""
        return self._shelf.get_book(url)

    def add_book(self, url: str, info: dict[str, Any] | None = None) -> dict[str, Any]:
        """添加书籍到书架

        Returns:
            操作结果字典
        """
        try:
            self._shelf.add_book(url, info)
            logger.info("已添加到书架: %s", url)
            return {"success": True, "message": f"已添加: {url}"}
        except Exception as e:
            logger.exception("添加书架失败: %s", url)
            return {"success": False, "message": f"添加失败: {e}"}

    def remove_book(self, url_or_title: str) -> dict[str, Any]:
        """从书架移除书籍"""
        try:
            self._shelf.remove_book(url_or_title)
            logger.info("已从书架移除: %s", url_or_title)
            return {"success": True, "message": f"已移除: {url_or_title}"}
        except Exception as e:
            logger.exception("移除书架失败: %s", url_or_title)
            return {"success": False, "message": f"移除失败: {e}"}

    def mark_completed(self, url: str) -> dict[str, Any]:
        """标记书籍为已完成"""
        try:
            self._shelf.mark_completed(url)
            return {"success": True, "message": f"已标记完成: {url}"}
        except Exception as e:
            logger.exception("标记完成失败: %s", url)
            return {"success": False, "message": f"标记失败: {e}"}

    def clean_shelf(self) -> dict[str, Any]:
        """清空书架"""
        return self.clean_cache()

    def clean_cache(self) -> dict[str, Any]:
        """清空书架"""
        try:
            self._shelf.clean_cache()
            logger.info("已清空书架缓存")
            return {"success": True, "message": "已清空书架"}
        except Exception as e:
            logger.exception("清空书架失败")
            return {"success": False, "message": f"清空失败: {e}"}

    def get_statistics(self) -> dict[str, int]:
        """获取书架统计信息"""
        return self._shelf.get_statistics()

    def get_shelf_file_path(self) -> str:
        """获取书架文件路径"""
        return str(self._shelf.get_shelf_file_path())
