"""书架存储层测试（规格书 §2.13）：全部离线，仅使用 tmp_path 临时目录。

覆盖：增删改查 / 按 id 合并 / updated_at 倒序 / record_download 追更合并 /
损坏 JSON 备份恢复 / 原子写（.tmp + os.replace）/ 中文持久化 / 错误消息。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from zhihu_downloader.errors import SaltError
from zhihu_downloader.shelf import DEFAULT_SHELF_FILE, Shelf, book_id_for
from zhihu_downloader.shelf import shelf as shelf_mod
from zhihu_downloader.types import BookResult, ShelfBook

URL = "https://www.zhihu.com/market/pub_column/1234567890"
URL2 = "https://www.zhihu.com/market/pub_column/9876543210"


class FakeClock:
    """可控时钟：每次调用前进 60 秒，返回与实现相同格式的秒精度 ISO 字符串。"""

    def __init__(self, start: datetime | None = None) -> None:
        self.t = start or datetime(2025, 1, 1, 12, 0, 0)

    def __call__(self) -> str:
        s = self.t.isoformat(timespec="seconds")
        self.t += timedelta(seconds=60)
        return s


@pytest.fixture()
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """把 shelf 模块的时间源替换为可控时钟。"""
    fake = FakeClock()
    monkeypatch.setattr(shelf_mod, "_now_iso", fake)
    return fake


def make_book(url: str = URL, title: str = "测试书", **overrides) -> ShelfBook:
    """构造书架条目（id 默认按契约取 sha1(url)[:12]）。"""
    fields: dict = {
        "id": book_id_for(url),
        "title": title,
        "url": url,
        "fmt": "md",
        "files": ["测试书.md"],
        "chapter_urls": ["https://zhuanlan.zhihu.com/p/1"],
    }
    fields.update(overrides)
    return ShelfBook(**fields)


def make_result(url: str = URL, title: str = "测试书",
                files: list[str] | None = None) -> BookResult:
    """构造下载结果。"""
    return BookResult(title=title, url=url, chapters=2,
                      files=files if files is not None else ["测试书.md"])


def disk_title(path: Path) -> str:
    """辅助：从磁盘原始 JSON 里取第一本书的标题。"""
    return json.loads(path.read_text(encoding="utf-8"))["books"][0]["title"]


# ----------------------------------------------------------------------
# 基本增删改查
# ----------------------------------------------------------------------

def test_empty_shelf_without_file(tmp_path: Path) -> None:
    """文件不存在时：list 为空、get 返回 None、remove 返回 False，且不创建文件。"""
    shelf = Shelf(tmp_path / "shelf.json")
    assert shelf.list() == []
    assert shelf.get("nope") is None
    assert shelf.remove("nope") is False
    assert not (tmp_path / "shelf.json").exists()


def test_add_and_get_roundtrip(tmp_path: Path, clock: FakeClock) -> None:
    """add_or_update 落盘为 {"books": [...]}；get 支持 id 与 url（含末尾斜杠）。"""
    path = tmp_path / "shelf.json"
    shelf = Shelf(path)
    book = make_book()
    shelf.add_or_update(book)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"books"} and len(data["books"]) == 1
    assert data["books"][0]["id"] == book.id
    assert data["books"][0]["downloaded_at"] == "2025-01-01T12:00:00"
    assert data["books"][0]["updated_at"] == "2025-01-01T12:00:00"

    assert shelf.get(book.id) is not None
    assert shelf.get(URL) is not None
    assert shelf.get(URL + "/") is not None
    assert shelf.get(URL2) is None
    assert shelf.get("") is None


def test_add_autofills_id_from_url(tmp_path: Path) -> None:
    """id 为空时按 sha1(url)[:12] 自动补全。"""
    shelf = Shelf(tmp_path / "shelf.json")
    book = make_book(id="")
    shelf.add_or_update(book)
    expected = hashlib.sha1(URL.encode("utf-8")).hexdigest()[:12]
    assert book.id == expected == book_id_for(URL)
    assert shelf.get(expected) is not None


def test_add_or_update_merges_by_id(tmp_path: Path, clock: FakeClock) -> None:
    """同 id 二次写入：非空字段覆盖、空字段不清库、downloaded_at 保留、updated_at 刷新。"""
    shelf = Shelf(tmp_path / "shelf.json")
    first = make_book(title="第一版书名", files=["old.md"],
                      chapter_urls=["https://p/1", "https://p/2"])
    shelf.add_or_update(first)
    original_downloaded_at = first.downloaded_at

    second = make_book(title="第二版书名", fmt="epub",
                       files=[], chapter_urls=[])  # 空 files/chapters 不应清空旧值
    shelf.add_or_update(second)

    books = shelf.list()
    assert len(books) == 1
    merged = books[0]
    assert merged.title == "第二版书名"
    assert merged.fmt == "epub"
    assert merged.files == ["old.md"]
    assert merged.chapter_urls == ["https://p/1", "https://p/2"]
    assert merged.downloaded_at == original_downloaded_at
    assert merged.updated_at == "2025-01-01T12:01:00"  # 时钟前进一格


def test_remove(tmp_path: Path, clock: FakeClock) -> None:
    """remove 按 id 删除并返回 True；重复删除/未知 id 返回 False。"""
    shelf = Shelf(tmp_path / "shelf.json")
    shelf.add_or_update(make_book())
    shelf.add_or_update(make_book(url=URL2, title="另一本"))

    assert shelf.remove(book_id_for(URL)) is True
    assert shelf.get(URL) is None
    assert len(shelf.list()) == 1
    assert shelf.remove(book_id_for(URL)) is False
    assert shelf.remove("unknown-id") is False


def test_list_sorted_by_updated_at_desc(tmp_path: Path, clock: FakeClock) -> None:
    """list 按 updated_at 倒序；更新旧条目会把它顶到最前。"""
    shelf = Shelf(tmp_path / "shelf.json")
    shelf.add_or_update(make_book(url=URL, title="A"))
    shelf.add_or_update(make_book(url=URL2, title="B"))
    shelf.add_or_update(make_book(url=URL + "3", title="C"))
    assert [b.title for b in shelf.list()] == ["C", "B", "A"]

    shelf.add_or_update(make_book(url=URL, title="A2"))  # 更新 A
    assert [b.title for b in shelf.list()] == ["A2", "C", "B"]


def test_list_handles_bad_updated_at(tmp_path: Path) -> None:
    """updated_at 为空/非法的条目排在最后，且不抛异常。"""
    path = tmp_path / "shelf.json"
    path.write_text(json.dumps({"books": [
        {"id": "x1", "title": "坏时间", "url": "u1", "fmt": "md",
         "updated_at": "not-a-time"},
        {"id": "x2", "title": "好时间", "url": "u2", "fmt": "md",
         "updated_at": "2024-06-01T00:00:00"},
        {"id": "x3", "title": "空时间", "url": "u3", "fmt": "md"},
    ]}), encoding="utf-8")
    titles = [b.title for b in Shelf(path).list()]
    assert titles[0] == "好时间"
    assert set(titles[1:]) == {"坏时间", "空时间"}


def test_two_instances_share_state(tmp_path: Path) -> None:
    """实例不缓存：另一个 Shelf 实例写入后立即可见。"""
    path = tmp_path / "shelf.json"
    a, b = Shelf(path), Shelf(path)
    a.add_or_update(make_book())
    assert b.get(URL) is not None
    b.remove(book_id_for(URL))
    assert a.list() == []


# ----------------------------------------------------------------------
# record_download
# ----------------------------------------------------------------------

def test_record_download_creates_entry(tmp_path: Path, clock: FakeClock) -> None:
    """首次登记：id=sha1(url)[:12]，files/fmt/chapter_urls/时间戳齐全。"""
    shelf = Shelf(tmp_path / "shelf.json")
    chapters = ["https://zhuanlan.zhihu.com/p/1", "https://zhuanlan.zhihu.com/p/2"]
    book = shelf.record_download(make_result(), "md", chapters)

    assert book.id == hashlib.sha1(URL.encode("utf-8")).hexdigest()[:12]
    assert book.title == "测试书" and book.url == URL and book.fmt == "md"
    assert book.files == ["测试书.md"]
    assert book.chapter_urls == chapters
    assert book.downloaded_at == book.updated_at == "2025-01-01T12:00:00"
    assert shelf.get(book.id) is not None and shelf.get(URL) is not None


def test_record_download_update_merges_chapters(tmp_path: Path, clock: FakeClock) -> None:
    """追更：chapter_urls 有序去重合并，files/fmt 覆盖，downloaded_at 保留最早值。"""
    shelf = Shelf(tmp_path / "shelf.json")
    first = shelf.record_download(make_result(), "md", ["p1", "p2"])
    original_downloaded_at = first.downloaded_at

    second = shelf.record_download(
        make_result(title="新标题", files=["全书.epub"]),
        "epub", ["p2", "p3"])  # p2 重复应去重，p3 追加

    assert second.id == first.id
    assert second.chapter_urls == ["p1", "p2", "p3"]
    assert second.files == ["全书.epub"]
    assert second.fmt == "epub"
    assert second.title == "新标题"
    assert second.downloaded_at == original_downloaded_at
    assert second.updated_at == "2025-01-01T12:01:00"
    assert len(shelf.list()) == 1


def test_record_download_without_chapter_urls(tmp_path: Path) -> None:
    """chapter_urls 省略时：新建为空列表，更新保留旧章节。"""
    shelf = Shelf(tmp_path / "shelf.json")
    book = shelf.record_download(make_result(), "md")
    assert book.chapter_urls == []

    shelf.record_download(make_result(), "md", ["p1"])
    again = shelf.record_download(make_result(), "md")  # 不传章节
    assert again.chapter_urls == ["p1"]


# ----------------------------------------------------------------------
# 损坏恢复
# ----------------------------------------------------------------------

def test_corrupt_json_backed_up_and_rebuilt(tmp_path: Path) -> None:
    """非法 JSON：备份为 shelf.json.bak、重建空书架、可继续写入，不崩溃。"""
    path = tmp_path / "shelf.json"
    garbage = b"{ not valid json [[[ "
    path.write_bytes(garbage)

    shelf = Shelf(path)
    assert shelf.list() == []
    bak = tmp_path / "shelf.json.bak"
    assert bak.read_bytes() == garbage
    assert not path.exists()  # 损坏文件已移走

    shelf.add_or_update(make_book())  # 重建后可正常写入
    assert len(shelf.list()) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["books"][0]["url"] == URL
    assert bak.read_bytes() == garbage  # 备份不被覆盖


def test_wrong_shape_treated_as_corrupt(tmp_path: Path) -> None:
    """合法 JSON 但顶层不是对象（如 v4 遗留列表）：同样备份重建。"""
    path = tmp_path / "shelf.json"
    path.write_text(json.dumps([{"url": URL}]), encoding="utf-8")
    shelf = Shelf(path)
    assert shelf.list() == []
    assert (tmp_path / "shelf.json.bak").exists()


def test_empty_object_is_valid(tmp_path: Path) -> None:
    """空对象视为空书架（结构合法），不触发备份。"""
    path = tmp_path / "shelf.json"
    path.write_text("{}", encoding="utf-8")
    assert Shelf(path).list() == []
    assert not (tmp_path / "shelf.json.bak").exists()


def test_non_dict_entries_skipped(tmp_path: Path) -> None:
    """books 数组里的非 dict 条目被跳过，其余条目保留。"""
    path = tmp_path / "shelf.json"
    path.write_text(json.dumps({"books": ["junk", 42, {"id": "ok1", "url": "u"}]}),
                    encoding="utf-8")
    books = Shelf(path).list()
    assert [b.id for b in books] == ["ok1"]
    assert books[0].fmt == "md"  # from_dict 默认值兜底


# ----------------------------------------------------------------------
# 原子写与 IO 错误
# ----------------------------------------------------------------------

def test_atomic_write_uses_tmp_then_replace(tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """保存必须先写 .tmp 再 os.replace，且不留临时文件。"""
    calls: list[tuple[str, str]] = []
    real_replace = shelf_mod.os.replace

    def spy(src, dst):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(shelf_mod.os, "replace", spy)
    path = tmp_path / "shelf.json"
    Shelf(path).add_or_update(make_book())

    assert calls == [(str(path) + ".tmp", str(path))]
    assert not (tmp_path / "shelf.json.tmp").exists()
    assert disk_title(path) == "测试书"


def test_write_failure_raises_actionable_salt_error(tmp_path: Path) -> None:
    """无法写入（父路径是文件）时抛中文可操作的 SaltError。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    shelf = Shelf(blocker / "shelf.json")
    with pytest.raises(SaltError) as exc:
        shelf.add_or_update(make_book())
    assert "书架文件写入失败" in str(exc.value)


def test_unicode_preserved(tmp_path: Path) -> None:
    """中文标题以原文（非 unicode 转义）落盘并可读回。"""
    path = tmp_path / "shelf.json"
    Shelf(path).add_or_update(
        make_book(title="盐选·长夜难明", files=["长夜难明.md"]))
    raw = path.read_text(encoding="utf-8")
    assert "盐选·长夜难明" in raw
    assert disk_title(path) == "盐选·长夜难明"


def test_default_path_constant() -> None:
    """默认路径为 ~/.zhihu_downloader/shelf.json；构造 Shelf() 不产生 IO。"""
    assert DEFAULT_SHELF_FILE.name == "shelf.json"
    assert DEFAULT_SHELF_FILE.parent.name == ".zhihu_downloader"
    assert Shelf().path == DEFAULT_SHELF_FILE
