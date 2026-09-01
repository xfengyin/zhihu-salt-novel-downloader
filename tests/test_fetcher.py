"""fetcher 下载编排测试（全离线）。

parse / export 模块由其他 agent 并行开发，本文件一律用
monkeypatch.setitem(sys.modules, "zhihu_downloader.parse.parser", fake) 注入假模块，
因此不依赖他们的文件是否存在；网络边界用 FakeSession 顶掉。
"""

from __future__ import annotations

import copy
import re
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

from zhihu_downloader.engine import client as client_mod
from zhihu_downloader.engine.checkpoint import CheckpointStore
from zhihu_downloader.engine.client import ZhihuClient
from zhihu_downloader.engine.fetcher import (
    DEFAULT_STATE_SUBDIR,
    check_new_chapters,
    download_book,
    resolve_book,
)
from zhihu_downloader.errors import (
    CheckpointError,
    ExportError,
    ParseError,
    UnsupportedUrlError,
    ZhihuError,
)
from zhihu_downloader.types import Article, Block, ChapterRef, ProgressEvent

COLUMN = "https://www.zhihu.com/market/paid_column/9527"
SECTION = "https://www.zhihu.com/market/paid_column/9527/section/1"
APP_URL = "https://story.zhihu.com/manuscript/paid_column/9527/777"
#: 故意用「<专栏ID>」占位（与真实 friendly_hint 一样不含具体 ID），
#: 以此验证 fetcher 自己会把 story 链接换算成可粘贴的 market 链接。
STORY_HINT = (
    "替代方法：把链接中的 story.zhihu.com/manuscript/paid_column/<专栏ID> "
    "替换为 www.zhihu.com/market/paid_column/<专栏ID> 后重试。"
)


def fake_chapter_type(title: str) -> str:
    """模拟 parse 层分类器（E3 在 parse_article / parse_toc 内部已调用）。"""
    if "番外" in title:
        return "extra"
    if "作者的话" in title:
        return "author_note"
    return "normal"


def article_for(url: str, title: str, chapter_type: str | None = None) -> Article:
    """构造假解析结果（带结构块；chapter_type 由「解析层」填好，同 E3 行为）。"""
    return Article(
        title=title,
        url=url,
        chapter_type=fake_chapter_type(title) if chapter_type is None else chapter_type,
        blocks=[Block(kind="p", text=f"正文 of {title}")],
    )


# ----------------------------------------------------------------------
# 假 parse / export 模块
# ----------------------------------------------------------------------

class Fakes:
    """注入到 sys.modules 的 parse/export 假模块集合（记录所有调用）。"""

    def __init__(self) -> None:
        self.url_types: dict[str, str] = {}
        self.articles: dict[str, Article] = {}
        self.toc: list[ChapterRef] = []
        self.page_titles: dict[str, str] = {}
        self.parse_delays: dict[str, float] = {}
        self.clean_calls: list[str] = []
        self.export_calls: list[dict[str, Any]] = []
        self.export_error: Exception | None = None

    # -- 装配 --------------------------------------------------------
    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """把假模块塞进 sys.modules（fetcher 在函数内延迟导入，故即时生效）。"""
        parser = types.ModuleType("zhihu_downloader.parse.parser")
        parser.parse_article = self._parse_article          # type: ignore[attr-defined]
        parser.parse_toc = self._parse_toc                  # type: ignore[attr-defined]
        parser.parse_page_title = self._parse_page_title    # type: ignore[attr-defined]

        urltype = types.ModuleType("zhihu_downloader.parse.urltype")
        urltype.detect = self._detect                       # type: ignore[attr-defined]
        urltype.friendly_hint = self._friendly_hint         # type: ignore[attr-defined]
        urltype.is_app_only = lambda url: self._detect(url) in ("app_column", "app_section")
        # 与 E3 真实实现同一口径：group(1)=专栏 ID，group(2)=可选章节 ID
        urltype.MANUSCRIPT_PATTERN = re.compile(r"/manuscript/paid_column/(\d+)(?:/(\d+))?")

        cleaner = types.ModuleType("zhihu_downloader.parse.cleaner")
        cleaner.clean = self._clean                         # type: ignore[attr-defined]

        export = types.ModuleType("zhihu_downloader.export")
        export.FORMATS = ("txt", "md", "epub")              # type: ignore[attr-defined]
        export.export_book = self._export_book              # type: ignore[attr-defined]

        # 注意：不注入 parse.classifier —— fetcher 不做重复分类（E3 情报 §2）。
        for name, module in {
            "zhihu_downloader.parse.parser": parser,
            "zhihu_downloader.parse.urltype": urltype,
            "zhihu_downloader.parse.cleaner": cleaner,
            "zhihu_downloader.export": export,
        }.items():
            monkeypatch.setitem(sys.modules, name, module)

    # -- parse.urltype ----------------------------------------------
    def _detect(self, url: str) -> str:
        return self.url_types.get(url, "column")

    def _friendly_hint(self, url_type: str) -> str:
        if url_type.startswith("app_"):
            return STORY_HINT
        if url_type == "unknown":
            # 与真实 parse.urltype（urltype.py 的 "unknown" 词条）同一口径：
            # 提示本身就以「无法识别该链接」开头——fetcher 不得再重复前缀。
            return (
                "无法识别该链接（不是知乎系域名或格式有误）。"
                "请提供知乎回答、盐选专栏目录页或章节链接后重试。"
            )
        return "请提供知乎回答或盐选专栏链接后重试。"

    # -- parse.parser ------------------------------------------------
    def _parse_article(self, html: str, url: str = "") -> Article:
        delay = self.parse_delays.get(url, 0.0)
        if delay:
            time.sleep(delay)
        if url in self.articles:
            return copy.deepcopy(self.articles[url])
        raise ParseError(f"假解析失败：{url}")

    def _parse_toc(self, html: str, base_url: str) -> list[ChapterRef]:
        # parse_toc 内部已用分类器填好 type（同 E3）：显式给过非默认值就保留，
        # 否则按标题算一遍，模拟真实解析层。按 base_url 前缀过滤：一册多目录
        # （并发共用 client 的测试）时各目录只看到自己的章节。
        return [
            ChapterRef(
                url=ch.url,
                title=ch.title,
                index=ch.index,
                type=ch.type if ch.type and ch.type != "normal" else fake_chapter_type(ch.title),
            )
            for ch in self.toc
            if ch.url.startswith(base_url)
        ]

    def _parse_page_title(self, html: str) -> str:
        return self.page_titles.get(html, "") or self.page_titles.get("*", "")

    # -- parse.cleaner -----------------------------------------------
    def _clean(self, article: Article, extra_patterns: list[str] | None = None) -> Article:
        self.clean_calls.append(article.title)
        return article

    # -- export ------------------------------------------------------
    def _export_book(
        self, title: str, articles: list[Article], fmt: str, output_dir: Any
    ) -> list[str]:
        if self.export_error is not None:
            raise self.export_error
        self.export_calls.append(
            {"title": title, "titles": [a.title for a in articles], "fmt": fmt,
             "articles": list(articles), "output_dir": str(output_dir)}
        )
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{title}.{fmt}"
        path.write_text("\n\n".join(a.plain_text() for a in articles), encoding="utf-8")
        return [str(path)]


@pytest.fixture()
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    """注入假 parse/export 模块。"""
    holder = Fakes()
    holder.install(monkeypatch)
    return holder


# ----------------------------------------------------------------------
# 假 HTTP 边界
# ----------------------------------------------------------------------

class FakeResponse:
    """最小响应替身。"""

    def __init__(self, status_code: int, text: str = "页面") -> None:
        self.status_code = status_code
        self.text = text


class FakeCookieJar:
    """最小 CookieJar 替身。"""

    def __init__(self) -> None:
        self.jar: dict[str, str] = {}

    def update(self, mapping: dict[str, str]) -> None:
        self.jar.update(mapping)


class FakeSession:
    """按 URL 返回预置响应；脚本项可为 Exception（模拟网络错误）。"""

    def __init__(self, pages: dict[str, Any], default: Any | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.cookies = FakeCookieJar()
        self.pages = pages
        self.default = default
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def get(
        self, url: str, headers: dict[str, str] | None = None, timeout: Any = None
    ) -> FakeResponse:
        with self._lock:
            self.calls.append(url)
        item = self.pages.get(url, self.default)
        if item is None:
            return FakeResponse(404, "不存在")
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(url)
        return item

    def count(self, url: str) -> int:
        """某 URL 被请求的次数。"""
        return self.calls.count(url)


class FakeClock:
    """time 替身：sleep 只记录，不真等（让退避测试零耗时）。"""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(session: FakeSession, **kwargs: Any) -> ZhihuClient:
    """构造离线客户端（默认不限速、不重试，便于精确断言请求次数）。"""
    kwargs.setdefault("rate_limit", 0)
    kwargs.setdefault("retries", 0)
    client = ZhihuClient(cookie_file=Path("/nonexistent/cookies.json"), **kwargs)
    client.session = session
    return client


def column_setup(fakes: Fakes, count: int = 3) -> dict[str, Any]:
    """配好一个 count 章的专栏：目录 + 每章正文 + 书名。"""
    chapters = [
        ChapterRef(url=f"{COLUMN}/section/{i}", title=f"第{i}章", index=i)
        for i in range(1, count + 1)
    ]
    fakes.url_types[COLUMN] = "column"
    fakes.toc = chapters
    fakes.page_titles["目录页HTML"] = "测试专栏"
    for ch in chapters:
        fakes.articles[ch.url] = article_for(ch.url, ch.title)
    return {"chapters": chapters}


def collect_events() -> tuple[list[ProgressEvent], Any]:
    """返回 (事件列表, 回调)。"""
    events: list[ProgressEvent] = []
    return events, events.append


# ----------------------------------------------------------------------
# resolve_book
# ----------------------------------------------------------------------

def test_resolve_book_section_single_chapter(fakes: Fakes) -> None:
    """章节链接 → 1 章的 BookMeta，标题取正文标题。"""
    fakes.url_types[SECTION] = "section"
    fakes.articles[SECTION] = article_for(SECTION, "第一章 初见")
    session = FakeSession({SECTION: FakeResponse(200, "章节页HTML")})
    fakes.page_titles["章节页HTML"] = "章节页标题"

    meta = resolve_book(make_client(session), SECTION)

    assert meta.title == "第一章 初见"
    assert meta.url == SECTION
    assert len(meta.chapters) == 1
    assert meta.chapters[0].url == SECTION
    assert meta.chapters[0].index == 1
    assert session.calls == [SECTION]


def test_resolve_book_column_with_title_and_order(fakes: Fakes) -> None:
    """专栏链接 → 书名来自 parse_page_title，章节保持目录顺序。"""
    column_setup(fakes, count=3)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})

    meta = resolve_book(make_client(session), COLUMN)

    assert meta.title == "测试专栏"
    assert [ch.title for ch in meta.chapters] == ["第1章", "第2章", "第3章"]
    assert [ch.index for ch in meta.chapters] == [1, 2, 3]


def test_resolve_book_normalizes_duplicates_and_types(fakes: Fakes) -> None:
    """目录去重保序、序号连续，番外由分类器补齐类型。"""
    fakes.url_types[COLUMN] = "column"
    fakes.toc = [
        ChapterRef(url=f"{COLUMN}/section/1", title="第1章", index=7),
        ChapterRef(url=f"{COLUMN}/section/1", title="重复项", index=8),
        ChapterRef(url=f"{COLUMN}/section/2", title="番外：后日谈", index=9),
        ChapterRef(url="", title="空链接", index=10),
        ChapterRef(url=f"{COLUMN}/section/3", title="", index=11),
    ]
    fakes.page_titles["目录页HTML"] = "测试专栏"
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})

    meta = resolve_book(make_client(session), COLUMN)

    assert [ch.index for ch in meta.chapters] == [1, 2, 3]
    assert [ch.url for ch in meta.chapters] == [
        f"{COLUMN}/section/1", f"{COLUMN}/section/2", f"{COLUMN}/section/3"
    ]
    assert meta.chapters[1].type == "extra"
    assert meta.chapters[0].type == "normal"
    assert meta.chapters[2].title == f"{COLUMN}/section/3"  # 无标题时回落 URL


def test_resolve_book_falls_back_to_first_chapter_title(fakes: Fakes) -> None:
    """页面标题解析不出来时用第一章标题当书名。"""
    column_setup(fakes, count=2)
    fakes.page_titles.clear()
    session = FakeSession({COLUMN: FakeResponse(200, "无标题页")})

    assert resolve_book(make_client(session), COLUMN).title == "第1章"


def test_resolve_book_app_only_raises_with_replacement_hint(fakes: Fakes) -> None:
    """仅 APP 内阅读链接 → UnsupportedUrlError，消息含 story→market 替换建议。"""
    fakes.url_types[APP_URL] = "app_column"
    session = FakeSession({})

    with pytest.raises(UnsupportedUrlError) as exc:
        resolve_book(make_client(session), APP_URL)

    message = str(exc.value)
    assert "仅支持在知乎 APP 内阅读" in message
    assert STORY_HINT in message                       # 保留解析层的通用说明
    assert "https://www.zhihu.com/market/paid_column/9527/section/777" in message
    assert session.calls == []  # 不该白跑一次请求


def test_market_replacement_concrete_urls() -> None:
    """story→market 换算：专栏页与章节页都能给出可直接粘贴的链接。"""
    from zhihu_downloader.engine.fetcher import market_replacement

    assert market_replacement(APP_URL) == (
        "https://www.zhihu.com/market/paid_column/9527/section/777"
    )
    assert market_replacement("https://story.zhihu.com/manuscript/paid_column/abc") == (
        "https://www.zhihu.com/market/paid_column/abc"
    )
    # 结构不认识 / 不是 story 域名 → 空串（错误消息里就不给假建议）
    assert market_replacement("https://story.zhihu.com/other/thing") == ""
    assert market_replacement("https://www.zhihu.com/market/paid_column/1") == ""
    assert market_replacement("完全不是 URL") == ""


def test_market_replacement_uses_parse_layer_pattern(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """换算优先采用 parse.urltype.MANUSCRIPT_PATTERN（与 detect 同一口径）。"""
    from zhihu_downloader.engine.fetcher import market_replacement

    stub = types.ModuleType("zhihu_downloader.parse.urltype")
    stub.MANUSCRIPT_PATTERN = re.compile(r"/m/col/(\d+)(?:/(\d+))?")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "zhihu_downloader.parse.urltype", stub)

    # 该路径段（/m/col/）本地兜底是不认的，只有走了注入模式才会得到下面的结果
    assert market_replacement("https://story.zhihu.com/m/col/42/7") == (
        "https://www.zhihu.com/market/paid_column/42/section/7"
    )
    assert market_replacement("https://story.zhihu.com/m/col/42") == (
        "https://www.zhihu.com/market/paid_column/42"
    )
    assert market_replacement("https://story.zhihu.com/other/42") == ""


def test_market_replacement_falls_back_when_pattern_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解析层没导出 MANUSCRIPT_PATTERN 时，本地按路径段兜底（不硬依赖 E3）。"""
    from zhihu_downloader.engine.fetcher import market_replacement

    stub = types.ModuleType("zhihu_downloader.parse.urltype")
    monkeypatch.setitem(sys.modules, "zhihu_downloader.parse.urltype", stub)

    assert market_replacement("https://story.zhihu.com/manuscript/paid_column/abc/xyz") == (
        "https://www.zhihu.com/market/paid_column/abc/section/xyz"
    )


def test_app_only_message_without_replacement_has_no_fake_hint(fakes: Fakes) -> None:
    """换算不了时，消息里不出现「请改用网页版链接」的假指引。"""
    weird = "https://story.zhihu.com/some/odd/path"
    fakes.url_types[weird] = "app_column"
    with pytest.raises(UnsupportedUrlError) as exc:
        resolve_book(make_client(FakeSession({})), weird)
    assert "请改用网页版链接" not in str(exc.value)


def test_resolve_book_unknown_url_raises(fakes: Fakes) -> None:
    """无法识别的链接 → UnsupportedUrlError；「无法识别」恰好出现 1 次（I3 反向发现定稿）。

    friendly_hint('unknown') 本身以「无法识别该链接」开头，fetcher 旧写法把前缀
    说了两遍；定稿 = 提示原文 + 「（链接：url）」。假 hint 与真实 parse.urltype
    同口径，另见下方真模块集成测试。
    """
    fakes.url_types["https://example.com/x"] = "unknown"
    with pytest.raises(UnsupportedUrlError) as exc:
        resolve_book(make_client(FakeSession({})), "https://example.com/x")
    message = str(exc.value)
    assert message.count("无法识别") == 1, f"前缀重复了：{message}"
    assert "（链接：https://example.com/x）" in message  # 具体链接仍然给出
    assert "请提供知乎回答" in message                   # 解析层提示原样保留


def test_resolve_book_unknown_url_real_hint_once(
    fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """与真实 parse.urltype 集成（不依赖假词表）：去重后「无法识别」仍恰好 1 次。

    钉住假/真词表口径漂移：撤掉注入的假 urltype，让 _resolve_book 走真实
    detect + friendly_hint；解析层未落地时跳过，不拖垮引擎套件。
    """
    import importlib

    monkeypatch.delitem(sys.modules, "zhihu_downloader.parse.urltype", raising=False)
    try:
        urltype_real = importlib.import_module("zhihu_downloader.parse.urltype")
    except ImportError:  # pragma: no cover - 并行开发期兜底
        pytest.skip("parse.urltype 未落地，假模块测试已钉 fetcher 行为")
    assert urltype_real.friendly_hint("unknown").startswith("无法识别该链接")
    assert urltype_real.detect("https://example.com/x") == "unknown"

    with pytest.raises(UnsupportedUrlError) as exc:
        resolve_book(make_client(FakeSession({})), "https://example.com/x")
    message = str(exc.value)
    assert message.count("无法识别") == 1, f"前缀重复了：{message}"
    assert "（链接：https://example.com/x）" in message


def test_resolve_book_empty_toc_raises_parse_error(fakes: Fakes) -> None:
    """专栏页解析不出章节 → ParseError，提示确认链接与 Cookie。"""
    fakes.url_types[COLUMN] = "column"
    fakes.toc = []
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})

    with pytest.raises(ParseError) as exc:
        resolve_book(make_client(session), COLUMN)
    assert "Cookie" in str(exc.value)


def test_resolve_book_propagates_http_error(fakes: Fakes) -> None:
    """目录页 403 → 直接抛 ZhihuError（反爬中文提示）。"""
    column_setup(fakes)
    session = FakeSession({COLUMN: FakeResponse(403)})

    with pytest.raises(ZhihuError, match="HTTP 403"):
        resolve_book(make_client(session), COLUMN)


# ----------------------------------------------------------------------
# download_book：正常路径
# ----------------------------------------------------------------------

def test_download_book_progress_sequence(fakes: Fakes, tmp_path: Path) -> None:
    """全链路事件序列：toc → chapter×3 → export → done，并导出文件。"""
    column_setup(fakes, count=3)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           **{f"{COLUMN}/section/{i}": FakeResponse(200, "章") for i in (1, 2, 3)}})
    events, emit = collect_events()

    result = download_book(make_client(session), COLUMN, fmt="md",
                           output_dir=tmp_path, progress=emit, workers=3)

    assert [e.kind for e in events] == ["toc", "chapter", "chapter", "chapter", "export", "done"]
    assert events[0].total == 3 and events[0].current == 0
    assert [e.current for e in events[1:4]] == [1, 2, 3]
    assert all(e.total == 3 for e in events)
    assert events[-1].title == "测试专栏"

    assert result.title == "测试专栏"
    assert result.url == COLUMN
    assert result.chapters == 3
    assert result.skipped_existing == 0
    assert len(result.files) == 1 and result.files[0].endswith(".md")
    assert Path(result.files[0]).read_text(encoding="utf-8").count("正文 of") == 3


def test_download_book_exports_in_toc_order(fakes: Fakes, tmp_path: Path) -> None:
    """并发完成顺序乱序时，导出仍严格按目录顺序。"""
    column_setup(fakes, count=3)
    fakes.parse_delays = {f"{COLUMN}/section/1": 0.06,
                          f"{COLUMN}/section/2": 0.03,
                          f"{COLUMN}/section/3": 0.0}
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           **{f"{COLUMN}/section/{i}": FakeResponse(200, "章") for i in (1, 2, 3)}})

    download_book(make_client(session), COLUMN, output_dir=tmp_path, workers=3)

    assert fakes.export_calls[0]["titles"] == ["第1章", "第2章", "第3章"]
    assert len(fakes.clean_calls) == 3


def test_download_book_accepts_progress_none_and_keeps_checkpoint(
    fakes: Fakes, tmp_path: Path
) -> None:
    """progress=None 可正常下载；成功后**保留**断点。

    旧断言钉的是「成功即清」；R1-M4 主审裁决改为成功后保留 state+bodies——
    同链接重跑=秒级重导出、追更只抓新章。清理入口是 resume=False 与 prune。
    """
    column_setup(fakes, count=2)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           **{f"{COLUMN}/section/{i}": FakeResponse(200, "章") for i in (1, 2)}})

    download_book(make_client(session), COLUMN, output_dir=tmp_path, progress=None)

    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    assert store.get_done_urls() == {f"{COLUMN}/section/1", f"{COLUMN}/section/2"}
    assert store.get_meta()["title"] == "测试专栏"
    for i in (1, 2):
        assert store.get_article(f"{COLUMN}/section/{i}") is not None


def test_download_book_section_only_fetches_one_page(fakes: Fakes, tmp_path: Path) -> None:
    """单章链接只请求该页并导出 1 章。"""
    fakes.url_types[SECTION] = "section"
    fakes.articles[SECTION] = article_for(SECTION, "单章标题")
    session = FakeSession({SECTION: FakeResponse(200, "章节页HTML")})
    events, emit = collect_events()

    result = download_book(make_client(session), SECTION, output_dir=tmp_path, progress=emit)

    assert result.chapters == 1
    assert session.calls == [SECTION]
    assert [e.kind for e in events] == ["toc", "chapter", "export", "done"]


def test_download_book_fills_missing_title_and_chapter_type(fakes: Fakes, tmp_path: Path) -> None:
    """解析结果缺标题/类型时，用目录标题与分类器补齐。"""
    fakes.url_types[COLUMN] = "column"
    fakes.toc = [ChapterRef(url=f"{COLUMN}/section/9", title="番外：后日谈", index=1)]
    fakes.page_titles["目录页HTML"] = "测试专栏"
    blank = Article(title="", url="", blocks=[Block(kind="p", text="内容")])
    fakes.articles[f"{COLUMN}/section/9"] = blank
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/9": FakeResponse(200, "章")})

    download_book(make_client(session), COLUMN, output_dir=tmp_path)

    assert fakes.export_calls[0]["titles"] == ["番外：后日谈"]
    exported = fakes.export_calls[0]["articles"][0]
    assert exported.chapter_type == "extra"      # 分类器补齐
    assert exported.url == f"{COLUMN}/section/9"  # 缺 URL 时回填目录 URL


def test_download_book_prefers_toc_title_over_page_title(
    fakes: Fakes, tmp_path: Path
) -> None:
    """目录标题优先：正文页 og:title 是营销标题时，导出仍用目录里的「番外」命名。"""
    fakes.url_types[COLUMN] = "column"
    fakes.toc = [
        ChapterRef(url=f"{COLUMN}/section/1", title="第一章 初入江湖", index=1),
        ChapterRef(url=f"{COLUMN}/section/2", title="番外 后记", index=2),
    ]
    fakes.page_titles["目录页HTML"] = "测试专栏"
    fakes.articles[f"{COLUMN}/section/1"] = article_for(f"{COLUMN}/section/1", "第1章 测试")
    fakes.articles[f"{COLUMN}/section/2"] = article_for(f"{COLUMN}/section/2", "第2章 测试")
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章"),
                           f"{COLUMN}/section/2": FakeResponse(200, "章")})

    download_book(make_client(session), COLUMN, output_dir=tmp_path, workers=1)

    assert fakes.export_calls[0]["titles"] == ["第一章 初入江湖", "番外 后记"]
    assert fakes.export_calls[0]["articles"][1].chapter_type == "extra"


def test_download_book_reuses_prepared_meta(fakes: Fakes, tmp_path: Path) -> None:
    """传 meta 时不再请求目录页（shelf 记账要的有序 URL 由上层从 BookMeta 取）。"""
    column_setup(fakes, count=2)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章"),
                           f"{COLUMN}/section/2": FakeResponse(200, "章")})
    client = make_client(session)
    meta = resolve_book(client, COLUMN)
    after_resolve = list(session.calls)

    result = download_book(client, COLUMN, output_dir=tmp_path, meta=meta, workers=1)

    assert result.chapters == 2
    assert session.calls == after_resolve + [f"{COLUMN}/section/1", f"{COLUMN}/section/2"]
    # 上层（CLI/server）据此调 Shelf.record_download(result, fmt, chapter_urls=...)
    assert [ch.url for ch in meta.chapters] == [f"{COLUMN}/section/1", f"{COLUMN}/section/2"]


def test_download_book_needs_no_classifier_module(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """分层校验：parse.classifier 不可 import 时下载照常（E3 已在解析层分类）。"""
    monkeypatch.setitem(sys.modules, "zhihu_downloader.parse.classifier", None)
    column_setup(fakes, count=2)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章"),
                           f"{COLUMN}/section/2": FakeResponse(200, "章")})

    result = download_book(make_client(session), COLUMN, output_dir=tmp_path, workers=2)

    assert result.chapters == 2
    assert fakes.export_calls[0]["titles"] == ["第1章", "第2章"]


def test_download_book_uses_cleaner_result(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """clean(article) 的返回值才是后续使用的对象（清洗层可换实例）。"""
    column_setup(fakes, count=1)

    def replace(article: Article, extra_patterns: list[str] | None = None) -> Article:
        fakes.clean_calls.append(article.title)
        return Article(title=article.title, url=article.url,
                       chapter_type=article.chapter_type,
                       blocks=[Block(kind="p", text="清洗后的正文")])

    monkeypatch.setattr(sys.modules["zhihu_downloader.parse.cleaner"], "clean", replace)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章")})

    download_book(make_client(session), COLUMN, output_dir=tmp_path)

    stored = fakes.export_calls[0]["articles"][0]
    assert stored.blocks[0].text == "清洗后的正文"


class StubClient:
    """只有 fetch 的鸭子类型客户端（没有 on_retry 属性，如上层/服务层的替身）。"""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        if url not in self.pages:
            raise ZhihuError(f"模拟 404：{url}")
        return self.pages[url]


def test_download_book_works_with_client_lacking_on_retry(
    fakes: Fakes, tmp_path: Path
) -> None:
    """客户端没有 on_retry 能力时下载照常（进度可观测性不得拖垮下载）。"""
    column_setup(fakes, count=2)
    stub = StubClient({COLUMN: "目录页HTML",
                       f"{COLUMN}/section/1": "章", f"{COLUMN}/section/2": "章"})

    result = download_book(stub, COLUMN, output_dir=tmp_path, workers=1)  # type: ignore[arg-type]

    assert result.chapters == 2
    assert not hasattr(stub, "on_retry")


def test_download_book_exports_from_memory_when_cache_vanishes(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """并发任务清掉了共享章节缓存也不影响本次导出（内存正文优先）。"""
    column_setup(fakes, count=2)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章"),
                           f"{COLUMN}/section/2": FakeResponse(200, "章")})
    monkeypatch.setattr(CheckpointStore, "get_article", lambda self, url: None)

    result = download_book(make_client(session), COLUMN, output_dir=tmp_path, workers=2)

    assert result.chapters == 2
    assert fakes.export_calls[0]["titles"] == ["第1章", "第2章"]


def test_download_book_concurrent_overlapping_books(tmp_path: Path, fakes: Fakes) -> None:
    """同一 URL 被两本书共用时，两个下载任务互不误删缓存（都能成功导出）。"""
    column_setup(fakes, count=3)
    fakes.url_types[SECTION] = "section"
    fakes.articles[SECTION] = article_for(SECTION, "第1章")
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML"), SECTION: FakeResponse(200, "章")}
    for i in (1, 2, 3):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    session = FakeSession(pages)
    client = make_client(session, rate_limit=0)
    results: dict[str, Any] = {}
    errors: list[BaseException] = []
    gate = threading.Barrier(2, timeout=10)

    def run(name: str, url: str) -> None:
        try:
            gate.wait()
            results[name] = download_book(client, url, output_dir=tmp_path, workers=2)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=run, args=("column", COLUMN))
    t2 = threading.Thread(target=run, args=("section", SECTION))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert errors == []
    assert results["column"].chapters == 3
    assert results["section"].chapters == 1
    assert all(Path(r.files[0]).exists() for r in results.values())


def test_download_book_keeps_parsed_chapter_type_when_toc_is_normal(
    fakes: Fakes, tmp_path: Path
) -> None:
    """解析层给出的非 normal 类型不被目录的默认 normal 覆盖。"""
    fakes.url_types[COLUMN] = "column"
    fakes.toc = [ChapterRef(url=f"{COLUMN}/section/1", title="正文页里才标明是作者的话", index=1)]
    fakes.page_titles["目录页HTML"] = "测试专栏"
    fakes.articles[f"{COLUMN}/section/1"] = article_for(
        f"{COLUMN}/section/1", "作者的话", chapter_type="author_note"
    )
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章")})

    download_book(make_client(session), COLUMN, output_dir=tmp_path)

    assert fakes.export_calls[0]["articles"][0].chapter_type == "author_note"


def test_download_book_keeps_parsed_title_when_toc_falls_back_to_url(
    fakes: Fakes, tmp_path: Path
) -> None:
    """目录没给标题（被 URL 兜底）时，保留正文解析出的真标题。"""
    fakes.url_types[COLUMN] = "column"
    fakes.toc = [ChapterRef(url=f"{COLUMN}/section/1", title="", index=1)]
    fakes.page_titles["目录页HTML"] = "测试专栏"
    fakes.articles[f"{COLUMN}/section/1"] = article_for(f"{COLUMN}/section/1", "真正的章名")
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章")})

    download_book(make_client(session), COLUMN, output_dir=tmp_path, workers=1)

    assert fakes.export_calls[0]["titles"] == ["真正的章名"]


def test_download_book_many_chapters_with_workers(fakes: Fakes, tmp_path: Path) -> None:
    """6 章 / 4 线程：全部完成，进度 current 恰好覆盖 1..6。"""
    column_setup(fakes, count=6)
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in range(1, 7):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    session = FakeSession(pages)
    events, emit = collect_events()

    result = download_book(make_client(session), COLUMN, output_dir=tmp_path,
                           progress=emit, workers=4)

    assert result.chapters == 6
    assert sorted(e.current for e in events if e.kind == "chapter") == [1, 2, 3, 4, 5, 6]
    assert len(session.calls) == 7  # 目录页 + 6 章


# ----------------------------------------------------------------------
# download_book：断点续传
# ----------------------------------------------------------------------

def test_download_book_resume_skips_done_chapters(fakes: Fakes, tmp_path: Path) -> None:
    """续传：已完成章节不再请求，skipped_existing 与进度起点正确。"""
    column_setup(fakes, count=3)
    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    store.put_chapter(f"{COLUMN}/section/1", article_for(f"{COLUMN}/section/1", "第1章"))
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML"),
                             f"{COLUMN}/section/2": FakeResponse(200, "章"),
                             f"{COLUMN}/section/3": FakeResponse(200, "章")}
    session = FakeSession(pages)
    events, emit = collect_events()

    result = download_book(make_client(session), COLUMN, output_dir=tmp_path,
                           progress=emit, resume=True, workers=2)

    assert result.skipped_existing == 1
    assert result.chapters == 3
    assert events[0].kind == "toc" and events[0].current == 1
    assert [e.current for e in events if e.kind == "chapter"] == [2, 3]
    assert f"{COLUMN}/section/1" not in session.calls
    assert fakes.export_calls[0]["titles"] == ["第1章", "第2章", "第3章"]


def test_download_book_resume_false_clears_checkpoint(fakes: Fakes, tmp_path: Path) -> None:
    """resume=False → 先清断点，全部重下。"""
    column_setup(fakes, count=3)
    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    for i in (1, 2):
        store.put_chapter(f"{COLUMN}/section/{i}", article_for(f"{COLUMN}/section/{i}", f"第{i}章"))
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in (1, 2, 3):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    session = FakeSession(pages)

    result = download_book(make_client(session), COLUMN, output_dir=tmp_path,
                           resume=False, workers=1)

    assert result.skipped_existing == 0
    assert session.count(f"{COLUMN}/section/1") == 1
    assert session.count(f"{COLUMN}/section/2") == 1


def test_download_book_resume_false_recovers_from_corrupt_state(
    fakes: Fakes, tmp_path: Path
) -> None:
    """损坏恢复：resume=False 时 clear() 直接删掉坏状态并完整重下。

    旧断言钉「跑完状态文件不存在」（成功即清）；R1-M4 主审裁决后，重下成功
    会重新写出**有效**断点——这里改钉「坏文件被替换成可加载的新状态」。
    """
    column_setup(fakes, count=2)
    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("{坏掉了", encoding="utf-8")
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in (1, 2):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    session = FakeSession(pages)

    result = download_book(make_client(session), COLUMN, output_dir=tmp_path, resume=False)

    assert result.chapters == 2
    assert store.load()["done_urls"] == [f"{COLUMN}/section/1", f"{COLUMN}/section/2"]


def test_download_book_corrupt_state_raises_checkpoint_error(fakes: Fakes, tmp_path: Path) -> None:
    """断点文件损坏 → CheckpointError（中文提示），不静默覆盖。"""
    column_setup(fakes, count=2)
    state_dir = tmp_path / DEFAULT_STATE_SUBDIR
    store = CheckpointStore(state_dir, COLUMN)
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("{坏掉了", encoding="utf-8")
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})

    with pytest.raises(CheckpointError):
        download_book(make_client(session), COLUMN, output_dir=tmp_path)


# ----------------------------------------------------------------------
# download_book：失败与重试
# ----------------------------------------------------------------------

def test_download_book_aborts_and_keeps_checkpoint_for_resume(
    fakes: Fakes, tmp_path: Path
) -> None:
    """单章最终失败：中止整本 + emit(error)，已完成章节留在断点。"""
    column_setup(fakes, count=3)
    pages: dict[str, Any] = {
        COLUMN: FakeResponse(200, "目录页HTML"),
        f"{COLUMN}/section/1": FakeResponse(200, "章"),
        f"{COLUMN}/section/2": FakeResponse(403),
    }
    session = FakeSession(pages)
    events, emit = collect_events()

    with pytest.raises(ZhihuError, match="HTTP 403"):
        download_book(make_client(session), COLUMN, output_dir=tmp_path,
                      progress=emit, workers=1)

    assert [e.kind for e in events] == ["toc", "chapter", "error"]
    assert events[-1].message.count("第2章") >= 1
    assert "可续传" in events[-1].message
    assert f"{COLUMN}/section/3" not in session.calls  # 中止后不再消耗请求

    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    assert store.get_done_urls() == {f"{COLUMN}/section/1"}
    assert fakes.export_calls == []  # 未导出

    # 修好之后重跑：自动续传，只补第 2、3 章
    session2 = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                            f"{COLUMN}/section/2": FakeResponse(200, "章"),
                            f"{COLUMN}/section/3": FakeResponse(200, "章")})
    events2, emit2 = collect_events()
    result = download_book(make_client(session2), COLUMN, output_dir=tmp_path,
                           progress=emit2, workers=1)
    assert result.skipped_existing == 1
    assert [e.kind for e in events2] == ["toc", "chapter", "chapter", "export", "done"]
    assert fakes.export_calls[-1]["titles"] == ["第1章", "第2章", "第3章"]


def test_download_book_emits_retry_events_and_restores_hook(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """client 内部重试被转成 retry 事件；下载结束后 on_retry 回调被还原。"""
    monkeypatch.setattr(client_mod, "time", FakeClock())
    column_setup(fakes, count=1)
    pages: dict[str, Any] = {
        COLUMN: FakeResponse(200, "目录页HTML"),
        f"{COLUMN}/section/1": [FakeResponse(503), FakeResponse(200, "章")],  # 见下
    }
    session = FakeSession(pages)
    # 让第 1 章第一次拿到 503、第二次拿到 200
    queue = [FakeResponse(503), FakeResponse(200, "章")]
    session.pages[f"{COLUMN}/section/1"] = lambda _url: queue.pop(0)
    events, emit = collect_events()
    client = make_client(session, retries=2)
    assert client.on_retry is None

    result = download_book(client, COLUMN, output_dir=tmp_path, progress=emit, workers=1)

    kinds = [e.kind for e in events]
    assert kinds == ["toc", "retry", "chapter", "export", "done"]
    retry = events[1]
    assert retry.title == "第1章"
    assert "第 1 次重试" in retry.message and "HTTP 503" in retry.message
    assert result.chapters == 1
    assert client.on_retry is None  # 不污染共享客户端


def test_download_book_export_failure_emits_error_and_keeps_checkpoint(
    fakes: Fakes, tmp_path: Path
) -> None:
    """R1-m7：导出失败也要发 error 事件（§2.3 失败路径），断点保留供直接重导出。"""
    column_setup(fakes, count=2)
    fakes.export_error = ExportError("磁盘空间不足，请清理后重试")
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in (1, 2):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    session = FakeSession(pages)
    events, emit = collect_events()

    with pytest.raises(ExportError, match="磁盘空间不足"):
        download_book(make_client(session), COLUMN, output_dir=tmp_path, progress=emit)

    assert [e.kind for e in events] == ["toc", "chapter", "chapter", "export", "error"]
    err = events[-1]
    assert err.title == "测试专栏"
    assert "导出 md 失败" in err.message and "磁盘空间不足" in err.message
    assert "重跑同一命令即可重新导出" in err.message  # 中文可操作提示
    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    assert store.get_done_urls() == {f"{COLUMN}/section/1", f"{COLUMN}/section/2"}

    # 修好后重跑：一章都不重抓，直接重新导出成功（断点保留的价值所在）
    fakes.export_error = None
    session2 = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})
    events2, emit2 = collect_events()
    result = download_book(make_client(session2), COLUMN, output_dir=tmp_path,
                           progress=emit2, workers=2)
    assert result.skipped_existing == 2
    assert session2.calls == [COLUMN]  # 只请求目录页
    assert [e.kind for e in events2] == ["toc", "export", "done"]


def test_download_book_parse_failure_reports_chapter(fakes: Fakes, tmp_path: Path) -> None:
    """正文解析失败：错误消息指明是哪一章，断点保留。"""
    column_setup(fakes, count=2)
    fakes.articles.pop(f"{COLUMN}/section/2")  # 假解析器对该章抛 ParseError
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in (1, 2):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    session = FakeSession(pages)

    with pytest.raises(ParseError):
        download_book(make_client(session), COLUMN, output_dir=tmp_path, workers=1)

    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    assert store.get_done_urls() == {f"{COLUMN}/section/1"}


# ----------------------------------------------------------------------
# R1 修复回归：M2 钩子竞态 / m1 坏缓存自愈 / M4 成功后保留断点
# ----------------------------------------------------------------------

def test_download_book_concurrent_shared_client_hook_isolation(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1-M2：两线程共用一个 client 各跑一次 download_book。

    钉两件事：① 双双结束后 client.on_retry 恢复原值（None），不残留钩子；
    ② retry 事件只进「该章所属任务」的进度回调，不互串。旧实现是各自直接
    覆盖/还原 on_retry：后安装者覆盖先安装者的钩子（先安装者的重试被塞进
    后安装者的进度流），后还原者又会把先还原者的「还原」覆盖回去（钩子泄漏）。
    """
    monkeypatch.setattr(client_mod, "time", FakeClock())
    col_a = "https://www.zhihu.com/market/paid_column/1111"
    col_b = "https://www.zhihu.com/market/paid_column/2222"
    fakes.url_types[col_a] = "column"
    fakes.url_types[col_b] = "column"
    fakes.toc = [
        ChapterRef(url=f"{col_a}/section/1", title="A1", index=1),
        ChapterRef(url=f"{col_a}/section/2", title="A2", index=2),
        ChapterRef(url=f"{col_b}/section/1", title="B1", index=1),
        ChapterRef(url=f"{col_b}/section/2", title="B2", index=2),
    ]
    fakes.page_titles["目录A"] = "书A"
    fakes.page_titles["目录B"] = "书B"
    for url, title in ((f"{col_a}/section/1", "A1"), (f"{col_a}/section/2", "A2"),
                       (f"{col_b}/section/1", "B1"), (f"{col_b}/section/2", "B2")):
        fakes.articles[url] = article_for(url, title)
    # 每章第一次 503、第二次 200 → 每章恰好产生一个 retry 事件
    queues: dict[str, list[FakeResponse]] = {}

    def flaky(_url: str) -> FakeResponse:
        q = queues.setdefault(_url, [FakeResponse(503), FakeResponse(200, "章")])
        return q.pop(0) if q else FakeResponse(200, "章")

    pages: dict[str, Any] = {col_a: FakeResponse(200, "目录A"),
                             col_b: FakeResponse(200, "目录B")}
    for c in (col_a, col_b):
        for i in (1, 2):
            pages[f"{c}/section/{i}"] = flaky
    session = FakeSession(pages)
    client = make_client(session, retries=2)
    # 解析延时让两任务的钩子注册期确定重叠（否则测不到并发覆盖）
    fakes.parse_delays = {f"{c}/section/{i}": 0.1 for c in (col_a, col_b) for i in (1, 2)}

    events: dict[str, list[ProgressEvent]] = {"A": [], "B": []}
    results: dict[str, Any] = {}
    errors: list[BaseException] = []
    gate = threading.Barrier(2, timeout=10)

    def run(name: str, url: str) -> None:
        try:
            gate.wait()
            results[name] = download_book(client, url, output_dir=tmp_path,
                                          progress=events[name].append, workers=1)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=run, args=("A", col_a))
    t2 = threading.Thread(target=run, args=("B", col_b))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert errors == []
    assert results["A"].chapters == 2 and results["B"].chapters == 2
    assert client.on_retry is None  # ① 原值还原，无 dispatcher/钩子残留
    for name, own in (("A", {"A1", "A2"}), ("B", {"B1", "B2"})):
        retries = [e for e in events[name] if e.kind == "retry"]
        assert len(retries) == 2, f"{name} 的重试事件被别的任务覆盖丢失"  # ②
        assert {e.title for e in retries} == own, f"{name} 串进了别的任务的 retry 事件"


def test_download_book_preserves_and_chains_user_on_retry(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1-M2：用户自己挂在 client.on_retry 上的钩子照常收到重试，结束后原样还原。"""
    monkeypatch.setattr(client_mod, "time", FakeClock())
    column_setup(fakes, count=1)
    queue = [FakeResponse(503), FakeResponse(200, "章")]
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": lambda _u: queue.pop(0)})
    client = make_client(session, retries=2)
    seen: list[tuple[str, int]] = []

    def user_hook(url: str, attempt: int, delay: float, reason: str) -> None:
        seen.append((url, attempt))

    client.on_retry = user_hook
    events, emit = collect_events()

    download_book(client, COLUMN, output_dir=tmp_path, progress=emit, workers=1)

    assert seen == [(f"{COLUMN}/section/1", 1)]  # 下载期间用户钩子照常收到重试
    assert client.on_retry is user_hook          # 结束后原样还原，不残留 dispatcher
    assert [e.kind for e in events] == ["toc", "retry", "chapter", "export", "done"]


def test_download_book_resume_refetches_corrupt_chapter_end_to_end(
    fakes: Fakes, tmp_path: Path
) -> None:
    """R1-m1 端到端（R1 点名的盲区：单测钉局部、集成漏钉）：写坏一章 body → resume 成功出书。

    坏章被 get_done_urls 的「存在且可解析」判定视为未完成 → 走正常重抓管线；
    好章照常从缓存读回；导出完整；全程不抛 ParseError、不逼用户 --no-resume。
    """
    column_setup(fakes, count=3)
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in (1, 2, 3):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    download_book(make_client(FakeSession(pages)), COLUMN, output_dir=tmp_path, workers=2)

    store = CheckpointStore(tmp_path / DEFAULT_STATE_SUBDIR, COLUMN)
    store.chapter_path(f"{COLUMN}/section/2").write_text("{截断的坏 JSON", encoding="utf-8")

    # 第二次会话故意不提供第 1、3 章页面：若被误重抓会 404 → 测试失败
    session2 = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                            f"{COLUMN}/section/2": FakeResponse(200, "章")})
    events, emit = collect_events()
    result = download_book(make_client(session2), COLUMN, output_dir=tmp_path,
                           progress=emit, workers=1)

    assert result.skipped_existing == 2                    # 只有坏章算未完成
    assert result.chapters == 3
    assert session2.count(f"{COLUMN}/section/2") == 1      # 坏章现场重抓
    assert f"{COLUMN}/section/1" not in session2.calls     # 好章不受牵连
    assert [e.kind for e in events] == ["toc", "chapter", "export", "done"]
    assert fakes.export_calls[-1]["titles"] == ["第1章", "第2章", "第3章"]
    assert store.get_article(f"{COLUMN}/section/2") is not None  # 缓存已修复


def test_download_book_self_heals_when_cache_vanishes_before_export(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1-m1 兜底：跳过「已完成」章后、导出前缓存又被并发任务删掉 → 现场自愈重抓回填。

    模拟竞态：get_done_urls 时还在（全部跳过），_collect_articles 读回时已不可用。
    旧行为是抛 ParseError 让用户 --no-resume 全量重下（死路）；新行为是重抓该章。
    """
    column_setup(fakes, count=2)
    monkeypatch.setattr(
        CheckpointStore, "get_done_urls",
        lambda self: {f"{COLUMN}/section/1", f"{COLUMN}/section/2"},
    )
    monkeypatch.setattr(CheckpointStore, "get_article", lambda self, url: None)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                           f"{COLUMN}/section/1": FakeResponse(200, "章"),
                           f"{COLUMN}/section/2": FakeResponse(200, "章")})

    result = download_book(make_client(session), COLUMN, output_dir=tmp_path, workers=1)

    assert result.chapters == 2
    assert session.count(f"{COLUMN}/section/1") == 1
    assert session.count(f"{COLUMN}/section/2") == 1
    assert fakes.export_calls[0]["titles"] == ["第1章", "第2章"]


def test_download_book_second_run_reexports_without_refetch(
    fakes: Fakes, tmp_path: Path
) -> None:
    """R1-M4（主审裁决）：成功后保留断点 → 同链接重跑只请求目录页，秒级重导出。"""
    column_setup(fakes, count=3)
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in (1, 2, 3):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    download_book(make_client(FakeSession(pages)), COLUMN, output_dir=tmp_path, workers=2)

    session2 = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})
    events, emit = collect_events()
    result = download_book(make_client(session2), COLUMN, output_dir=tmp_path,
                           progress=emit, workers=2)

    assert result.skipped_existing == 3
    assert result.chapters == 3
    assert session2.calls == [COLUMN]  # 一章都没重抓（重抓会 404 直接失败）
    assert [e.kind for e in events] == ["toc", "export", "done"]
    assert fakes.export_calls[-1]["titles"] == ["第1章", "第2章", "第3章"]


def test_download_book_update_fetches_only_new_chapters(
    fakes: Fakes, tmp_path: Path
) -> None:
    """R1-M4 + README 承诺「追更只下新增章节」：目录新增第 3 章后重跑，只抓第 3 章。"""
    column_setup(fakes, count=2)
    pages: dict[str, Any] = {COLUMN: FakeResponse(200, "目录页HTML")}
    for i in (1, 2):
        pages[f"{COLUMN}/section/{i}"] = FakeResponse(200, "章")
    download_book(make_client(FakeSession(pages)), COLUMN, output_dir=tmp_path, workers=1)

    column_setup(fakes, count=3)  # 作者更新了：目录多出第 3 章
    session2 = FakeSession({COLUMN: FakeResponse(200, "目录页HTML"),
                            f"{COLUMN}/section/3": FakeResponse(200, "章")})
    result = download_book(make_client(session2), COLUMN, output_dir=tmp_path, workers=1)

    assert result.skipped_existing == 2
    assert result.chapters == 3
    assert session2.calls == [COLUMN, f"{COLUMN}/section/3"]  # 只抓新章
    assert fakes.export_calls[-1]["titles"] == ["第1章", "第2章", "第3章"]


# ----------------------------------------------------------------------
# check_new_chapters
# ----------------------------------------------------------------------

def test_download_book_self_heal_refetch_failure_emits_error(
    fakes: Fakes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1-m1/m7 失败路径：自愈重抓也失败（如章页 404）→ 发 error 事件（中文提示）并抛错。"""
    column_setup(fakes, count=1)
    monkeypatch.setattr(CheckpointStore, "get_done_urls",
                        lambda self: {f"{COLUMN}/section/1"})
    monkeypatch.setattr(CheckpointStore, "get_article", lambda self, url: None)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})  # 无章页 → 重抓 404
    events, emit = collect_events()

    with pytest.raises(ZhihuError, match="404"):
        download_book(make_client(session), COLUMN, output_dir=tmp_path,
                      progress=emit, workers=1)

    assert [e.kind for e in events] == ["toc", "error"]
    assert "章节正文取回失败" in events[-1].message
    assert "重跑同一命令即可续传" in events[-1].message


def test_check_new_chapters_returns_unknown_in_toc_order(fakes: Fakes) -> None:
    """追更 diff：只返回未下载章节，保持目录顺序。"""
    column_setup(fakes, count=4)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})

    new = check_new_chapters(make_client(session), COLUMN,
                             [f"{COLUMN}/section/1", f"{COLUMN}/section/3"])

    assert [ch.index for ch in new] == [2, 4]
    assert [ch.title for ch in new] == ["第2章", "第4章"]


def test_check_new_chapters_empty_when_all_known(fakes: Fakes) -> None:
    """无新章节 → 空列表（书架追更据此提示「已最新」）。"""
    column_setup(fakes, count=2)
    session = FakeSession({COLUMN: FakeResponse(200, "目录页HTML")})

    new = check_new_chapters(make_client(session), COLUMN,
                             [f"{COLUMN}/section/1", f"{COLUMN}/section/2", ""])

    assert new == []


def test_check_new_chapters_propagates_unsupported_url(fakes: Fakes) -> None:
    """追更同样拒绝仅 APP 内阅读链接。"""
    fakes.url_types[APP_URL] = "app_section"
    with pytest.raises(UnsupportedUrlError):
        check_new_chapters(make_client(FakeSession({})), APP_URL, [])
