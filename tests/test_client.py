"""ZhihuClient 单元测试（全离线：只 mock requests.Session 边界）。

覆盖规格 §4 对 test_client.py 的要求：
限速间隔 / 重试指数退避（mock time.sleep）/ 403 立即抛不重试 / 签名注入 /
线程安全冒烟（8 线程并发 fetch）。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
import requests

from zhihu_downloader import __version__
from zhihu_downloader.auth import cookies as cookie_store
from zhihu_downloader.engine import client as client_mod
from zhihu_downloader.engine.client import DEFAULT_USER_AGENT, ZhihuClient
from zhihu_downloader.errors import AuthError, ZhihuError
from zhihu_downloader.signature import XZSE_93_VERSION

URL = "https://www.zhihu.com/market/paid_column/123/section/456"


# ----------------------------------------------------------------------
# 测试替身
# ----------------------------------------------------------------------

class FakeResponse:
    """最小 requests.Response 替身（headers/url 供 R2#P0-1/P0-2 重定向闸门断言）。"""

    def __init__(self, status_code: int, text: str = "<html>ok</html>",
                 headers: dict[str, str] | None = None, url: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self.headers: dict[str, str] = dict(headers or {})
        self.url = url


class FakeCookieJar:
    """最小 CookieJar 替身：update + set（set 记录 domain，供 R2#P0-1 绑域断言）。"""

    def __init__(self) -> None:
        self.jar: dict[str, str] = {}
        self.domains: dict[str, str | None] = {}

    def update(self, mapping: dict[str, str]) -> None:
        self.jar.update(mapping)

    def set(self, name: str, value: str, domain: str | None = None) -> None:
        self.jar[name] = value
        self.domains[name] = domain


class FakeSession:
    """记录调用的 Session 替身，可脚本化返回序列与并发观测。"""

    def __init__(self, script: list[Any] | None = None, default: Any | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.cookies = FakeCookieJar()
        self.script: list[Any] = list(script or [])
        self.default: Any = default or FakeResponse(200)
        self.calls: list[tuple[str, dict[str, str] | None, Any]] = []
        #: 每次请求的额外关键字参数（R2#P0-1：断言 allow_redirects=False）。
        self.call_kwargs: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._inflight = 0
        self.max_inflight = 0
        self.hold = 0.005  # 每次请求占用一会儿，便于观测并发是否被锁串行化

    def get(
        self, url: str, headers: dict[str, str] | None = None, timeout: Any = None,
        **kwargs: Any,
    ) -> FakeResponse:
        """记录请求并返回脚本中的下一个响应（或抛出预置异常）。"""
        item: Any
        with self._lock:
            self.calls.append((url, headers, timeout))
            self.call_kwargs.append(dict(kwargs))
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
            item = self.script.pop(0) if self.script else self.default
        try:
            if self.hold:
                time.sleep(self.hold)
            if isinstance(item, Exception):
                raise item
            return item
        finally:
            with self._lock:
                self._inflight -= 1

    @property
    def call_count(self) -> int:
        """已发出的请求数。"""
        return len(self.calls)


class FakeClock:
    """time 模块替身：sleep 记录时长并推进虚拟时钟。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(tmp_path: Path, **kwargs: Any) -> ZhihuClient:
    """构造一个不读真实 Cookie、不发真实请求的客户端。"""
    kwargs.setdefault("cookie_file", tmp_path / "cookies.json")
    kwargs.setdefault("rate_limit", 0)  # 默认不限速，让单个测试只测自己关心的行为
    client = ZhihuClient(**kwargs)
    client.session = FakeSession()
    return client


# ----------------------------------------------------------------------
# 基本请求与签名
# ----------------------------------------------------------------------

def test_fetch_returns_text_and_records_request(tmp_path: Path) -> None:
    """fetch 返回响应文本，并把 URL / 超时传给 session。"""
    client = make_client(tmp_path)
    assert isinstance(client.session, FakeSession)
    client.session.script = [FakeResponse(200, "正文内容")]

    assert client.fetch(URL) == "正文内容"
    url, _headers, timeout = client.session.calls[0]
    assert url == URL
    assert timeout == client.timeout


def test_fetch_injects_signed_headers_for_zhihu_url(tmp_path: Path) -> None:
    """知乎 URL + d_c0 → 请求头带 x-zse-96 / x-zst-81 / x-zse-93。"""
    client = make_client(tmp_path)
    client.load_cookies({"d_c0": "abcDEF123"})
    client.session = FakeSession()
    client.fetch(URL)

    headers = client.session.calls[0][1]
    assert headers is not None
    assert headers["x-zse-96"].startswith("2.0_")
    assert headers["x-zse-93"] == XZSE_93_VERSION
    assert headers["x-zst-81"]


def test_fetch_without_signing_cookie_sends_no_signature(tmp_path: Path) -> None:
    """缺 d_c0 时不注入签名头（传 None，交给 session 默认头）。"""
    client = make_client(tmp_path)
    client.session = FakeSession()
    client.fetch(URL)
    assert client.session.calls[0][1] is None


def test_signed_headers_only_for_zhihu_hosts(tmp_path: Path) -> None:
    """signed_headers：非知乎域名返回空字典；知乎子域正常签名。"""
    client = make_client(tmp_path)
    client.load_cookies({"d_c0": "dc0value"})
    assert client.signed_headers("https://example.com/x") == {}
    assert client.signed_headers("not a url") == {}
    headers = client.signed_headers("https://zhuanlan.zhihu.com/p/1")
    assert set(headers) == {"x-zse-96", "x-zst-81", "x-zse-93"}


def test_signed_headers_empty_without_d_c0(tmp_path: Path) -> None:
    """没有 d_c0 时不签名。"""
    client = make_client(tmp_path)
    assert client.signed_headers(URL) == {}


def test_user_agent_is_modern_and_tagged(tmp_path: Path) -> None:
    """UA 为现代 Chrome/124（Windows NT 10.0）并保留产品后缀。"""
    client = ZhihuClient(cookie_file=tmp_path / "cookies.json", rate_limit=0)
    ua = client.session.headers["User-Agent"]
    assert "Chrome/124" in ua
    assert "Windows NT 10.0" in ua
    assert f"zhihu-salt/{__version__}" in ua
    assert DEFAULT_USER_AGENT == ua


# ----------------------------------------------------------------------
# 重试与退避
# ----------------------------------------------------------------------

def test_403_raises_immediately_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """403 反爬拦截：立即抛中文错误，不重试、不退避。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path)
    client.session = FakeSession(script=[FakeResponse(403)], default=FakeResponse(200))

    with pytest.raises(ZhihuError) as exc:
        client.fetch(URL)
    assert "HTTP 403" in str(exc.value)
    assert "重新登录" in str(exc.value)
    assert client.session.call_count == 1
    assert clock.sleeps == []


def test_404_raises_without_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """404 内容不存在：不重试。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path)
    client.session = FakeSession(script=[FakeResponse(404)])

    with pytest.raises(ZhihuError, match="HTTP 404"):
        client.fetch(URL)
    assert client.session.call_count == 1
    assert clock.sleeps == []


def test_other_4xx_raises_without_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非 403/404/429/5xx 的 HTTP 错误也不重试（重试无意义）。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path)
    client.session = FakeSession(script=[FakeResponse(401)])

    with pytest.raises(ZhihuError, match="HTTP 401"):
        client.fetch(URL)
    assert client.session.call_count == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retryable_status_uses_exponential_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """429/5xx：按 1/2/4s 指数退避，最终成功即返回。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path, retries=3)
    client.session = FakeSession(
        script=[FakeResponse(status)] * 3 + [FakeResponse(200, "好了")]
    )

    assert client.fetch(URL) == "好了"
    assert clock.sleeps == [1.0, 2.0, 4.0]
    assert client.session.call_count == 4


def test_network_error_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """网络错误（requests.RequestException）也走退避重试。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path, retries=2)
    client.session = FakeSession(
        script=[requests.ConnectionError("timeout"), FakeResponse(200, "恢复")]
    )

    assert client.fetch(URL) == "恢复"
    assert clock.sleeps == [1.0]


def test_retries_exhausted_raises_chinese_error_with_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重试耗尽：中文错误含重试次数与最后一次原因。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path, retries=2)
    client.session = FakeSession(default=FakeResponse(503))

    with pytest.raises(ZhihuError) as exc:
        client.fetch(URL)
    message = str(exc.value)
    assert "已重试 2 次" in message
    assert "HTTP 503" in message
    assert "doctor" in message  # 给出下一步操作建议
    assert clock.sleeps == [1.0, 2.0]
    assert client.session.call_count == 3


def test_retries_zero_means_single_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """retries=0 → 只请求一次。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path, retries=0)
    client.session = FakeSession(default=FakeResponse(500))

    with pytest.raises(ZhihuError):
        client.fetch(URL)
    assert client.session.call_count == 1
    assert clock.sleeps == []


def test_on_retry_hook_receives_attempt_delay_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """on_retry 回调收到 (url, 第几次, 退避秒数, 原因)，供上层发 retry 事件。"""
    monkeypatch.setattr(client_mod, "time", FakeClock())
    client = make_client(tmp_path, retries=2)
    client.session = FakeSession(script=[FakeResponse(500), FakeResponse(200, "ok")])
    seen: list[tuple[str, int, float, str]] = []
    client.on_retry = lambda url, attempt, delay, reason: seen.append((url, attempt, delay, reason))

    assert client.fetch(URL) == "ok"
    assert seen == [(URL, 1, 1.0, "HTTP 500（知乎服务端异常）")]


def test_on_retry_hook_exception_does_not_break_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """进度回调抛错不得影响重试主流程。"""
    monkeypatch.setattr(client_mod, "time", FakeClock())
    client = make_client(tmp_path, retries=1)
    client.session = FakeSession(script=[FakeResponse(500), FakeResponse(200, "ok")])

    def boom(*_args: Any) -> None:
        raise RuntimeError("UI 挂了")

    client.on_retry = boom
    assert client.fetch(URL) == "ok"


# ----------------------------------------------------------------------
# 限速
# ----------------------------------------------------------------------

def test_rate_limit_inserts_interval_between_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rate_limit=2 → 相邻请求之间至少间隔 0.5s（首个请求不等待）。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    client = make_client(tmp_path, rate_limit=2.0)
    client.session = FakeSession(default=FakeResponse(200, "x"))
    client.session.hold = 0.0

    client.fetch(URL)
    assert clock.sleeps == []          # 首个请求立即发出
    client.fetch(URL)
    assert clock.sleeps == [pytest.approx(0.5)]
    client.fetch(URL)
    assert clock.sleeps == [pytest.approx(0.5), pytest.approx(0.5)]


def test_rate_limit_none_or_zero_disables_throttling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rate_limit 为 0 / None / 负数 → 完全不限速。"""
    clock = FakeClock()
    monkeypatch.setattr(client_mod, "time", clock)
    for limit in (0, 0.0, None, -1):
        client = make_client(tmp_path, rate_limit=limit)  # type: ignore[arg-type]
        client.session = FakeSession(default=FakeResponse(200, "x"))
        client.session.hold = 0.0
        client.fetch(URL)
        client.fetch(URL)
    assert clock.sleeps == []


def test_rate_limit_measured_in_real_time(tmp_path: Path) -> None:
    """真实时钟下限速确实拉开间隔（宽松阈值，避免 CI 抖动）。"""
    client = make_client(tmp_path, rate_limit=20.0)  # 0.05s 一次
    client.session = FakeSession(default=FakeResponse(200, "x"))
    client.session.hold = 0.0
    started = time.monotonic()
    for _ in range(3):
        client.fetch(URL)
    assert time.monotonic() - started >= 0.08


# ----------------------------------------------------------------------
# 线程安全
# ----------------------------------------------------------------------

def test_concurrent_fetch_from_eight_threads(tmp_path: Path) -> None:
    """8 线程并发 fetch：全部成功、请求数正确、session 访问被锁串行化。"""
    client = make_client(tmp_path, rate_limit=0, retries=1)
    session = FakeSession(default=FakeResponse(200, "页面"))
    session.hold = 0.01
    client.session = session

    results: list[str] = []
    errors: list[BaseException] = []
    gate = threading.Barrier(8, timeout=5)

    def worker(i: int) -> None:
        gate.wait()
        try:
            results.append(client.fetch(f"{URL}?i={i}"))
        except BaseException as exc:  # noqa: BLE001 - 收集后断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert errors == []
    assert len(results) == 8
    assert session.call_count == 8
    assert session.max_inflight == 1  # 锁保护 session：同一时刻只有一个请求在飞


def test_concurrent_cookie_load_and_read(tmp_path: Path) -> None:
    """并发读写 Cookie 不崩，且最终状态包含全部键。"""
    client = make_client(tmp_path)
    client.session = FakeSession()

    def worker(i: int) -> None:
        client.load_cookies({f"k{i}": f"v{i}"})
        client.get_cookies()
        client.has_valid_signing_cookie()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    cookies = client.get_cookies()
    assert {f"k{i}" for i in range(8)} <= set(cookies)


# ----------------------------------------------------------------------
# Cookie 与 copy_with
# ----------------------------------------------------------------------

def test_get_cookies_returns_copy(tmp_path: Path) -> None:
    """get_cookies 是副本，改它不影响客户端内部状态。"""
    client = make_client(tmp_path)
    client.session = FakeSession()
    client.load_cookies({"d_c0": "keep"})
    snapshot = client.get_cookies()
    snapshot["d_c0"] = "tampered"
    assert client.get_cookies()["d_c0"] == "keep"


def test_save_cookies_delegates_to_auth_cookies_with_0600(tmp_path: Path) -> None:
    """save_cookies 委托 auth.cookies.save：JSON 落盘且权限 0600。"""
    client = make_client(tmp_path)
    client.session = FakeSession()
    client.load_cookies({"z_c0": "令牌", "d_c0": "dc0"})

    path = client.save_cookies()
    assert path == tmp_path / "cookies.json"
    assert path.read_text(encoding="utf-8").count("z_c0") == 1
    assert path.stat().st_mode & 0o777 == 0o600

    other = client.save_cookies(tmp_path / "sub" / "c.json")
    assert other.exists()


def test_load_cookies_accepts_dict_and_path(tmp_path: Path) -> None:
    """load_cookies 支持字典与文件路径，并同步到 session。"""
    client = make_client(tmp_path)
    client.session = FakeSession()
    client.load_cookies({"a": "1"})
    file = tmp_path / "imported.json"
    file.write_text('{"b": "2", "d_c0": "x"}', encoding="utf-8")
    client.load_cookies(file)

    assert client.get_cookies() == {"a": "1", "b": "2", "d_c0": "x"}
    assert client.session.cookies.jar == {"a": "1", "b": "2", "d_c0": "x"}


def test_load_missing_cookie_file_raises_auth_error(tmp_path: Path) -> None:
    """Cookie 文件不存在 → 中文 AuthError（提示先 login）。"""
    client = make_client(tmp_path)
    client.session = FakeSession()
    with pytest.raises(AuthError, match="login"):
        client.load_cookies(tmp_path / "nope.json")


def test_default_cookie_file_loaded_when_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未显式传 cookie_file 时使用 DEFAULT_COOKIE_FILE 并自动加载。"""
    default = tmp_path / "home-cookies.json"
    default.write_text('{"d_c0": "from-default"}', encoding="utf-8")
    monkeypatch.setattr(cookie_store, "DEFAULT_COOKIE_FILE", default)

    client = ZhihuClient(rate_limit=0)
    assert client.cookie_file == default
    assert client.has_valid_signing_cookie()
    assert client.get_cookies()["d_c0"] == "from-default"


def test_corrupt_default_cookie_file_degrades_to_unlogged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cookie 文件损坏：构造不崩（降级为未登录 + 告警），doctor 仍可用。"""
    broken = tmp_path / "cookies.json"
    broken.write_text("{半截 JSON", encoding="utf-8")
    monkeypatch.setattr(cookie_store, "DEFAULT_COOKIE_FILE", broken)

    client = ZhihuClient(rate_limit=0)
    assert client.get_cookies() == {}
    assert not client.has_valid_signing_cookie()
    # 显式加载时才把中文错误抛给用户
    with pytest.raises(AuthError):
        client.load_cookies(broken)


def test_default_cookie_file_absent_is_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认 Cookie 文件不存在时构造不报错（未登录状态可用）。"""
    monkeypatch.setattr(cookie_store, "DEFAULT_COOKIE_FILE", tmp_path / "absent.json")
    client = ZhihuClient(rate_limit=0)
    assert client.get_cookies() == {}
    assert not client.has_valid_signing_cookie()


def test_has_valid_signing_cookie(tmp_path: Path) -> None:
    """d_c0 存在且非空才算可用于签名。"""
    client = make_client(tmp_path)
    client.session = FakeSession()
    assert not client.has_valid_signing_cookie()
    client.load_cookies({"d_c0": ""})
    assert not client.has_valid_signing_cookie()
    client.load_cookies({"d_c0": "v"})
    assert client.has_valid_signing_cookie()


def test_copy_with_changes_rate_limit_without_mutating_original(tmp_path: Path) -> None:
    """copy_with 返回新实例、共享 Cookie 文件路径，不改原实例。"""
    original = make_client(tmp_path, rate_limit=2.0, timeout=15.0, retries=5)
    original.session = FakeSession()
    original.load_cookies({"d_c0": "shared"})

    derived = original.copy_with(rate_limit=0.5)

    assert derived is not original
    assert derived.rate_limit == 0.5
    assert original.rate_limit == 2.0            # 不原地改
    assert derived.cookie_file == original.cookie_file
    assert derived.timeout == 15.0
    assert derived.retries == 5
    assert derived.get_cookies()["d_c0"] == "shared"
    assert derived.has_valid_signing_cookie()


def test_copy_with_derived_client_saves_to_same_file(tmp_path: Path) -> None:
    """派生实例 save_cookies 写回同一处（一次登录全端复用）。"""
    original = make_client(tmp_path)
    original.session = FakeSession()
    original.load_cookies({"z_c0": "tok"})
    derived = original.copy_with(rate_limit=1.0)
    derived.load_cookies({"d_c0": "dc0"})

    path = derived.save_cookies()
    assert path == original.cookie_file
    assert original.cookie_file.read_text(encoding="utf-8").count("d_c0") == 1


# ----------------------------------------------------------------------
# 重定向闸门（R2#P0-1）与解析差分复校验（R2#P0-2）——全离线假 session
# ----------------------------------------------------------------------

#: 反斜杠字面量（测试载荷构造用，避免源码转义歧义，与生产代码同一约定）。
BS = chr(92)

EVIL_REDIRECT_TARGETS = [
    "https://evil.com/steal",                    # 普通外域
    "http://127.0.0.1:9501/internal",            # 内网地址（SSRF 典型目标）
    "https://zhihu.com.evil.co/callback",        # 仿冒域后缀伪装
    "//evil.com/x",                              # 协议相对跳转（urljoin 补 scheme 后被拦）
]


@pytest.mark.parametrize("target", EVIL_REDIRECT_TARGETS)
def test_cross_domain_redirect_not_followed_and_raises(
    tmp_path: Path, target: str
) -> None:
    """302 跳外域：不跟随、抛「登录凭证受保护」中文错误，外域零请求。"""
    client = make_client(tmp_path)
    client.session.script = [
        FakeResponse(302, headers={"Location": target}, url=URL),
        FakeResponse(200, "must-not-reach"),
    ]
    with pytest.raises(ZhihuError) as exc:
        client.fetch(URL)
    message = str(exc.value)
    assert "登录凭证受保护" in message
    assert "非知乎" in message
    assert client.session.call_count == 1        # 第二跳根本没发出去
    assert all("evil.com" not in c[0] and "9501" not in c[0] for c in client.session.calls)


def test_backslash_at_userinfo_redirect_rejected(tmp_path: Path) -> None:
    """R2#P0-2 PoC：Location 带反斜杠+@（urlparse 眼里是知乎域）→ 闸门拒绝。"""
    client = make_client(tmp_path)
    evil = "http://127.0.0.1:9501" + BS + "@www.zhihu.com/x"
    client.session.script = [FakeResponse(302, headers={"Location": evil}, url=URL)]
    with pytest.raises(ZhihuError, match="登录凭证受保护"):
        client.fetch(URL)
    assert client.session.call_count == 1


def test_same_domain_redirect_chain_followed(tmp_path: Path) -> None:
    """302 跳知乎域（含子域切换）：正常跟随，返回最终 200 正文。"""
    client = make_client(tmp_path)
    hop1 = "https://www.zhihu.com/api/v4/step1"
    hop2 = "https://zhuanlan.zhihu.com/final"
    client.session.script = [
        FakeResponse(302, headers={"Location": hop1}, url=URL),
        FakeResponse(302, headers={"Location": hop2}, url=hop1),
        FakeResponse(200, "final-body"),
    ]
    assert client.fetch(URL) == "final-body"
    assert [c[0] for c in client.session.calls] == [URL, hop1, hop2]


def test_relative_location_resolved_against_final_url(tmp_path: Path) -> None:
    """相对跳转（裸 path 的 Location）：urljoin 以最终落点为基准解析。"""
    client = make_client(tmp_path)
    base = "https://www.zhihu.com/market/paid_column/123/section/1"
    client.session.script = [
        FakeResponse(302, headers={"Location": "/api/v4/fresh"}, url=base),
        FakeResponse(200, "rel-ok"),
    ]
    assert client.fetch(URL) == "rel-ok"
    assert client.session.calls[1][0] == "https://www.zhihu.com/api/v4/fresh"


def test_five_hops_allowed_sixth_hop_raises(tmp_path: Path) -> None:
    """跳数闸门：5 跳重定向后成功允许；第 6 个重定向响应 → 中文抛错。"""
    client = make_client(tmp_path)
    hops = [
        FakeResponse(302, headers={"Location": f"https://www.zhihu.com/h{i}"}, url=URL)
        for i in range(5)
    ]
    client.session.script = hops + [FakeResponse(200, "deep-ok")]
    assert client.fetch(URL) == "deep-ok"
    assert client.session.call_count == 6        # 首跳 + 5 次跟随

    looped = make_client(tmp_path)
    looped.session.script = [
        FakeResponse(302, headers={"Location": f"https://www.zhihu.com/h{i}"}, url=URL)
        for i in range(6)
    ]
    with pytest.raises(ZhihuError, match="重定向次数"):
        looped.fetch(URL)
    assert looped.session.call_count == 6


def test_redirect_without_location_raises(tmp_path: Path) -> None:
    """3xx 缺 Location：无法审计下一跳，直接中文报错（不猜目标）。"""
    client = make_client(tmp_path)
    client.session.script = [FakeResponse(302, url=URL)]
    with pytest.raises(ZhihuError, match="缺少 Location"):
        client.fetch(URL)


def test_fetch_always_requests_no_auto_redirect(tmp_path: Path) -> None:
    """R2#P0-1：发给 session 的每个请求必须 allow_redirects=False（跳循环自管）。"""
    client = make_client(tmp_path)
    client.session.script = [FakeResponse(200, "x")]
    client.fetch(URL)
    assert client.session.call_kwargs[0].get("allow_redirects") is False


def test_response_final_url_revalidated_each_hop(tmp_path: Path) -> None:
    """R2#P0-2：请求后复校验 response.url——200 落在非知乎域也中止（差分残余兜底）。"""
    client = make_client(tmp_path)
    client.session.script = [FakeResponse(200, "body", url="http://127.0.0.1:9501/landed")]
    with pytest.raises(ZhihuError, match="登录凭证受保护"):
        client.fetch(URL)
    assert client.session.call_count == 1


def test_signed_headers_never_generated_for_offsite_targets(tmp_path: Path) -> None:
    """R2#P0-1#4：签名头只发往知乎域——反斜杠/@ 差分载荷同样拿不到签名。"""
    client = make_client(tmp_path)
    client.load_cookies({"d_c0": "dc0value"})
    assert client.signed_headers("http://127.0.0.1:9501" + BS + "@www.zhihu.com/x") == {}
    assert client.signed_headers("http://www.zhihu.com@127.0.0.1:9501/x") == {}
    assert client.signed_headers("https://www.zhihu.com/x") != {}


def test_network_error_message_hides_internal_host_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2#P0-2：重试耗尽的消息不回显连接池 repr 里的内网 host:port（防探测 oracle）。"""
    monkeypatch.setattr(client_mod, "time", FakeClock())
    client = make_client(tmp_path, retries=1)
    boom = requests.ConnectionError(
        "HTTPSConnectionPool(host='127.0.0.1', port=9501): Max retries exceeded")
    client.session = FakeSession(script=[boom, boom])

    with pytest.raises(ZhihuError) as exc:
        client.fetch(URL)
    message = str(exc.value)
    assert "9501" not in message
    assert "127.0.0.1" not in message
    assert "网络连接失败（目标不可达" in message   # 统一措辞
    assert "ConnectionError" in message           # 保留异常类型名供排查


# ----------------------------------------------------------------------
# Cookie 绑域（R2#P0-1 兜底）：真 requests jar 与测试替身双路径
# ----------------------------------------------------------------------

def test_load_cookies_binds_domain_in_real_jar(tmp_path: Path) -> None:
    """真 requests.Session：注入后 jar 里每条 Cookie 的 domain == ".zhihu.com"。"""
    client = ZhihuClient(cookie_file=tmp_path / "cookies.json", rate_limit=0)
    client.load_cookies({"z_c0": "TOKEN", "d_c0": "DC0"})
    stored = {c.name: c for c in client.session.cookies}
    assert set(stored) == {"z_c0", "d_c0"}
    assert all(c.domain == ".zhihu.com" for c in stored.values())


def _cookie_header(client: ZhihuClient, url: str) -> str:
    """让 requests 自己按 jar 规则算该 URL 会带上的 Cookie 头（离线）。"""
    prepared = client.session.prepare_request(requests.Request("GET", url))
    return prepared.headers.get("Cookie", "")


def test_bound_cookies_only_sent_to_zhihu_hosts(tmp_path: Path) -> None:
    """Cookie 头计算：知乎裸域/子域带 z_c0，外域不带（跨域泄露的根因修复）。"""
    client = ZhihuClient(cookie_file=tmp_path / "cookies.json", rate_limit=0)
    client.load_cookies({"z_c0": "TOKEN"})

    assert "z_c0" not in _cookie_header(client, "https://evil.com/x")
    assert "z_c0=TOKEN" in _cookie_header(client, "https://www.zhihu.com/x")
    assert "z_c0=TOKEN" in _cookie_header(client, "https://zhihu.com/x")
    # 旧写法（update(dict) 注入）正是栽在跨域照发上——回归防线核心断言。


def test_fake_jar_receives_domain_bound_set(tmp_path: Path) -> None:
    """测试替身路径：load_cookies 走 set(name, value, domain=".zhihu.com")。"""
    client = make_client(tmp_path)
    client.session = FakeSession()
    client.load_cookies({"z_c0": "tok"})
    assert client.session.cookies.domains["z_c0"] == ".zhihu.com"
    assert client.session.cookies.jar["z_c0"] == "tok"
