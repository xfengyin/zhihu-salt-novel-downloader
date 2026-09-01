"""app/server.py 测试（规格书 §4）：TestClient 全端点 + SSRF 400 + SSE 事件流 + 文件穿越防护。

全部离线：mock 只打在 ZhihuClient.fetch（等价于 requests.Session 边界，参考
tests/test_e2e.py 的 FakeSession 写法）；扫码端点用 monkeypatch 桩替换 auth.qr
三函数并断言"传的是应用客户端实例"这一委托契约。
"""

from __future__ import annotations

import hashlib
import json
import logging
import stat
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import zhihu_downloader.app.server as server_module
from zhihu_downloader import __version__
from zhihu_downloader.app import create_app
from zhihu_downloader.engine.client import ZhihuClient
from zhihu_downloader.errors import AuthError, ZhihuError
from zhihu_downloader.shelf.shelf import Shelf

# ---------------------------------------------------------------------------
# fixture 页面（与 test_e2e.py 同风格）
# ---------------------------------------------------------------------------

TOC_HTML = """<html><head><title>测试专栏</title></head><body>
<div class="ColumnCatalog">
  <a href="/market/paid_column/123/section/1">第一章 初入江湖</a>
  <a href="/market/paid_column/123/section/2">第二章 风波</a>
  <a href="/market/paid_column/123/section/3">番外 后记</a>
</div></body></html>"""

TOC_HTML_V2 = TOC_HTML.replace(
    "</div></body>",
    '  <a href="/market/paid_column/123/section/4">第四章 结局</a>\n</div></body>')

def section_html(n: int) -> str:
    return f"""<html><head><meta property="og:title" content="第{n}章 测试" /></head>
<body><div class="RichText">
<h2>小节 {n}A</h2>
<p>这是第{n}章的正文段落，内容足够长不会被当垃圾。</p>
</div></body></html>"""

COLUMN_URL = "https://www.zhihu.com/market/paid_column/123"
SECTION_URLS = [f"{COLUMN_URL}/section/{i}" for i in (1, 2, 3, 4)]


class FakeSite:
    """路由 URL -> fixture HTML；记录调用；可注入故障/阻塞（全部离线）。"""

    def __init__(self) -> None:
        self.pages: dict[str, str] = {
            COLUMN_URL: TOC_HTML,
            **{SECTION_URLS[i]: section_html(i + 1) for i in range(3)},
        }
        self.fail: set[str] = set()
        self.block: dict[str, threading.Event] = {}
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def fetch(self, url: str) -> str:
        with self._lock:
            self.calls.append(url)
        gate = self.block.get(url)
        if gate is not None:
            gate.wait(10)
        if url in self.fail:
            raise ZhihuError("模拟故障：" + url)
        page = self.pages.get(url)
        if page is None:
            raise ZhihuError("模拟 404：" + url)
        return page


def _wait_until(predicate: Callable[[], bool], timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """一个带 FakeSite 的完整应用：create_app + TestClient（含 lifespan）。"""
    site = FakeSite()
    monkeypatch.setattr(ZhihuClient, "fetch", lambda self, url: site.fetch(url))

    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps({"z_c0": "SECRET_Z_C0", "d_c0": "SECRET_D_C0"}), encoding="utf-8")
    client = ZhihuClient(cookie_file=cookie_file, rate_limit=0)
    shelf = Shelf(path=tmp_path / "shelf.json")
    app = create_app(client=client, output_dir=tmp_path / "out", shelf=shelf)

    with TestClient(app) as http:
        e = SimpleNamespace(
            site=site, client=client, shelf=shelf, app=app, http=http,
            state=app.state.zhihu, tmp=tmp_path, cookie_file=cookie_file)
        yield e


def download(env: SimpleNamespace, url: str = COLUMN_URL,
             **payload: Any) -> str:
    """POST /api/download 并返回 task_id（状态可能已是 running：worker 秒启动）。"""
    resp = env.http.post("/api/download", json={"url": url, **payload})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("pending", "running", "done", "error")
    return body["task_id"]


def wait_task(env: SimpleNamespace, task_id: str, timeout: float = 20.0) -> dict:
    """等任务终态并返回详情快照。"""
    task = env.state.tasks.get(task_id)
    assert task is not None, "任务不在表里"
    assert task.finished.wait(timeout), "任务超时未结束"
    return task.snapshot()


def read_sse(env: SimpleNamespace, task_id: str,
             client: TestClient | None = None) -> tuple[list[dict], bool, dict]:
    """流式读完 SSE：返回 (ProgressEvent 列表, 是否收到 [DONE], 响应头)。

    client 可注入独立 TestClient（M3 并发双连接用例用，各连接游标独立）。
    """
    events: list[dict] = []
    saw_done = False
    http = client if client is not None else env.http
    with http.stream("GET", f"/api/tasks/{task_id}/events") as resp:
        headers = dict(resp.headers)
        for line in resp.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload == "[DONE]":
                saw_done = True
                continue
            events.append(json.loads(payload))
    return events, saw_done, headers


# ---------------------------------------------------------------------------
# 0. 工厂模式与版本单源（§2.14 安全 / v4 教训）
# ---------------------------------------------------------------------------

def test_no_module_level_app_instance() -> None:
    """模块底部不放 app=create_app()：import server 不得产生实例。"""
    assert not hasattr(server_module, "app")
    from zhihu_downloader.app import create_app as reexported
    assert reexported is server_module.create_app


def test_create_app_is_pure_factory() -> None:
    """create_app() 无参可调用（默认值齐备）且返回 FastAPI，不建线程池。"""
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.version == __version__
    state = app.state.zhihu
    assert state.tasks.limit == 50  # LRU 上限 50（§2.14）
    assert state._executor is None  # 懒创建：没提交任务就没有线程池


def test_health_version_single_source(env: SimpleNamespace) -> None:
    resp = env.http.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "version": __version__}


# ---------------------------------------------------------------------------
# 1. SSRF 防护：非知乎域一律 400（中文），且不创建任务
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_url", [
    "https://example.com/article/1",                      # 普通外域
    "http://zhihu.com.evil.co/market/paid_column/1",      # 仿冒域（后缀伪装）
    "https://notzhihu.com/market/paid_column/1",          # 前后缀粘连伪装
    "http://zhihu.com@evil.com/x",                        # userinfo 注入
    "https://evil.com/?next=https://www.zhihu.com/",      # 参数藏真域
    "javascript:fetch('http://evil.com')//www.zhihu.com", # 协议注入
    "file://zhihu.com/etc/passwd",                        # file 协议（无 hostname 语义）
    "http://127.0.0.1:8080/market/paid_column/1",         # 内网 IP（SSRF 典型目标）
    "zhihu.com/market/paid_column/1",                     # 缺 scheme
    "https://",                                           # 空 host
    "https://zhihu.com.evil.co",                          # 仿冒域裸形
])
def test_ssrf_rejected_with_chinese_400(env: SimpleNamespace, bad_url: str) -> None:
    resp = env.http.post("/api/download", json={"url": bad_url, "format": "md"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "知乎" in detail and "拒绝" in detail  # 中文、可操作
    assert env.http.get("/api/tasks").json() == []  # 校验发生在建任务之前


@pytest.mark.parametrize("good_url", [
    "https://www.zhihu.com/market/paid_column/123",
    "https://zhihu.com/market/paid_column/123",
    "https://m.zhihu.com/market/paid_column/123",
    "HTTPS://WWW.ZHIHU.COM/market/paid_column/123",  # 大小写不敏感
])
def test_zhihu_domains_pass_gate(env: SimpleNamespace, good_url: str) -> None:
    resp = env.http.post("/api/download", json={"url": good_url, "format": "md"})
    assert resp.status_code == 200
    assert resp.json()["task_id"]


def test_empty_url_rejected(env: SimpleNamespace) -> None:
    resp = env.http.post("/api/download", json={"url": "   "})
    assert resp.status_code == 400
    assert "链接" in resp.json()["detail"]


def test_format_validation(env: SimpleNamespace) -> None:
    resp = env.http.post("/api/download",
                         json={"url": COLUMN_URL, "format": "docx"})
    assert resp.status_code == 400
    assert "格式" in resp.json()["detail"]
    # 大小写归一：EPUB 合法
    resp = env.http.post("/api/download",
                         json={"url": COLUMN_URL, "format": "EPUB"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. 下载全链路 + SSE 事件流 + 任务详情/列表 + 书架自动登记
# ---------------------------------------------------------------------------

def test_download_sse_full_flow(env: SimpleNamespace) -> None:
    task_id = download(env)
    events, saw_done, headers = read_sse(env, task_id)

    # SSE 头：text/event-stream + no-cache（§2.14 要求 5）
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"

    kinds = [e["kind"] for e in events]
    assert kinds[0] == "toc"
    assert kinds.count("chapter") == 3          # 每章一个进度事件
    assert kinds[-1] == "done"                  # 正常路径以 done 收尾
    assert kinds[-2] == "export"
    assert events[0]["total"] == 3
    assert events[-1]["current"] == 3
    assert saw_done, "必须以 data: [DONE] 收尾"

    detail = env.http.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "done"
    assert detail["title"] == "测试专栏"
    assert detail["progress"]["current"] == 3 and detail["progress"]["total"] == 3
    assert len(detail["files"]) == 1 and detail["files"][0].endswith(".md")
    # 导出文件落在 output_dir 根；工作目录成功后保留断点现场（R1-M4 裁决：
    # state+bodies 留存=同链接秒级重导出，清理入口是书架移除 prune）
    assert Path(detail["files"][0]).parent == env.tmp / "out"
    assert Path(detail["files"][0]).read_text(encoding="utf-8").count("小节") >= 3
    state_dir = task_key_dir(env, COLUMN_URL) / ".zhihu_state"
    assert list(state_dir.glob("*.json")), "R1-M4：成功后断点 state 必须保留"

    listed = env.http.get("/api/tasks").json()
    assert any(t["id"] == task_id for t in listed)

    # 下载成功自动登记书架（含 chapter_urls，供「检查更新」精确 diff）
    books = env.http.get("/api/shelf").json()
    assert len(books) == 1
    assert books[0]["title"] == "测试专栏"
    assert sorted(books[0]["chapter_urls"]) == sorted(SECTION_URLS[:3])
    assert books[0]["fmt"] == "md"


def test_meta_reuse_single_toc_fetch(env: SimpleNamespace) -> None:
    """标准记账通路（E1 追加轮）：resolve_book 的目录结果经 download_book(meta=)
    复用——普通下载与追更各自只抓一次目录页（对齐 test_fetcher 的同型用例）。"""
    task_id = download(env)
    wait_task(env, task_id)
    assert env.site.calls.count(COLUMN_URL) == 1, "目录页不得被重抓（meta= 复用）"

    book = env.http.get("/api/shelf").json()[0]
    assert sorted(book["chapter_urls"]) == sorted(SECTION_URLS[:3])  # 记账来自 meta
    env.site.pages[COLUMN_URL] = TOC_HTML_V2
    env.site.pages[SECTION_URLS[3]] = section_html(4)
    body = env.http.post(f"/api/shelf/{book['id']}/update").json()
    assert body["updated"] is True and body["new_chapters"] == 1
    detail = wait_task(env, body["task_id"])
    assert detail["status"] == "done"
    # 追更全程只多抓一次目录（diff 用的 resolve，worker 经 meta= 复用）
    assert env.site.calls.count(COLUMN_URL) == 2
    after = env.http.get("/api/shelf").json()[0]
    assert sorted(after["chapter_urls"]) == sorted(SECTION_URLS[:4])


def test_sse_second_connect_replays_full_events(env: SimpleNamespace) -> None:
    """M3（R1 审查）：旧钉把「单队列分食」缺陷钉成了规格——重连只余 [DONE]。

    广播模型下每条连接独立游标：第一连接读完全部事件后，第二连接必须重放到
    同样的全量事件（刷新/双标签页不再各见半截），且任务已终态时读完即
    [DONE] 收尾、不挂死。
    """
    task_id = download(env)
    first, done1, _ = read_sse(env, task_id)
    assert done1 and first, "前置：第一连接拿到全量事件"
    events, saw_done, _ = read_sse(env, task_id)
    assert saw_done, "重连必须及时 [DONE] 收尾（不挂死）"
    assert events == first, "重连必须重放出与首连完全相同的全量事件"


def test_sse_unknown_task_404(env: SimpleNamespace) -> None:
    resp = env.http.get("/api/tasks/nope123/events")
    assert resp.status_code == 404
    assert "任务" in resp.json()["detail"]


def test_task_detail_404(env: SimpleNamespace) -> None:
    resp = env.http.get("/api/tasks/nope123")
    assert resp.status_code == 404
    assert "任务" in resp.json()["detail"]


def test_download_error_path_emits_error_event(env: SimpleNamespace) -> None:
    env.site.fail.add(SECTION_URLS[1])
    task_id = download(env)
    events, saw_done, _ = read_sse(env, task_id)
    kinds = [e["kind"] for e in events]
    assert kinds[-1] == "error", "失败路径以 error 事件收尾"
    assert not kinds.count("error") > 1, "error 事件不得重复（fetcher 已发则不补发）"
    assert saw_done
    detail = env.http.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == "error"
    assert "模拟故障" in detail["error"]
    # 失败任务的断点保留在按 URL 稳定的工作目录里（跨重启可续传）
    state_root = env.tmp / "out" / server_module.TASK_RUN_SUBDIR
    assert state_root.is_dir()
    assert any(state_root.rglob("*.json"))
    # 再次发起同 URL：续传（断点里已完成的章节不再请求）
    env.site.fail.discard(SECTION_URLS[1])
    calls_before = len([c for c in list(env.site.calls) if c == SECTION_URLS[0]])
    t2 = download(env)
    d2 = wait_task(env, t2)
    assert d2["status"] == "done"
    calls_after = len([c for c in list(env.site.calls) if c == SECTION_URLS[0]])
    assert calls_after == calls_before
    # R1-M4：成功后分桶目录保留断点（不再清走），导出文件在 output_dir 根
    assert (task_key_dir(env, COLUMN_URL) / ".zhihu_state").is_dir()
    assert Path(d2["files"][0]).parent == env.tmp / "out"


def _corrupt_checkpoint(env: SimpleNamespace) -> None:
    """制造真实断点：先失败一次留下断点，再把状态 JSON 写坏。"""
    env.site.fail.add(SECTION_URLS[1])
    t1 = download(env)
    assert wait_task(env, t1)["status"] == "error"
    env.site.fail.discard(SECTION_URLS[1])
    state_dir = task_key_dir(env, COLUMN_URL) / ".zhihu_state"
    state_files = list(state_dir.glob("*.json"))
    assert state_files, "失败任务的断点必须保留（续传前提）"
    state_files[0].write_text("{ broken json", encoding="utf-8")


def test_checkpoint_corruption_resume_hint(env: SimpleNamespace) -> None:
    """E1 契约：resume=True 遇断点损坏 → 中文 CheckpointError 原样透传，
    末尾追加"或关闭续传重试"；SSE error 事件与任务详情同一消息。"""
    _corrupt_checkpoint(env)
    task_id = download(env)  # 默认 resume=True
    detail = wait_task(env, task_id)
    assert detail["status"] == "error"
    assert "断点文件已损坏" in detail["error"]      # 引擎原始指引
    assert "或关闭续传重试" in detail["error"]      # server 追加的 GUI 可操作提示
    events, saw_done, _ = read_sse(env, task_id)
    assert [e["kind"] for e in events] == ["error"]
    assert "或关闭续传重试" in events[0]["message"]
    assert saw_done


def test_checkpoint_corruption_resume_off_recovers(env: SimpleNamespace) -> None:
    """同一损坏断点，resume=False 先清理再下载：应当直接成功（提示的可执行路径）。"""
    _corrupt_checkpoint(env)
    task_id = download(env, resume=False)
    detail = wait_task(env, task_id)
    assert detail["status"] == "done"
    assert Path(detail["files"][0]).exists()


def test_unsupported_url_synthesizes_error_event(env: SimpleNamespace) -> None:
    """story.zhihu.com 过 SSRF 闸，但 fetcher 抛 UnsupportedUrlError：
    未产生任何事件也要在 SSE 里补发一个中文 error 事件。"""
    task_id = download(env, url="https://story.zhihu.com/manuscript/paid_column/123")
    events, saw_done, _ = read_sse(env, task_id)
    assert [e["kind"] for e in events] == ["error"]
    assert "APP" in events[0]["message"]
    assert saw_done
    assert env.http.get(f"/api/tasks/{task_id}").json()["status"] == "error"


# ---------------------------------------------------------------------------
# 3. 每任务独立 client（v4 竞态教训）
# ---------------------------------------------------------------------------

def test_each_task_gets_isolated_client(env: SimpleNamespace) -> None:
    t1 = download(env)
    t2 = download(env, url=SECTION_URLS[0])
    wait_task(env, t1)
    wait_task(env, t2)
    task1 = env.state.tasks.get(t1)
    task2 = env.state.tasks.get(t2)
    assert task1.client is not task2.client
    assert task1.client is not env.client
    assert task1.client.session is not env.client.session   # 绝不共享 session
    assert task2.client.session is not task1.client.session
    assert task1.client.cookie_file == env.client.cookie_file  # 但共享 Cookie 文件


def test_rate_limit_clamped(env: SimpleNamespace) -> None:
    t = download(env, rate_limit=999)
    task = env.state.tasks.get(t)
    assert task.client.rate_limit == server_module.MAX_RATE_LIMIT
    t2 = download(env, url=SECTION_URLS[0], rate_limit=5)
    assert env.state.tasks.get(t2).client.rate_limit == 5.0


def test_duplicate_active_url_rejected(env: SimpleNamespace) -> None:
    """同一链接已有进行中任务时重复提交 → 400 中文（重复提交去重 + 目录隔离纵深防御）。"""
    gate = threading.Event()
    env.site.block[COLUMN_URL] = gate
    t1 = download(env)
    assert _wait_until(lambda: env.state.tasks.get(t1).status == "running")
    resp = env.http.post("/api/download", json={"url": COLUMN_URL})
    assert resp.status_code == 400
    assert "正在进行中" in resp.json()["detail"]
    gate.set()
    wait_task(env, t1)
    # 终态后可重新发起（等待收尾，确保测试结束前无在跑任务）
    resp2 = env.http.post("/api/download", json={"url": COLUMN_URL})
    assert resp2.status_code == 200
    wait_task(env, resp2.json()["task_id"])


# ---------------------------------------------------------------------------
# 4. 任务表 LRU（上限只淘汰终态，且记录淘汰）
# ---------------------------------------------------------------------------

def test_task_lru_evicts_terminal_only_and_logs(env: SimpleNamespace,
                                                caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=server_module.__name__)
    store = env.state.tasks
    store.limit = 2

    t_a = download(env)                      # A：正常完成（终态）
    wait_task(env, t_a)

    gate = threading.Event()                 # B：阻塞在目录请求上 = 运行中
    env.site.block[COLUMN_URL] = gate
    t_b = download(env)
    assert _wait_until(lambda: store.get(t_b).status == "running")

    t_c = download(env, url=SECTION_URLS[0])  # C：入表触发淘汰 → 最旧终态 A 出局
    wait_task(env, t_c)

    ids = [t["id"] for t in env.http.get("/api/tasks").json()]
    assert t_a not in ids and t_b in ids and t_c in ids
    assert "淘汰" in caplog.text             # 淘汰必须记录
    assert "任务不存在" in env.http.get(f"/api/tasks/{t_a}").json()["detail"]

    gate.set()                               # 放行 B，收尾
    wait_task(env, t_b)


def test_task_lru_keeps_running_when_nothing_evictable(env: SimpleNamespace,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=server_module.__name__)
    store = env.state.tasks
    store.limit = 1
    gate = threading.Event()
    env.site.block[COLUMN_URL] = gate
    t1 = download(env)
    t2 = download(env, url=SECTION_URLS[2])  # 另一本书同时在跑：无可淘汰项，都保留
    assert _wait_until(lambda: store.get(t1).status == "running"
                       and store.get(t2).status == "running")
    assert len(store) == 2
    assert "暂不淘汰" in caplog.text
    gate.set()
    wait_task(env, t1)
    wait_task(env, t2)


# ---------------------------------------------------------------------------
# 5. 文件下载防穿越
# ---------------------------------------------------------------------------

def test_file_download_registered_ok(env: SimpleNamespace) -> None:
    task_id = download(env)
    detail = wait_task(env, task_id)
    name = Path(detail["files"][0]).name
    resp = env.http.get(f"/api/files/{task_id}/{name}")
    assert resp.status_code == 200
    assert "小节" in resp.text
    assert "attachment" in resp.headers["content-disposition"]


@pytest.mark.parametrize("evil", [
    "..%2F..%2F..%2Fetc%2Fpasswd",           # %2F 编码的 ../
    "%2e%2e%2f%2e%2e%2fsecret.txt",          # 点号也编码
    "secret.txt",                            # 合法形态但未登记
    "测%2e试.md",                            # 花名册外
    "%2e%2e",                                # 单段 ..
])
def test_file_traversal_404(env: SimpleNamespace, evil: str) -> None:
    task_id = download(env)
    wait_task(env, task_id)
    # 在输出目录旁放一个真实存在的诱饵文件：穿越若成立就会被回显
    secret = env.tmp / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    resp = env.http.get(f"/api/files/{task_id}/{evil}")
    assert resp.status_code == 404
    assert b"TOP-SECRET" not in resp.content
    # 未知任务：无论文件名多合法都 404
    assert env.http.get(f"/api/files/nosuchtask/{evil}").status_code == 404


# ---------------------------------------------------------------------------
# 6. Cookie 三端点：只回布尔、导入中文 400、登出清内存
# ---------------------------------------------------------------------------

def test_cookies_status_booleans_only(env: SimpleNamespace) -> None:
    resp = env.http.get("/api/cookies")
    assert resp.status_code == 200
    assert resp.json() == {"has_cookie": True, "z_c0": True,
                           "zse_ck": False, "d_c0": True}
    assert "SECRET_Z_C0" not in resp.text    # 绝不回传 Cookie 值！
    assert "SECRET_D_C0" not in resp.text


def test_cookies_import_valid_and_invalid(env: SimpleNamespace) -> None:
    resp = env.http.post("/api/cookies/import",
                         json={"raw": "z_c0=abc; zse_ck=ck; d_c0=dc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert Path(body["saved_to"]) == env.cookie_file
    mode = stat.S_IMODE(env.cookie_file.stat().st_mode)
    assert mode == 0o600                     # 落盘权限 0600
    flags = env.http.get("/api/cookies").json()
    assert flags == {"has_cookie": True, "z_c0": True, "zse_ck": True, "d_c0": True}
    assert "abc" not in resp.text            # 导入响应同样不回传值

    for raw in ["", "完全不是 cookie"]:
        bad = env.http.post("/api/cookies/import", json={"raw": raw})
        assert bad.status_code == 400
        assert "Cookie" in bad.json()["detail"]  # 中文可读（parse_content 的消息）


def test_cookies_logout_clears_memory(env: SimpleNamespace) -> None:
    assert env.client.get_cookies() != {}
    resp = env.http.delete("/api/cookies")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "removed": True}
    assert not env.cookie_file.exists()
    assert env.client.get_cookies() == {}    # 登出必须清内存（copy_with 不带走旧值）
    derived = env.client.copy_with()
    assert derived.get_cookies() == {}
    assert env.http.get("/api/cookies").json() == {
        "has_cookie": False, "z_c0": False, "zse_ck": False, "d_c0": False}
    # 文件已不在时再删一次：幂等，removed=False
    assert env.http.delete("/api/cookies").json() == {"ok": True, "removed": False}


# ---------------------------------------------------------------------------
# 7. 扫码三端点：委托 auth.qr 且传应用客户端实例
# ---------------------------------------------------------------------------

def test_qrcode_endpoints_delegate(env: SimpleNamespace,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_start(c: Any) -> dict:
        seen["start"] = c
        return {"token": "T1", "image_url": "https://www.zhihu.com/qr/T1"}

    def fake_image(c: Any, token: str) -> bytes:
        seen["image"] = token
        return b"FAKE-JPEG-BYTES"

    def fake_poll(c: Any, token: str) -> dict:
        seen["poll"] = token
        return {"status": "scanned", "user_id": None, "error": None}

    monkeypatch.setattr(server_module.qr, "start", fake_start)
    monkeypatch.setattr(server_module.qr, "image", fake_image)
    monkeypatch.setattr(server_module.qr, "poll", fake_poll)

    resp = env.http.post("/api/qrcode")
    assert resp.status_code == 200
    assert resp.json() == {"token": "T1", "image_url": "https://www.zhihu.com/qr/T1"}
    assert seen["start"] is env.client       # 委托：传的就是应用客户端

    resp = env.http.get("/api/qrcode/T1/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content == b"FAKE-JPEG-BYTES"
    assert seen["image"] == "T1"

    resp = env.http.get("/api/qrcode/T1/status")
    assert resp.json()["status"] == "scanned"
    assert seen["poll"] == "T1"


def test_qrcode_error_maps_to_400(env: SimpleNamespace,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(c: Any) -> dict:
        raise AuthError("获取登录二维码失败：模拟断网，请稍后重试")

    monkeypatch.setattr(server_module.qr, "start", boom)
    resp = env.http.post("/api/qrcode")
    assert resp.status_code == 400
    assert "二维码" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8. 书架：列表 / 追更（无新章、有新章）/ 删除
# ---------------------------------------------------------------------------

def task_key_dir(env: SimpleNamespace, url: str) -> Path:
    """任务工作目录（按 URL 稳定分桶），断点/导出中转都在里面。"""
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return env.tmp / "out" / server_module.TASK_RUN_SUBDIR / key


def shelf_ids(env: SimpleNamespace) -> list[str]:
    return [b["id"] for b in env.http.get("/api/shelf").json()]


def test_shelf_list_empty(env: SimpleNamespace) -> None:
    assert env.http.get("/api/shelf").json() == []


def test_shelf_update_no_new_chapters(env: SimpleNamespace) -> None:
    task_id = download(env)
    wait_task(env, task_id)
    assert _wait_until(lambda: shelf_ids(env) != [])
    book_id = shelf_ids(env)[0]
    resp = env.http.post(f"/api/shelf/{book_id}/update")
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] is False          # 目录无变化 → 不重导出
    assert "没有新章节" in body["message"] or "已是最新" in body["message"]


def test_shelf_update_with_new_chapter(env: SimpleNamespace) -> None:
    task_id = download(env)
    wait_task(env, task_id)
    book = env.http.get("/api/shelf").json()[0]
    assert len(book["chapter_urls"]) == 3

    env.site.pages[COLUMN_URL] = TOC_HTML_V2          # 目录多了第 4 章
    env.site.pages[SECTION_URLS[3]] = section_html(4)
    resp = env.http.post(f"/api/shelf/{book['id']}/update")
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] is True
    assert body["new_chapters"] == 1
    new_task = wait_task(env, body["task_id"])       # 整本重导出（追更）
    assert new_task["status"] == "done"
    assert new_task["kind"] == "shelf_update"

    after = env.http.get("/api/shelf").json()[0]
    assert sorted(after["chapter_urls"]) == sorted(SECTION_URLS[:4])  # 新旧合并
    assert Path(after["files"][0]).exists()
    assert "第四章" in Path(after["files"][0]).read_text(encoding="utf-8")


def test_shelf_update_unknown_404(env: SimpleNamespace) -> None:
    resp = env.http.post("/api/shelf/nosuchid/update")
    assert resp.status_code == 404
    assert "书架" in resp.json()["detail"]


def test_shelf_delete(env: SimpleNamespace) -> None:
    task_id = download(env)
    wait_task(env, task_id)
    book = env.http.get("/api/shelf").json()[0]
    resp = env.http.delete(f"/api/shelf/{book['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "removed": True}
    assert env.http.get("/api/shelf").json() == []
    # 只删条目不删文件
    assert Path(book["files"][0]).exists()
    again = env.http.delete(f"/api/shelf/{book['id']}")
    assert again.status_code == 404


# ---------------------------------------------------------------------------
# 9. 静态挂载（PyInstaller datas 场景路径同构）
# ---------------------------------------------------------------------------

def test_static_ui_mounted(env: SimpleNamespace) -> None:
    resp = env.http.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert env.http.get("/style.css").status_code == 200


def test_static_dir_relative_to_module() -> None:
    assert server_module.STATIC_DIR == Path(server_module.__file__).parent / "static"


# ---------------------------------------------------------------------------
# 10. 并发冒烟：两个任务同时跑（executor max_workers=2），互不串台
# ---------------------------------------------------------------------------

def test_two_tasks_run_concurrently(env: SimpleNamespace) -> None:
    started = time.time()
    t1 = download(env)
    t2 = download(env, url=SECTION_URLS[0])
    d1 = wait_task(env, t1)
    d2 = wait_task(env, t2)
    assert d1["status"] == d2["status"] == "done"
    assert d1["progress"]["total"] == 3 and d2["progress"]["total"] == 1
    assert time.time() - started < 15
    # 线程池参数契约
    assert server_module.MAX_CONCURRENT_TASKS == 2
    assert env.state.executor() is env.state.executor()  # 懒创建后单例


# ---------------------------------------------------------------------------
# 11. R2#P0-2：解析差分 SSRF 载荷（反斜杠/@/协议注入）一律 400
# ---------------------------------------------------------------------------

#: 反斜杠字面量（构造 PoC 载荷用，避免源码转义歧义，与生产代码同一约定）。
BS = chr(92)


@pytest.mark.parametrize("bad_url", [
    "http://127.0.0.1:9501" + BS + "@www.zhihu.com/market/paid_column/1",  # 审计 PoC
    "https://www.zhihu.com" + BS + "@evil.com/market/paid_column/1",       # 反向差分
    "http://www.zhihu.com@127.0.0.1:9501/market/paid_column/1",            # userinfo 注入
    "javascript:alert(1)//www.zhihu.com",                                  # 协议注入
    "file:///etc/passwd",                                                  # file 协议
    "http://127.0.0.1:9501#@www.zhihu.com",                                # fragment 藏 @
])
def test_parser_differential_urls_rejected_400(env: SimpleNamespace, bad_url: str) -> None:
    resp = env.http.post("/api/download", json={"url": bad_url, "format": "md"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "知乎" in detail and "拒绝" in detail
    assert env.http.get("/api/tasks").json() == []  # 闸门在建任务之前


def test_is_zhihu_url_gate_unit() -> None:
    """闸门函数直接单测：反斜杠/@ 硬拒 + scheme 白名单 + urllib3 同栈取 host。

    R2#P0-2：旧实现只信 urlparse().hostname，对「127.0.0.1:9501 + 反斜杠 +
    @www.zhihu.com」这类差分载荷会放行；新实现必须拒。
    """
    assert server_module.is_zhihu_url("https://www.zhihu.com/market/paid_column/1")
    assert server_module.is_zhihu_url("HTTPS://ZHIHU.COM/x")  # 大小写不敏感
    assert not server_module.is_zhihu_url("http://127.0.0.1:9501" + BS + "@www.zhihu.com/")
    assert not server_module.is_zhihu_url("http://zhihu.com@127.0.0.1:9501/")
    assert not server_module.is_zhihu_url("javascript:open('https://www.zhihu.com')")
    assert not server_module.is_zhihu_url("file://zhihu.com/etc/passwd")
    assert not server_module.is_zhihu_url("http://zhihu.com.evil.co/")
    assert not server_module.is_zhihu_url("http://[::1")  # 畸形 IPv6 → 解析抛错 → 拒


# ---------------------------------------------------------------------------
# 12. R2#P0-3：CSRF-lite —— 写接口 Origin/Referer 闸门
# ---------------------------------------------------------------------------

EVIL_ORIGIN = "http://evil.example"


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/download"),
    ("POST", "/api/qrcode"),
    ("POST", "/api/shelf/anyid/update"),
    ("POST", "/api/cookies/import"),
    ("DELETE", "/api/cookies"),
    ("DELETE", "/api/shelf/anyid"),
])
def test_write_endpoints_reject_evil_origin(
    env: SimpleNamespace, method: str, path: str
) -> None:
    resp = env.http.request(method, path, json={}, headers={"Origin": EVIL_ORIGIN})
    assert resp.status_code == 403
    assert "跨站" in resp.json()["detail"]


def test_bodyless_form_post_evil_origin_403(env: SimpleNamespace) -> None:
    """审计 PoC 复现：无 body 的 form POST（简单请求不触发预检）+ 外站 Origin → 403。"""
    resp = env.http.post(
        "/api/shelf/nosuchid/update",
        headers={"Origin": EVIL_ORIGIN,
                 "Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 403
    assert "跨站" in resp.json()["detail"]


def test_referer_checked_when_origin_absent(env: SimpleNamespace) -> None:
    """无 Origin 时退而查 Referer；本机 Referer 放行（404=过了闸门卡在查书）。"""
    resp = env.http.post("/api/qrcode", headers={"Referer": EVIL_ORIGIN + "/page"})
    assert resp.status_code == 403
    resp = env.http.post("/api/shelf/nosuchid/update",
                         headers={"Referer": "http://127.0.0.1:8123/"})
    assert resp.status_code == 404


@pytest.mark.parametrize("origin", [
    "http://127.0.0.1:8000",   # 默认端口
    "http://localhost:9999",   # localhost 别名 + 任意端口（GUI 端口自动 +1）
    "http://[::1]:1234",       # IPv6 回环
])
def test_loopback_origin_any_port_allowed(env: SimpleNamespace, origin: str) -> None:
    resp = env.http.post("/api/shelf/nosuchid/update", headers={"Origin": origin})
    assert resp.status_code == 404  # 非 403：闸门通过


def test_no_origin_curl_style_allowed(env: SimpleNamespace) -> None:
    """无 Origin/Referer（curl/CLI/测试客户端）→ 写接口照常工作。"""
    resp = env.http.post("/api/download", json={"url": COLUMN_URL})
    assert resp.status_code == 200
    assert resp.json()["task_id"]


def test_get_with_evil_origin_not_blocked(env: SimpleNamespace) -> None:
    """GET 是无副作用读接口（Cookie 只回布尔）：按设计不拦 Origin。"""
    resp = env.http.get("/api/health", headers={"Origin": EVIL_ORIGIN})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 13. R2#P0-3：docs 关闭 + 全站安全响应头
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect",
])
def test_api_docs_disabled(env: SimpleNamespace, path: str) -> None:
    assert env.http.get(path).status_code == 404


def test_security_headers_on_api_and_static_responses(env: SimpleNamespace) -> None:
    """API、静态资源统一带 CSP/nosniff/DENY；未声明缓存的响应补 no-store。"""
    for path in ("/api/health", "/api/cookies", "/", "/style.css"):
        resp = env.http.get(path)
        assert resp.status_code == 200, path
        csp = resp.headers["content-security-policy"]
        assert csp.startswith("default-src 'none'")
        assert "script-src 'self'" in csp
        # img-src 放行知乎域：二维码 image_url 指向 https://www.zhihu.com（auth/qr.py）
        assert "img-src 'self' data: https://www.zhihu.com https://*.zhihu.com" in csp
        assert "style-src 'self'" in csp
        assert "connect-src 'self'" in csp
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["cache-control"] == "no-store"


def test_security_headers_on_error_responses(env: SimpleNamespace) -> None:
    """4xx（SSRF 拒绝 / CSRF 拒绝）响应同样过安全头中间件。"""
    resp = env.http.post("/api/download", json={"url": "https://evil.com/x"})
    assert resp.status_code == 400
    assert resp.headers["content-security-policy"].startswith("default-src 'none'")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    resp = env.http.post("/api/qrcode", headers={"Origin": EVIL_ORIGIN})
    assert resp.status_code == 403
    assert "cache-control" in resp.headers


# ---------------------------------------------------------------------------
# 14. R2#P0-3：写接口速率粗限（未终态任务总数 ≥ MAX_CONCURRENT_TASKS×4 → 429）
# ---------------------------------------------------------------------------

def test_too_many_active_tasks_returns_429(env: SimpleNamespace) -> None:
    """未终态任务堆到软上限：/api/download 429 中文；终态清空后恢复受理。"""
    cap = server_module.MAX_CONCURRENT_TASKS * server_module.ACTIVE_TASK_QUEUE_FACTOR
    assert cap == 8
    for i in range(cap):
        env.state.tasks.add(server_module.Task(
            id=f"busy{i}", kind="download",
            url="https://www.zhihu.com/busy/" + str(i), fmt="md"))

    resp = env.http.post("/api/download", json={"url": COLUMN_URL})
    assert resp.status_code == 429
    assert "任务过多" in resp.json()["detail"]
    assert "8" in resp.json()["detail"]  # 消息里给出上限值

    # 闸门发生在建任务之前：busy 任务之外没有新增
    assert len(env.state.tasks) == cap

    # 全部转终态后额度释放
    for t in env.state.tasks.list():
        t.finished.set()
    resp = env.http.post("/api/download", json={"url": COLUMN_URL})
    assert resp.status_code == 200
    wait_task(env, resp.json()["task_id"])


def test_duplicate_url_400_still_first_line(env: SimpleNamespace) -> None:
    """既有「同 URL 未终态 → 400」语义保留（与 429 总量闸互不吞没）。"""
    gate = threading.Event()
    env.site.block[COLUMN_URL] = gate
    t1 = download(env)
    assert _wait_until(lambda: env.state.tasks.get(t1).status == "running")
    resp = env.http.post("/api/download", json={"url": COLUMN_URL})
    assert resp.status_code == 400
    assert "正在进行中" in resp.json()["detail"]
    gate.set()
    wait_task(env, t1)


# ---------------------------------------------------------------------------
# 15. R2#6：追更入口显式过闸（shelf.json 外部篡改防御）
# ---------------------------------------------------------------------------

def _tamper_shelf(env: SimpleNamespace, entries: list[dict[str, Any]]) -> None:
    """直接改写 shelf.json（模拟外部工具篡改；Shelf 无缓存，读侧即时可见）。"""
    env.shelf.path.write_text(
        json.dumps({"books": entries}), encoding="utf-8")


def _shelf_entry(book_id: str, url: str, fmt: str = "md") -> dict[str, Any]:
    return {"id": book_id, "title": "被篡改的书", "url": url, "fmt": fmt,
            "files": [], "chapter_urls": [],
            "downloaded_at": "", "updated_at": ""}


@pytest.mark.parametrize("bad_url", [
    "http://127.0.0.1:9" + BS + "@www.zhihu.com/market/paid_column/1",  # 反斜杠差分 PoC
    "http://127.0.0.1:9501/admin",                                      # 内网直连
    "http://www.zhihu.com@127.0.0.1:9501/market/paid_column/1",         # userinfo @
    "javascript:alert(1)",                                              # 协议注入
])
def test_shelf_update_rejects_tampered_url_without_request(
    env: SimpleNamespace, bad_url: str
) -> None:
    """R2#6：条目 url 被篡改 → 400 中文「数据异常请清理书架」，零请求、零任务。

    旧实现把 book.url 直接喂 resolve_book（首跳请求先于任何域校验发出）；
    新实现必须在建客户端、发任何请求之前过闸——用 site.calls 增量==0 断言。
    """
    _tamper_shelf(env, [_shelf_entry("tampered1", bad_url)])
    before = len(env.site.calls)
    resp = env.http.post("/api/shelf/tampered1/update")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "数据异常" in detail and "清理书架" in detail
    assert len(env.site.calls) == before          # resolve_book 一次都没触网
    assert env.http.get("/api/tasks").json() == []  # 也不建任务


def test_shelf_update_rejects_bad_fmt(env: SimpleNamespace) -> None:
    """R2#6：fmt="exe"（不在 FORMATS 白名单）→ 400 中文，零请求、零任务。"""
    _tamper_shelf(env, [_shelf_entry("badfmt", COLUMN_URL, fmt="exe")])
    before = len(env.site.calls)
    resp = env.http.post("/api/shelf/badfmt/update")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "数据异常" in detail and "格式" in detail and "exe" in detail
    assert len(env.site.calls) == before
    assert env.http.get("/api/tasks").json() == []


def test_shelf_update_url_checked_before_fmt(env: SimpleNamespace) -> None:
    """url 与 fmt 双异常时先报 url（SSRF 闸门优先级更高）。"""
    _tamper_shelf(env, [_shelf_entry("bothbad", "http://127.0.0.1:9/x", fmt="exe")])
    resp = env.http.post("/api/shelf/bothbad/update")
    assert resp.status_code == 400
    assert "链接" in resp.json()["detail"]


def test_shelf_list_marks_anomalous_entry_not_500(env: SimpleNamespace) -> None:
    """R2#6 读侧宽容：GET /api/shelf 不 500；异常条目带 data_anomaly 中文标记。"""
    _tamper_shelf(env, [
        _shelf_entry("goodid", COLUMN_URL),
        _shelf_entry("badid", "http://127.0.0.1:9" + BS + "@www.zhihu.com/x"),
        _shelf_entry("emptyid", ""),
    ])
    resp = env.http.get("/api/shelf")
    assert resp.status_code == 200
    by_id = {b["id"]: b for b in resp.json()}
    assert "data_anomaly" not in by_id["goodid"]     # 正常条目零附加字段（既有契约）
    assert "数据异常" in by_id["badid"]["data_anomaly"]
    assert "清理书架" in by_id["badid"]["data_anomaly"]
    assert "data_anomaly" in by_id["emptyid"]        # 空 url 也算异常数据


def test_shelf_update_good_entry_still_works(env: SimpleNamespace) -> None:
    """显式过闸不误伤正常通路：真实下载记账后的条目照常追更（回归护栏）。"""
    t1 = download(env)
    tid = wait_task(env, t1)
    assert tid["status"] == "done"
    assert _wait_until(lambda: shelf_ids(env) != [])
    book_id = shelf_ids(env)[0]
    resp = env.http.post("/api/shelf/" + book_id + "/update")
    assert resp.status_code == 200
    assert resp.json()["updated"] is False  # FakeSite 无新章 → 既有同步返回语义


# ---------------------------------------------------------------------------
# 16. R1 审查：M3 SSE 广播 / m2 relocate 保留现场 / m3 同名防撞 / M4 prune
# ---------------------------------------------------------------------------

def test_sse_concurrent_connections_both_get_full_events(
    env: SimpleNamespace,
) -> None:
    """M3：两条连接同时挂着——旧实现 destructive get 分食，各见半截。

    广播模型下 A/B 游标独立：任务运行中先后接入，两条都必须拿到全量
    （toc + 3×chapter + export + done）并以 [DONE] 收尾。
    """
    gate = threading.Event()
    env.site.block[COLUMN_URL] = gate
    task_id = download(env)
    assert _wait_until(lambda: env.state.tasks.get(task_id).status == "running")
    holder: dict[str, tuple[list[dict], bool, dict]] = {}
    client_b = TestClient(env.app)

    def reader_b() -> None:
        holder["b"] = read_sse(env, task_id, client=client_b)

    tb = threading.Thread(target=reader_b)
    tb.start()
    gate.set()
    a_events, a_done, _ = read_sse(env, task_id)   # 连接 A（主线程）
    tb.join(30)
    assert not tb.is_alive(), "连接 B 未收尾（挂死）"
    b_events, b_done, _ = holder["b"]
    for name, (events, saw_done) in (("A", (a_events, a_done)),
                                     ("B", (b_events, b_done))):
        kinds = [e["kind"] for e in events]
        assert saw_done, name + " 缺 [DONE]"
        assert kinds[0] == "toc", name
        assert kinds.count("chapter") == 3, name + " 事件被分食"
        assert kinds[-1] == "done", name


def test_sse_event_log_cap_replays_tail_only(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M3：日志超上限丢最旧——游标跳过缺口只重放尾部，仍及时 [DONE]。"""
    monkeypatch.setattr(server_module, "EVENT_LOG_MAX", 3)
    task_id = download(env)
    wait_task(env, task_id)
    events, saw_done, _ = read_sse(env, task_id)
    kinds = [e["kind"] for e in events]
    assert len(kinds) == 3, "只保留日志尾部 EVENT_LOG_MAX 条"
    assert kinds[-2:] == ["export", "done"]
    assert saw_done, "截断后必须正常收尾，不挂死"


def test_relocate_failure_keeps_run_dir_and_files_downloadable(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m2：move 失败后不得 rmtree——done 任务的 files 必须仍可下载（旧 bug 404）。"""
    def boom(src, dest, *args, **kwargs):  # 只打桩 server 的 relocate 用 move
        raise OSError("模拟移动失败")

    monkeypatch.setattr(server_module.shutil, "move", boom)
    task_id = download(env)
    detail = wait_task(env, task_id)
    assert detail["status"] == "done"
    key_dir = task_key_dir(env, COLUMN_URL)
    leftovers = sorted(key_dir.rglob("*.md"))
    assert leftovers, "m2：移动失败的产物必须留在工作目录（保留现场）"
    assert detail["files"][0] == str(leftovers[0])  # 登记的是实际存在的路径
    name = Path(detail["files"][0]).name
    resp = env.http.get("/api/files/" + task_id + "/" + name)
    assert resp.status_code == 200, "旧 bug：rmtree 把残留文件连带删掉 → 404"


def test_same_name_books_do_not_overwrite(env: SimpleNamespace) -> None:
    """m3：两本书 safe_filename 相同 → 后者改名 -<task_id前6位>，双方产物都在。"""
    t1 = download(env)
    d1 = wait_task(env, t1)
    f1 = Path(d1["files"][0])
    assert f1.name == "测试专栏.md"
    column2 = "https://www.zhihu.com/market/paid_column/999"
    # 同标题（→同导出名）但独立目录页：href 换成本列 id，解析器才收章节链接
    env.site.pages[column2] = TOC_HTML.replace("paid_column/123", "paid_column/999")
    for i in (1, 2, 3):
        env.site.pages[column2 + "/section/" + str(i)] = section_html(i)
    t2 = env.http.post(
        "/api/download", json={"url": column2, "format": "md"}
    ).json()["task_id"]
    d2 = wait_task(env, t2)
    f2 = Path(d2["files"][0])
    assert f1.exists(), "m3：前者的产物不得被后者覆盖删除"
    assert f2.exists() and f1 != f2
    assert t2[:6] in f2.name, "撞名任务应追加 task_id 前 6 位防撞"
    assert f2.read_text(encoding="utf-8").count("小节") >= 3


def test_shelf_update_replaces_old_export(env: SimpleNamespace) -> None:
    """m3 定向清理（主审裁决）：追更后旧登记文件删除、新版在位、shelf 指新版。

    语义=「追更替换旧版」，杜绝 update 十次攒十个孤儿；旧文件路径取自书架
    登记白名单（basename 天然可删，不猜路径）。
    """
    t1 = download(env)
    d1 = wait_task(env, t1)
    old_file = Path(d1["files"][0])
    assert old_file.exists()
    book = env.http.get("/api/shelf").json()[0]
    assert book["files"] == [str(old_file)]
    # 加新章 → 追更（新任务 id → relocate 撞名改名，新旧路径必然不同）
    env.site.pages[COLUMN_URL] = TOC_HTML_V2
    env.site.pages[SECTION_URLS[3]] = section_html(4)
    body = env.http.post("/api/shelf/" + book["id"] + "/update").json()
    assert body["updated"] is True
    d2 = wait_task(env, body["task_id"])
    assert d2["status"] == "done"
    new_file = Path(d2["files"][0])
    assert new_file.exists() and new_file != old_file
    assert not old_file.exists(), "追更替换旧版：旧登记文件必须删除，不留孤儿"
    after = env.http.get("/api/shelf").json()[0]
    assert after["files"] == [str(new_file)], "shelf.files 必须指向新版"
    assert new_file.read_text(encoding="utf-8").count("小节") >= 4


def test_plain_redownload_keeps_old_and_renames_new(env: SimpleNamespace) -> None:
    """裁决边界：同 URL 非追更重下（kind=download）不清理旧版，改名共存。"""
    t1 = download(env)
    d1 = wait_task(env, t1)
    old = Path(d1["files"][0])
    t2 = download(env)          # 同 URL 重下：新任务、非追更
    d2 = wait_task(env, t2)
    assert d2["status"] == "done"
    new = Path(d2["files"][0])
    assert new != old
    assert new.exists() and old.exists(), "非追更路径维持 m3 改名不覆盖语义"


def test_shelf_delete_prunes_checkpoint(env: SimpleNamespace) -> None:
    """M4：DELETE /api/shelf/{id} 接 CheckpointStore.prune——state+bodies 同删。"""
    t1 = download(env)
    wait_task(env, t1)
    state_dir = task_key_dir(env, COLUMN_URL) / ".zhihu_state"
    assert list(state_dir.glob("*.json")), "前置：R1-M4 成功后断点保留"
    assert any((state_dir / "chapters").glob("*")), "前置：章节正文缓存保留"
    book_id = shelf_ids(env)[0]
    resp = env.http.delete("/api/shelf/" + book_id)
    assert resp.status_code == 200
    assert not list(state_dir.glob("*.json")), "prune：该书 state 必须删除"
    assert not any((state_dir / "chapters").glob("*")), "prune：该书 bodies 必须删除"
