"""CheckpointStore 单元测试（全离线，tmp_path 沙箱目录）。

覆盖规格 §4 对 test_checkpoint.py 的要求：原子写 / 损坏恢复 / 续传跳过。
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import pytest

from zhihu_downloader.engine.checkpoint import CheckpointStore, key_hash
from zhihu_downloader.errors import CheckpointError
from zhihu_downloader.types import Article, Block

BOOK_KEY = "https://www.zhihu.com/market/paid_column/123"
CH_URL = "https://www.zhihu.com/market/paid_column/123/section/456"


def make_article(title: str = "第一章", url: str = CH_URL) -> Article:
    """构造带结构块的文章样本。"""
    return Article(
        title=title,
        url=url,
        chapter_type="normal",
        blocks=[
            Block(kind="h2", text="小节"),
            Block(kind="p", text="正文段落。"),
            Block(kind="li", text="列表项"),
            Block(kind="img", src="https://pic.img/1.png", alt="插图"),
        ],
    )


def sha16(raw: str) -> str:
    """期望的短哈希（与实现独立算一遍，钉死命名规则）。"""
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------
# 状态文件命名与基本读写
# ----------------------------------------------------------------------

def test_state_path_uses_sha1_prefix(tmp_path: Path) -> None:
    """状态文件 = state_dir/<sha1(book_key)[:16]>.json。"""
    store = CheckpointStore(tmp_path / ".zhihu_state", BOOK_KEY)
    assert store.state_path == tmp_path / ".zhihu_state" / f"{sha16(BOOK_KEY)}.json"
    assert store.state_path.name != f"{BOOK_KEY}.json"
    assert key_hash(BOOK_KEY) == sha16(BOOK_KEY)


def test_load_returns_empty_dict_when_missing(tmp_path: Path) -> None:
    """状态不存在 → {}（首次下载）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    assert store.load() == {}
    assert store.get_done_urls() == set()
    assert store.get_article(CH_URL) is None


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """save/load 往返一致，且自动创建目录。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    payload = {"title": "书", "total": 3, "done_urls": [CH_URL]}
    store.save(payload)
    assert store.load() == payload


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    """原子写：落盘后目录里没有 .tmp 残留，也没有半截 JSON。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    for i in range(20):
        store.save({"n": i, "done_urls": [f"{CH_URL}?i={i}"]})
    assert store.load()["n"] == 19
    assert list(store.state_path.parent.glob("*.tmp")) == []
    assert json.loads(store.state_path.read_text(encoding="utf-8"))["n"] == 19


def test_state_file_is_private_0600(tmp_path: Path) -> None:
    """断点含正文（个人已购内容），落盘权限收紧到 0600。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    assert store.state_path.stat().st_mode & 0o777 == 0o600
    assert store.chapter_path(CH_URL).stat().st_mode & 0o777 == 0o600


def test_load_corrupt_state_raises_checkpoint_error(tmp_path: Path) -> None:
    """损坏状态 → CheckpointError，中文消息含下一步（删除/重新下载）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("{不是合法 JSON", encoding="utf-8")

    with pytest.raises(CheckpointError) as exc:
        store.load()
    message = str(exc.value)
    assert "损坏" in message
    assert "--no-resume" in message or "删除" in message


def test_load_non_dict_state_raises_checkpoint_error(tmp_path: Path) -> None:
    """顶层不是对象的状态文件同样视为损坏。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(CheckpointError):
        store.load()


def test_recovery_after_corruption_via_clear(tmp_path: Path) -> None:
    """损坏恢复：clear() 能删掉坏文件，之后重新可用。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("broken", encoding="utf-8")

    store.clear()
    assert not store.state_path.exists()
    store.save({"done_urls": [CH_URL]})
    assert store.load() == {"done_urls": [CH_URL]}


# ----------------------------------------------------------------------
# 章节正文缓存
# ----------------------------------------------------------------------

def test_put_and_get_chapter_roundtrip(tmp_path: Path) -> None:
    """正文缓存保留结构块（h2/p/li/img）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    article = make_article()
    store.put_chapter(CH_URL, article)

    path = store.chapter_path(CH_URL)
    assert path == tmp_path / "state" / "chapters" / f"{sha16(CH_URL)}.json"
    restored = store.get_article(CH_URL)
    assert restored is not None
    assert restored.to_dict() == article.to_dict()
    assert restored.blocks[3].src == "https://pic.img/1.png"


def test_put_chapter_records_done_url(tmp_path: Path) -> None:
    """put_chapter 之后 URL 进入 done 集合（续传据此跳过）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.put_chapter(CH_URL + "?x=1", make_article(title="第二章"))
    assert store.get_done_urls() == {CH_URL, CH_URL + "?x=1"}
    assert store.load()["done_urls"] == [CH_URL, CH_URL + "?x=1"]  # 保持顺序


def test_done_urls_ignores_entries_without_body(tmp_path: Path) -> None:
    """状态里说完成但正文文件被删 → 不算完成（下次会重取）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.chapter_path(CH_URL).unlink()
    assert store.get_done_urls() == set()


def test_get_article_corrupt_body_returns_none(tmp_path: Path) -> None:
    """正文缓存损坏 → None（视为未下载，自动重取而非整本失败）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.chapter_path(CH_URL).write_text("{{{", encoding="utf-8")
    assert store.get_article(CH_URL) is None


def test_get_article_non_dict_body_returns_none(tmp_path: Path) -> None:
    """正文缓存结构异常（顶层非对象）→ None。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.chapter_path(CH_URL).write_text("[]", encoding="utf-8")
    assert store.get_article(CH_URL) is None


def test_get_article_missing_required_key_returns_none(tmp_path: Path) -> None:
    """缺 title 键无法还原 Article → None 而非抛错。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.chapter_path(CH_URL).write_text('{"blocks": []}', encoding="utf-8")
    assert store.get_article(CH_URL) is None


def test_put_chapter_overwrites_previous_body(tmp_path: Path) -> None:
    """同一 URL 重复写入以最后一次为准（重跑单章安全）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article(title="旧"))
    store.put_chapter(CH_URL, make_article(title="新"))
    assert store.get_article(CH_URL) is not None
    assert store.get_article(CH_URL).title == "新"
    assert store.get_done_urls() == {CH_URL}


# ----------------------------------------------------------------------
# 元信息
# ----------------------------------------------------------------------

def test_set_meta_writes_fields_and_keeps_done_urls(tmp_path: Path) -> None:
    """set_meta 更新书名/总数/格式，且不清空已完成章节。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.set_meta("书名", 12, "epub")

    data = store.load()
    assert data["title"] == "书名"
    assert data["total"] == 12
    assert data["format"] == "epub"
    assert data["book_key"] == BOOK_KEY
    assert data["done_urls"] == [CH_URL]
    assert store.get_meta()["title"] == "书名"


def test_set_meta_twice_is_idempotent(tmp_path: Path) -> None:
    """重复 set_meta 只更新值，done_urls 不重复膨胀。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.set_meta("A", 1, "md")
    store.put_chapter(CH_URL, make_article())
    store.set_meta("B", 2, "txt")
    assert store.load()["done_urls"] == [CH_URL]
    assert store.load()["title"] == "B"


# ----------------------------------------------------------------------
# 清理与隔离
# ----------------------------------------------------------------------

def test_clear_removes_state_and_chapter_cache(tmp_path: Path) -> None:
    """clear() 删除状态与本书章节缓存。"""
    state_dir = tmp_path / "state"
    store = CheckpointStore(state_dir, BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.put_chapter(CH_URL + "?2", make_article(title="第二章"))
    store.set_meta("书名", 2, "md")

    store.clear()

    assert not store.state_path.exists()
    assert store.get_done_urls() == set()
    assert store.get_article(CH_URL) is None
    assert not store.chapter_path(CH_URL).exists()
    assert not store.chapters_dir.exists()  # 空目录顺手清理


def test_clear_is_idempotent(tmp_path: Path) -> None:
    """clear() 幂等：不存在也不报错。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.clear()
    store.clear()
    assert store.load() == {}


def test_books_are_isolated(tmp_path: Path) -> None:
    """不同 book_key 的状态互不影响。"""
    a = CheckpointStore(tmp_path, "book-a")
    b = CheckpointStore(tmp_path, "book-b")
    a.put_chapter(CH_URL, make_article(title="A 的书"))
    assert a.get_done_urls() == {CH_URL}
    assert b.get_done_urls() == set()      # b 的状态里没记这条
    assert b.load() == {}                  # 两本书的状态文件互不覆盖
    b.set_meta("B 书", 1, "md")
    assert a.load()["done_urls"] == [CH_URL]
    b.clear()
    assert a.get_done_urls() == {CH_URL}


def test_clear_preserves_bodies_still_referenced_by_other_books(tmp_path: Path) -> None:
    """并发保护：另一本书的状态还在引用的正文，clear() 不得删除。"""
    a = CheckpointStore(tmp_path, "book-a")
    b = CheckpointStore(tmp_path, "book-b")
    a.put_chapter(CH_URL, make_article(title="共享章"))
    b.put_chapter(CH_URL, make_article(title="共享章"))

    a.clear()

    assert not a.state_path.exists()          # 本书状态一定清掉
    assert b.get_done_urls() == {CH_URL}      # b 仍认为已完成
    assert b.get_article(CH_URL) is not None  # 正文没被 a 误删
    assert a.get_done_urls() == set()         # a 自己干净了


def test_clear_removes_body_when_no_other_state_references_it(tmp_path: Path) -> None:
    """无人引用时照常删除，不留垃圾。"""
    a = CheckpointStore(tmp_path, "book-a")
    a.put_chapter(CH_URL, make_article())
    CheckpointStore(tmp_path, "book-b").save({"done_urls": ["https://other/1"]})

    a.clear()

    assert not a.chapter_path(CH_URL).exists()


def test_same_url_cached_once(tmp_path: Path) -> None:
    """章节缓存按 URL 哈希命名：两本书共用同一 URL 时读回同一份正文。"""
    a = CheckpointStore(tmp_path, "book-a")
    b = CheckpointStore(tmp_path, "book-b")
    a.put_chapter(CH_URL, make_article(title="共享章"))
    assert b.get_article(CH_URL) is not None
    assert b.get_article(CH_URL).title == "共享章"
    assert b.get_done_urls() == set()  # 但 b 的状态里没记完成


# ----------------------------------------------------------------------
# get_done_urls：「存在且可解析」判定（R1-m1）
# ----------------------------------------------------------------------

def test_done_urls_excludes_corrupt_body(tmp_path: Path) -> None:
    """R1-m1：状态说完成、正文文件也在、但内容坏 → 不算完成（续传自动重取）。

    旧实现只查文件存在：坏缓存被当作已完成跳过，直到导出阶段才炸 ParseError，
    把用户逼上 --no-resume 全量重下的死路。
    """
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.chapter_path(CH_URL).write_text("{{{截断", encoding="utf-8")
    assert store.get_done_urls() == set()


def test_done_urls_excludes_unrestorable_body(tmp_path: Path) -> None:
    """JSON 合法但还原不出 Article（缺 title）→ 同样不算完成。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.chapter_path(CH_URL).write_text('{"blocks": []}', encoding="utf-8")
    assert store.get_done_urls() == set()


def test_done_urls_corrupt_body_warns_exactly_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """R1-m1：坏缓存移出完成集合时记 1 次 warning（不静默、也不刷屏）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.put_chapter(CH_URL + "?2", make_article(title="第二章"))
    store.chapter_path(CH_URL).write_text("{{{", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="zhihu_downloader.engine.checkpoint"):
        assert store.get_done_urls() == {CH_URL + "?2"}

    warns = [r for r in caplog.records if "章节缓存" in r.getMessage()]
    assert len(warns) == 1
    assert str(store.chapter_path(CH_URL)) in warns[0].getMessage()


def test_done_urls_keeps_good_bodies_and_drops_missing(tmp_path: Path) -> None:
    """混合场景：好章保留、坏章与缺文件章都移出完成集合。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    good, bad, gone = CH_URL, CH_URL + "?bad", CH_URL + "?gone"
    store.put_chapter(good, make_article())
    store.put_chapter(bad, make_article(title="坏"))
    store.put_chapter(gone, make_article(title="丢"))
    store.chapter_path(bad).write_text("not json", encoding="utf-8")
    store.chapter_path(gone).unlink()
    assert store.get_done_urls() == {good}


# ----------------------------------------------------------------------
# prune：单本显式清理入口（R1-M4，CLI shelf remove / DELETE /api/shelf 接线用）
# ----------------------------------------------------------------------

def test_prune_removes_state_and_bodies(tmp_path: Path) -> None:
    """prune 删除本书状态与其全部章节正文。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.put_chapter(CH_URL + "?2", make_article(title="第二章"))
    store.set_meta("书名", 2, "md")

    store.prune(BOOK_KEY)

    assert not store.state_path.exists()
    assert not store.chapter_path(CH_URL).exists()
    assert not store.chapter_path(CH_URL + "?2").exists()
    assert store.load() == {}


def test_prune_defaults_to_own_book_key(tmp_path: Path) -> None:
    """prune() 不带参数 = 清理 self.book_key。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    store.prune()
    assert not store.state_path.exists()
    assert not store.chapter_path(CH_URL).exists()


def test_prune_is_idempotent(tmp_path: Path) -> None:
    """prune 幂等：目录不存在、重复调用都不报错。"""
    store = CheckpointStore(tmp_path / "no-such-dir", BOOK_KEY)
    store.prune(BOOK_KEY)  # 目录都没有 → 静默
    store2 = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store2.put_chapter(CH_URL, make_article())
    store2.prune(BOOK_KEY)
    store2.prune(BOOK_KEY)  # 第二次无文件可删 → 静默
    assert store2.load() == {}


def test_prune_targets_another_book_key_in_same_dir(tmp_path: Path) -> None:
    """prune(book_key) 删指定书（shelf remove 只知道 URL）；别的书不受影响。"""
    a = CheckpointStore(tmp_path, "book-a")
    b = CheckpointStore(tmp_path, "book-b")
    a.put_chapter(CH_URL, make_article(title="A 的章"))
    b.put_chapter(CH_URL + "?b", make_article(title="B 的章"))

    a.prune("book-a")

    assert not a.state_path.exists()
    assert not a.chapter_path(CH_URL).exists()
    assert b.state_path.exists()
    assert b.get_done_urls() == {CH_URL + "?b"}


def test_prune_deletes_shared_body_and_referencer_self_heals(tmp_path: Path) -> None:
    """prune 是显式清理：不像 clear 那样保护兄弟引用；被删方按 m1 语义自愈。"""
    a = CheckpointStore(tmp_path, "book-a")
    b = CheckpointStore(tmp_path, "book-b")
    a.put_chapter(CH_URL, make_article(title="共享章"))
    b.put_chapter(CH_URL, make_article(title="共享章"))

    a.prune("book-a")

    assert not a.chapter_path(CH_URL).exists()   # 共享正文被显式删掉
    assert b.state_path.exists()                 # b 的状态文件还在
    assert b.get_done_urls() == set()            # 但 m1 判定把缺正文的章移出完成集合
    b.put_chapter(CH_URL, make_article(title="共享章"))  # b 重取即恢复（自愈闭环）
    assert b.get_done_urls() == {CH_URL}


def test_prune_survives_corrupt_state(tmp_path: Path) -> None:
    """状态文件损坏也要能 prune（load 抛 CheckpointError 时直接删文件）。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("{坏掉了", encoding="utf-8")
    store.prune(BOOK_KEY)
    assert not store.state_path.exists()


# ----------------------------------------------------------------------
# total_bytes：磁盘占用观测（R1-M4 之后断点保留，doctor 报占用用）
# ----------------------------------------------------------------------

def test_total_bytes_zero_when_dir_missing(tmp_path: Path) -> None:
    """目录不存在 → 0（首次运行前）。"""
    store = CheckpointStore(tmp_path / "nothing", BOOK_KEY)
    assert store.total_bytes() == 0


def test_total_bytes_counts_state_and_bodies(tmp_path: Path) -> None:
    """total_bytes = 状态文件 + 章节正文缓存的实际字节数之和。"""
    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    store.put_chapter(CH_URL, make_article())
    expected = store.state_path.stat().st_size + store.chapter_path(CH_URL).stat().st_size
    assert expected > 0
    assert store.total_bytes() == expected


def test_total_bytes_covers_all_books_in_dir(tmp_path: Path) -> None:
    """多本书共用状态目录时按目录汇总（doctor 报的是整体占用）。"""
    a = CheckpointStore(tmp_path, "book-a")
    b = CheckpointStore(tmp_path, "book-b")
    a.put_chapter(CH_URL, make_article())
    b.put_chapter(CH_URL + "?b", make_article(title="B 的章"))
    total = a.total_bytes()
    assert total >= (tmp_path / f"{key_hash('book-a')}.json").stat().st_size
    assert total >= (tmp_path / f"{key_hash('book-b')}.json").stat().st_size
    assert total > 0


# ----------------------------------------------------------------------
# 并发
# ----------------------------------------------------------------------

def test_concurrent_put_chapter_is_thread_safe(tmp_path: Path) -> None:
    """8 线程并发写不同章节：done_urls 不丢条目、无临时文件残留。"""
    import threading

    store = CheckpointStore(tmp_path / "state", BOOK_KEY)
    urls = [f"{CH_URL}?i={i}" for i in range(24)]
    gate = threading.Barrier(8, timeout=5)

    def worker(shard: list[str]) -> None:
        gate.wait()
        for url in shard:
            store.put_chapter(url, make_article(title=url, url=url))

    threads = [
        threading.Thread(target=worker, args=(urls[i::8],)) for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert store.get_done_urls() == set(urls)
    assert len(store.load()["done_urls"]) == 24
    assert list(store.chapters_dir.glob("*.tmp")) == []
