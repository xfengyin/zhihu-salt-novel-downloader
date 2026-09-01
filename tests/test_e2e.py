"""端到端验收测试（主审编写，定义"可运行重构版"的完成标准）。

在 requests.Session 边界 mock（规格书 §4 铁律），其余全链路真实：
client → fetcher → parse → cleaner → export → shelf → checkpoint 续传。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# fixtures：仿知乎页面
# ---------------------------------------------------------------------------

TOC_HTML = """<html><head><title>测试专栏</title></head><body>
<div class="ColumnCatalog">
  <a href="/market/paid_column/123/section/1">第一章 初入江湖</a>
  <a href="/market/paid_column/123/section/2">第二章 风波</a>
  <a href="/market/paid_column/123/section/3">番外 后记</a>
</div></body></html>"""

def section_html(n: int) -> str:
    return f"""<html><head><meta property="og:title" content="第{n}章 测试" /></head>
<body><div class="RichText">
<h2>小节 {n}A</h2>
<p>这是第{n}章的正文段落，内容足够长不会被当垃圾。</p>
<p>关注公众号领取福利</p>
<p><img data-original="https://picx.zhimg.com/img{n}.jpg" alt="插图" /></p>
<blockquote>引用一句题记</blockquote>
</div></body></html>"""

COLUMN_URL = "https://www.zhihu.com/market/paid_column/123"
SECTION_URLS = [f"{COLUMN_URL}/section/{i}" for i in (1, 2, 3)]


class FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.content = text.encode()

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """路由 URL → fixture HTML；记录调用；可注入故障。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_urls: set[str] = set()
        self.headers: dict[str, str] = {}
        self.cookies = FakeCookieJar()

    def get(self, url: str, headers: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append(url)
        if url in self.fail_urls:
            import requests as _rq
            raise _rq.ConnectionError("模拟网络抖动")
        if url == COLUMN_URL:
            return FakeResponse(TOC_HTML)
        if url in SECTION_URLS:
            n = SECTION_URLS.index(url) + 1
            return FakeResponse(section_html(n))
        return FakeResponse("<html><body>404</body></html>", 404)


class FakeCookieJar(dict):
    def update(self, other=None, **kw):  # type: ignore[override]
        if other:
            super().update(other)


def make_client(tmp_path: Path) -> tuple[Any, FakeSession]:
    from zhihu_downloader.engine.client import ZhihuClient
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({"z_c0": "v", "zse_ck": "s", "d_c0": "dc"}), encoding="utf-8")
    client = ZhihuClient(cookie_file=cookie_file, rate_limit=0)
    fake = FakeSession()
    client.session = fake
    return client, fake


# ---------------------------------------------------------------------------
# 1. 专栏全链路下载
# ---------------------------------------------------------------------------

def test_column_download_end_to_end(tmp_path: Path) -> None:
    from zhihu_downloader.engine.fetcher import download_book

    client, fake = make_client(tmp_path)
    events: list[Any] = []
    result = download_book(client, COLUMN_URL, fmt="md", output_dir=tmp_path / "out",
                           progress=events.append, workers=2)

    assert result.title == "测试专栏"
    assert result.chapters == 3
    assert len(result.files) == 1 and result.files[0].endswith(".md")
    md = Path(result.files[0]).read_text(encoding="utf-8")
    # 结构保留（v5 关键升级）
    assert "## 小节 1A" in md
    assert "> 引用一句题记" in md
    assert "![插图](https://picx.zhimg.com/img1.jpg)" in md
    # 广告被清洗
    assert "关注公众号" not in md
    # 番外分类（TOC 标题分类）
    assert "番外" in md
    # 请求序列：目录 + 3 章
    assert fake.calls[0] == COLUMN_URL
    assert sorted(fake.calls[1:]) == sorted(SECTION_URLS)
    # 进度事件协议
    kinds = [e.kind for e in events]
    assert kinds[0] == "toc"
    assert kinds.count("chapter") == 3
    assert kinds[-1] == "done"
    done = events[-1]
    assert done.total == 3 and done.current == 3
    # R1-M4 主审裁决（v5.0）：成功后保留断点 state+bodies——同链接重跑=秒级重导出、
    # 追更只抓新章；清理入口是 --no-resume 与书架移除 prune，不再是"成功即清"。
    state = tmp_path / "out" / ".zhihu_state"
    assert state.exists() and list(state.glob("*.json")), "成功后应保留断点供追更复用"


# ---------------------------------------------------------------------------
# 2. 断点续传：中途失败 → 已完成章节不重取
# ---------------------------------------------------------------------------

def test_resume_after_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from zhihu_downloader.engine import client as _client_mod
    from zhihu_downloader.engine.fetcher import download_book
    from zhihu_downloader.errors import ZhihuError

    monkeypatch.setattr(_client_mod.time, "sleep", lambda s: None)  # R1-m8：退避不真睡

    client, fake = make_client(tmp_path)
    fake.fail_urls.add(SECTION_URLS[1])  # 第二章网络故障（重试耗尽后整本中止）
    with pytest.raises(ZhihuError):
        download_book(client, COLUMN_URL, fmt="md", output_dir=tmp_path / "out", workers=1)
    first_round = list(fake.calls)
    # 失败轮里：第一章在失败点之前，已成功抓取并入断点
    assert SECTION_URLS[0] in first_round

    # 修复故障，续传：第一章不应重新请求
    fake.fail_urls.clear()
    fake.calls.clear()
    result = download_book(client, COLUMN_URL, fmt="md", output_dir=tmp_path / "out",
                           resume=True, workers=1)
    assert result.chapters == 3
    assert SECTION_URLS[0] not in fake.calls  # 已续传跳过
    assert SECTION_URLS[1] in fake.calls      # 失败章重取


# ---------------------------------------------------------------------------
# 3. APP 独占 URL → 明确中文提示 + 替代方案
# ---------------------------------------------------------------------------

def test_app_only_url_friendly_error(tmp_path: Path) -> None:
    from zhihu_downloader.engine.fetcher import resolve_book
    from zhihu_downloader.errors import UnsupportedUrlError

    client, _ = make_client(tmp_path)
    with pytest.raises(UnsupportedUrlError) as ei:
        resolve_book(client, "https://story.zhihu.com/manuscript/paid_column/123")
    msg = str(ei.value)
    assert "www.zhihu.com/market/paid_column/123" in msg  # 给出替换 URL


# ---------------------------------------------------------------------------
# 4. 单章节下载
# ---------------------------------------------------------------------------

def test_single_section_download(tmp_path: Path) -> None:
    from zhihu_downloader.engine.fetcher import download_book

    client, _ = make_client(tmp_path)
    result = download_book(client, SECTION_URLS[0], fmt="txt", output_dir=tmp_path / "out")
    assert result.chapters == 1
    txt = Path(result.files[0]).read_text(encoding="utf-8")
    assert "这是第1章的正文段落" in txt
    assert "小节 1A" in txt


# ---------------------------------------------------------------------------
# 5. 书架 + 追更
# ---------------------------------------------------------------------------

def test_shelf_and_updates(tmp_path: Path) -> None:
    from zhihu_downloader.engine.fetcher import check_new_chapters, download_book
    from zhihu_downloader.shelf.shelf import Shelf

    client, fake = make_client(tmp_path)
    result = download_book(client, COLUMN_URL, fmt="md", output_dir=tmp_path / "out")

    shelf = Shelf(path=tmp_path / "shelf.json")
    book = shelf.record_download(result, "md", chapter_urls=list(SECTION_URLS))
    assert shelf.get(book.id) is not None

    # 目录新增第 4 章 → check_new_chapters 只返回新章
    new_toc = TOC_HTML.replace(
        "</div></body>",
        '  <a href="/market/paid_column/123/section/4">第四章 结局</a>\n</div></body>')
    orig_get = fake.get
    def get2(url, headers=None, timeout=None):
        if url == COLUMN_URL:
            return FakeResponse(new_toc)
        if url.endswith("/section/4"):
            return FakeResponse(section_html(4))
        return orig_get(url, headers, timeout)
    fake.get = get2

    news = check_new_chapters(client, COLUMN_URL, list(SECTION_URLS))
    assert [c.url for c in news] == [f"{COLUMN_URL}/section/4"]


# ---------------------------------------------------------------------------
# 6. EPUB 导出链路（读回验证）
# ---------------------------------------------------------------------------

def test_epub_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("ebooklib")
    from zhihu_downloader.engine.fetcher import download_book

    client, _ = make_client(tmp_path)
    result = download_book(client, COLUMN_URL, fmt="epub", output_dir=tmp_path / "out")
    epub_path = Path(result.files[0])
    assert epub_path.exists() and epub_path.suffix == ".epub"

    from ebooklib import epub as _epub
    book = _epub.read_epub(str(epub_path))
    assert book.get_metadata("DC", "title")[0][0] == "测试专栏"
    chapters = [i for i in book.get_items() if i.get_type() == 9]  # ITEM_DOCUMENT
    assert len(chapters) >= 3  # 3 章 + nav/ncx
