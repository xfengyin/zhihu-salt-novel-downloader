"""书架纯存储层（规格书 §2.13）。

职责：把书架条目（:class:`~zhihu_downloader.types.ShelfBook`）持久化到
``~/.zhihu_downloader/shelf.json``，格式为 ``{"books": [ShelfBook.to_dict()...]}``。

设计约束：

- 纯存储层：**绝不 import engine**；追更组合逻辑（check_new_chapters × shelf.list）
  在 CLI/server 层完成。
- 原子写：先写 ``shelf.json.tmp`` 再 ``os.replace``（规格书 §0 铁律 6）。
- 损坏恢复：shelf.json 不是合法 JSON 或结构不符（顶层不是对象 / books 不是数组）时，
  自动备份为 ``shelf.json.bak`` 并重建空书架，**不崩溃**。
- 无跨实例缓存：每次公开操作都从磁盘重读，保证多 Shelf 实例/多进程间尽量看到最新状态；
  读-改-写用进程内锁串行化。

契约说明：规格书 §2.13 的 ``record_download(result, fmt)`` 无法从
:class:`~zhihu_downloader.types.BookResult` 得知章节 URL 列表（types.py 为定稿契约，
不可增删字段），因此本实现增加第三个参数 ``chapter_urls: list[str] | None``，
由调用方（fetcher/cli/server）传入本次已下载章节 URL（有序）。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..errors import SaltError
from ..types import BookResult, ShelfBook

#: 默认书架文件路径（规格书 §3 用户状态布局）。
DEFAULT_SHELF_FILE = Path.home() / ".zhihu_downloader" / "shelf.json"

__all__ = ["DEFAULT_SHELF_FILE", "Shelf", "book_id_for"]


def book_id_for(url: str) -> str:
    """由专栏 URL 计算稳定的书架 id：``sha1(url)[:12]``。

    Args:
        url: 专栏 market URL。

    Returns:
        12 位十六进制 id。
    """
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    """当前本地时间的 ISO 字符串（秒精度，同格式下可按字典序比较）。"""
    return datetime.now().isoformat(timespec="seconds")


def _updated_key(book: ShelfBook) -> datetime:
    """list() 排序键：解析 updated_at；为空或不可解析时视为最旧（排在最后）。"""
    try:
        dt = datetime.fromisoformat(book.updated_at)
    except (TypeError, ValueError):
        return datetime.min
    if dt.tzinfo is not None:  # 统一去时区，避免 aware/naive 混排抛 TypeError
        dt = dt.replace(tzinfo=None)
    return dt


def _merge_chapter_urls(old: list[str], new: list[str]) -> list[str]:
    """章节 URL 有序合并去重：保留旧顺序，新出现的追加在末尾。"""
    seen: set[str] = set(old)
    merged: list[str] = list(old)
    for url in new:
        if url and url not in seen:
            seen.add(url)
            merged.append(url)
    return merged


class Shelf:
    """书架存储：单个 JSON 文件持久化 :class:`ShelfBook` 条目。

    所有公开方法每次调用都从磁盘重新加载（实例不缓存数据），因此同一进程内
    多个 :class:`Shelf` 实例（或外部进程）写入的内容能被后续读取看到。
    读-改-写操作由实例内 :class:`threading.Lock` 串行化，供 server 多线程安全复用。
    """

    def __init__(self, path: Path | None = None) -> None:
        """绑定书架文件路径，不触碰文件系统（目录与文件均在首次写入时创建）。

        Args:
            path: shelf.json 的位置；为 ``None`` 时使用 :data:`DEFAULT_SHELF_FILE`。
        """
        self.path: Path = Path(path) if path is not None else DEFAULT_SHELF_FILE
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公开 API（规格书 §2.13）
    # ------------------------------------------------------------------

    def add_or_update(self, book: ShelfBook) -> None:
        """按 id 合并写入条目（upsert），并刷新 ``updated_at``。

        合并规则：

        - ``book.id`` 为空时按 ``sha1(url)[:12]`` 自动补全；
        - 已存在同 id 条目 → 逐字段合并，**空字段不覆盖旧值**（防止误清空
          files/chapter_urls），``downloaded_at`` 保留最早值；
        - 不存在 → 直接追加，``downloaded_at`` 为空时补当前时间；
        - 无论新增还是更新，``updated_at`` 一律刷新为当前时间。

        Args:
            book: 待写入的书架条目（就地更新后落盘）。
        """
        if not book.id:
            book.id = book_id_for(book.url)
        now = _now_iso()
        with self._lock:
            books = self._read()
            existing = self._find_by_id(books, book.id)
            if existing is None:
                book.downloaded_at = book.downloaded_at or now
                book.updated_at = now
                books.append(book)
            else:
                self._merge_into(existing, book)
                existing.downloaded_at = existing.downloaded_at or now
                existing.updated_at = now
            self._write(books)

    def remove(self, book_id: str) -> bool:
        """按 id 移除条目（只删记录，不删已导出文件）。

        Args:
            book_id: 书架 id（``sha1(url)[:12]``）。

        Returns:
            实际删除了条目返回 ``True``；id 不存在返回 ``False``。
        """
        with self._lock:
            books = self._read()
            remaining = [b for b in books if b.id != book_id]
            if len(remaining) == len(books):
                return False
            self._write(remaining)
        return True

    def list(self) -> list[ShelfBook]:
        """列出全部条目，按 ``updated_at`` 倒序（最近更新的在前）。

        Returns:
            排序后的条目列表；书架为空（或文件不存在）时返回空列表。
        """
        with self._lock:
            books = self._read()
        books.sort(key=_updated_key, reverse=True)
        return books

    def get(self, book_id_or_url: str) -> ShelfBook | None:
        """按 id 或 URL 查找条目（id 优先；URL 忽略末尾斜杠差异）。

        Args:
            book_id_or_url: 书架 id 或专栏 URL。

        Returns:
            匹配的条目；找不到返回 ``None``。
        """
        key = (book_id_or_url or "").strip()
        if not key:
            return None
        norm = key.rstrip("/")
        with self._lock:
            books = self._read()
        for book in books:
            if book.id == key:
                return book
        for book in books:
            if book.url == key or book.url.rstrip("/") == norm:
                return book
        return None

    def record_download(self, result: BookResult, fmt: str,
                        chapter_urls: list[str] | None = None) -> ShelfBook:
        """下载成功后登记/更新书架条目（由 fetcher/cli/server 在成功路径调用）。

        id 固定为 ``sha1(result.url)[:12]``。已存在条目时做**追更合并**：

        - ``chapter_urls`` 与旧值有序去重合并（旧章节在前，新章节追加）；
        - ``files``/``fmt``/``title`` 用本次结果的非空值覆盖（整本重导出的最新产物）；
        - ``downloaded_at`` 保留最早值，``updated_at`` 刷新为当前时间。

        Args:
            result: 本次下载结果。
            fmt: 本次导出格式（txt | md | epub）。
            chapter_urls: 本次已下载章节 URL（有序）。``BookResult`` 契约中没有该
                信息，故由调用方额外传入；为 ``None`` 时不新增章节（保留旧值）。

        Returns:
            落盘后的书架条目。
        """
        bid = book_id_for(result.url)
        now = _now_iso()
        with self._lock:
            books = self._read()
            existing = self._find_by_id(books, bid)
            if existing is None:
                book = ShelfBook(
                    id=bid,
                    title=result.title,
                    url=result.url,
                    fmt=fmt,
                    files=list(result.files),
                    chapter_urls=list(chapter_urls or []),
                    downloaded_at=now,
                    updated_at=now,
                )
                books.append(book)
            else:
                existing.title = result.title or existing.title
                existing.url = result.url or existing.url
                if fmt:
                    existing.fmt = fmt
                if result.files:
                    existing.files = list(result.files)
                if chapter_urls:
                    existing.chapter_urls = _merge_chapter_urls(
                        existing.chapter_urls, chapter_urls)
                existing.updated_at = now
                book = existing
            self._write(books)
        return book

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _find_by_id(books: list[ShelfBook], book_id: str) -> ShelfBook | None:
        """在列表中按 id 查找条目。"""
        for book in books:
            if book.id == book_id:
                return book
        return None

    @staticmethod
    def _merge_into(target: ShelfBook, source: ShelfBook) -> None:
        """add_or_update 的逐字段合并：source 的非空字段覆盖 target，空字段保留旧值。"""
        if source.title:
            target.title = source.title
        if source.url:
            target.url = source.url
        if source.fmt:
            target.fmt = source.fmt
        if source.files:
            target.files = list(source.files)
        if source.chapter_urls:
            target.chapter_urls = list(source.chapter_urls)
        if source.downloaded_at and not target.downloaded_at:
            target.downloaded_at = source.downloaded_at

    def _read(self) -> list[ShelfBook]:
        """加载书架条目；文件不存在返回空表；损坏则备份 .bak 并重建空书架。"""
        if not self.path.exists():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as e:
            raise SaltError(
                f"无法读取书架文件 {self.path}（{e}），"
                "请检查文件权限或手动删除该文件后重试") from e
        books, corrupt = self._parse(text)
        if corrupt:
            self._backup_corrupt(text)
            return []
        return books

    @staticmethod
    def _parse(text: str) -> tuple[list[ShelfBook], bool]:
        """解析 shelf.json 文本。

        Returns:
            (条目列表, 是否损坏)。损坏 = JSON 语法错误，或顶层不是对象、
            ``books`` 字段不是数组。合法对象中非 dict 的条目会被跳过。
        """
        try:
            data: Any = json.loads(text)
        except json.JSONDecodeError:
            return [], True
        if not isinstance(data, dict):
            return [], True
        raw = data.get("books", [])
        if not isinstance(raw, list):
            return [], True
        books = [ShelfBook.from_dict(item) for item in raw if isinstance(item, dict)]
        return books, False

    def _backup_corrupt(self, text: str) -> None:
        """把损坏文件备份为 ``<name>.bak``（尽力而为，失败也不崩溃）。"""
        bak = self.path.with_name(self.path.name + ".bak")
        try:
            os.replace(self.path, bak)
            return
        except OSError:
            pass
        try:  # 退路：复制内容后删除原文件
            bak.write_text(text, encoding="utf-8")
            self.path.unlink(missing_ok=True)
        except OSError:
            pass  # 备份失败也继续重建空书架，下次保存会覆盖损坏文件

    def _write(self, books: list[ShelfBook]) -> None:
        """原子写 shelf.json：``.tmp`` + ``os.replace``。"""
        data = {"books": [b.to_dict() for b in books]}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            raise SaltError(
                f"书架文件写入失败 {self.path}（{e}），"
                "请检查磁盘空间与目录权限后重试") from e

