"""书架管理器"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


class ShelfManager:
    """书架管理器"""

    def __init__(self, shelf_file: str | None = None) -> None:
        """
        初始化书架管理器

        Args:
            shelf_file: 书架数据文件路径
        """
        if shelf_file:
            self._shelf_file = Path(shelf_file)
        else:
            self._shelf_file = self._get_default_shelf_file()

        self._shelf_file.parent.mkdir(parents=True, exist_ok=True)
        self._books: list[dict[str, Any]] = self._load_shelf()

    def _get_default_shelf_file(self) -> Path:
        """获取默认书架文件路径"""
        if os.name == "nt":
            app_data = os.environ.get("APPDATA")
            if app_data:
                return Path(app_data) / "zhihu-downloader" / "shelf.json"
        else:
            home = os.environ.get("HOME")
            if home:
                return Path(home) / ".config" / "zhihu-downloader" / "shelf.json"
        return Path(".") / "shelf.json"

    def _load_shelf(self) -> list[dict[str, Any]]:
        """加载书架数据"""
        if not self._shelf_file.exists():
            return []
        try:
            with open(self._shelf_file, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_shelf(self) -> None:
        """保存书架数据"""
        with open(self._shelf_file, "w", encoding="utf-8") as f:
            json.dump(self._books, f, ensure_ascii=False, indent=2)

    def list_books(self) -> list[dict[str, Any]]:
        """
        获取书架中的所有书籍

        Returns:
            书籍列表
        """
        return self._books

    def get_book(self, url: str) -> dict[str, Any] | None:
        """
        根据URL获取书籍信息

        Args:
            url: 书籍URL

        Returns:
            书籍信息，如果不存在返回None
        """
        for book in self._books:
            if book.get("url") == url:
                return book
        return None

    def add_book(self, url: str, info: dict[str, Any] | None = None) -> None:
        """
        添加书籍到书架

        Args:
            url: 书籍URL
            info: 书籍详细信息（可选）
        """
        existing = self.get_book(url)
        if existing:
            if info:
                existing.update(info)
                existing["last_update"] = datetime.now().isoformat()
        else:
            book: dict[str, Any] = {
                "url": url,
                "added_at": datetime.now().isoformat(),
                "last_update": datetime.now().isoformat(),
                "completed": False,
            }
            if info:
                book.update(info)
            self._books.append(book)

        self._save_shelf()

    def remove_book(self, url_or_title: str) -> None:
        """
        从书架移除书籍

        Args:
            url_or_title: 书籍URL或标题
        """
        self._books = [
            book for book in self._books
            if book.get("url") != url_or_title and book.get("title") != url_or_title
        ]
        self._save_shelf()

    def update_book(self, url: str, updates: dict[str, Any]) -> None:
        """
        更新书籍信息

        Args:
            url: 书籍URL
            updates: 更新的字段
        """
        book = self.get_book(url)
        if book:
            book.update(updates)
            book["last_update"] = datetime.now().isoformat()
            self._save_shelf()

    def mark_completed(self, url: str) -> None:
        """
        标记书籍为已完成

        Args:
            url: 书籍URL
        """
        self.update_book(url, {"completed": True})

    def clean_cache(self) -> None:
        """清理书架缓存（重置书架）"""
        self._books = []
        self._save_shelf()

    def get_statistics(self) -> dict[str, int]:
        """
        获取书架统计信息

        Returns:
            统计字典，包含总数和已完成数
        """
        total = len(self._books)
        completed = sum(1 for book in self._books if book.get("completed"))
        return {
            "total": total,
            "completed": completed,
            "in_progress": total - completed,
        }

    def get_shelf_file_path(self) -> Path:
        """获取书架文件路径"""
        return self._shelf_file
