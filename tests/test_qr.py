"""auth/qr.py 测试：start / image / poll 五状态分支 + Cookie 落盘（0600）+ M6 会话隔离。

全部离线：mock 只打在 requests.Session 边界。R1 审查 M6 后 qr 的 HTTP 一律走
qr._new_session() 一次性 Session，故打桩点从 client.session 改为该工厂
（fixture 把工厂 patch 成共享 FakeSession，队列/调用记录断言原样可用）。
fixture 直接放在本文件内（约定：不建 conftest.py）。
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
import requests

from zhihu_downloader.auth import qr
from zhihu_downloader.errors import AuthError

# ----------------------------------------------------------------------
# 打桩：requests.Session 边界
# ----------------------------------------------------------------------


class FakeResponse:
    """最小 requests.Response 替身。"""

    def __init__(
        self,
        *,
        text: str = "",
        json_data: Any = None,
        content: bytes = b"",
        status_code: int = 200,
        broken_json: bool = False,
    ) -> None:
        self.text = text
        self._json = json_data
        self.content = content
        self.status_code = status_code
        self._broken_json = broken_json

    def json(self) -> Any:
        if self._broken_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


class FakeSession:
    """按队列吐出响应；记录每次调用供断言；支持 with（M6 一次性 Session）。"""

    def __init__(self, responses: list[Any] | None = None) -> None:
        self._responses: list[Any] = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.cookies: dict[str, str] = {}
        self.closed = False

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed = True

    def queue(self, *responses: Any) -> None:
        self._responses.extend(responses)

    def _next(self, method: str, url: str, headers: dict[str, str] | None, timeout: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "timeout": timeout})
        if not self._responses:
            raise AssertionError(f"打桩响应已用尽：{method} {url}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url: str, headers: dict[str, str] | None = None, timeout: Any = None) -> FakeResponse:
        return self._next("POST", url, headers, timeout)

    def get(self, url: str, headers: dict[str, str] | None = None, timeout: Any = None) -> FakeResponse:
        return self._next("GET", url, headers, timeout)


class FakeClient:
    """满足 qr.QrLoginClient 协议的最小客户端（不依赖 engine/client.py）。"""

    def __init__(
        self,
        session: FakeSession,
        cookie_file: Path,
        cookies: dict[str, str] | None = None,
        timeout: float = 7.5,
    ) -> None:
        self.session = session
        self.timeout = timeout
        self.cookie_file = cookie_file
        self._cookies: dict[str, str] = dict(cookies or {})

    def get_cookies(self) -> dict[str, str]:
        return dict(self._cookies)

    def load_cookies(self, source: str | Path | dict[str, str]) -> None:
        assert isinstance(source, dict)
        self._cookies.update(source)


@pytest.fixture()
def session() -> FakeSession:
    return FakeSession()


@pytest.fixture()
def client(session: FakeSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """M6 打桩点：qr._new_session() 返回共享 FakeSession，队列语义不变。"""
    monkeypatch.setattr(qr, "_new_session", lambda: session)
    return FakeClient(session, tmp_path / "cookies.json", cookies={"q_c1": "已有值"})


# ----------------------------------------------------------------------
# start
# ----------------------------------------------------------------------

def test_start_returns_token_and_image_url(client: FakeClient, session: FakeSession) -> None:
    session.queue(
        FakeResponse(text="UDID-abc"),
        FakeResponse(json_data={"token": "T1", "expires_in": 120}),
    )
    got = qr.start(client)
    assert got["token"] == "T1"
    assert got["image_url"] == qr.IMAGE_URL.format(token="T1")
    assert got["expire_seconds"] == 120
    assert [c["url"] for c in session.calls] == [qr.UDID_URL, qr.QRCODE_URL]
    # 第二次请求必须带 x-udid，且两次都带 Origin/Referer
    assert session.calls[1]["headers"]["x-udid"] == "UDID-abc"
    assert session.calls[0]["headers"]["Origin"] == "https://www.zhihu.com"
    assert session.calls[0]["timeout"] == client.timeout


def test_start_without_expire_field(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(text="U"), FakeResponse(json_data={"token": "T2"}))
    got = qr.start(client)
    assert set(got) == {"token", "image_url"}


def test_start_empty_udid_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(text="   "))
    with pytest.raises(AuthError, match="x-udid"):
        qr.start(client)


def test_start_udid_network_error_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(requests.ConnectionError("connection refused"))
    with pytest.raises(AuthError, match="获取登录设备标识"):
        qr.start(client)


def test_start_token_network_error_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(text="U"), requests.Timeout("timed out"))
    with pytest.raises(AuthError, match="获取登录二维码失败"):
        qr.start(client)


def test_start_non_json_response_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(text="U"), FakeResponse(broken_json=True))
    with pytest.raises(AuthError, match="获取登录二维码失败"):
        qr.start(client)


def test_start_missing_token_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(text="U"), FakeResponse(json_data={"code": 40001}))
    with pytest.raises(AuthError, match="没有 token"):
        qr.start(client)


def test_start_non_dict_payload_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(text="U"), FakeResponse(json_data=["T"]))
    with pytest.raises(AuthError, match="响应格式异常"):
        qr.start(client)


# ----------------------------------------------------------------------
# image
# ----------------------------------------------------------------------

def test_image_returns_bytes(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(content=b"\\xff\\xd8jpeg"))
    assert qr.image(client, "T1") == b"\\xff\\xd8jpeg"
    assert session.calls[0]["url"] == qr.IMAGE_URL.format(token="T1")


def test_image_http_error_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(status_code=500))
    with pytest.raises(AuthError, match="下载二维码图片失败"):
        qr.image(client, "T1")


def test_image_empty_body_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(content=b""))
    with pytest.raises(AuthError, match="内容为空"):
        qr.image(client, "T1")


def test_image_blank_token_raises(client: FakeClient) -> None:
    with pytest.raises(AuthError, match="token 为空"):
        qr.image(client, "")


# ----------------------------------------------------------------------
# poll：五状态分支
# ----------------------------------------------------------------------

def test_poll_waiting(client: FakeClient, session: FakeSession, tmp_path: Path) -> None:
    session.queue(FakeResponse(json_data={"status": 0}))
    got = qr.poll(client, "T1")
    assert got["status"] == "waiting"
    assert got["user_id"] is None and got["error"] is None
    assert got["saved_to"] is None
    assert not (tmp_path / "cookies.json").exists()


def test_poll_scanned(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(json_data={"status": 1}))
    assert qr.poll(client, "T1")["status"] == "scanned"


def test_poll_expired_on_known_expiry_code(client: FakeClient, session: FakeSession) -> None:
    """status == 2 是已知过期码 → expired；返回体不再携带 raw_status 原文字段。"""
    session.queue(FakeResponse(json_data={"status": 2}))
    got = qr.poll(client, "T1")
    assert got["status"] == "expired"
    assert "raw_status" not in got


def test_poll_result_shape_is_fixed(client: FakeClient, session: FakeSession) -> None:
    """返回体字段固定为四个规范化字段（Web API 直接透传，不留原文通道）。"""
    session.queue(FakeResponse(json_data={"status": 0, "extra": {"cookie": "X"}}))
    got = qr.poll(client, "T1")
    assert set(got) == {"status", "user_id", "error", "saved_to"}


def test_poll_error_status(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(json_data={"status": 0, "error": {"message": "二维码已失效"}}))
    got = qr.poll(client, "T1")
    assert got["status"] == "error"
    assert got["error"] == "二维码已失效"
    assert got["user_id"] is None


def test_poll_error_plain_string(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(json_data={"error": "need_verify"}))
    got = qr.poll(client, "T1")
    assert got["status"] == "error" and got["error"] == "need_verify"


def test_poll_confirmed_saves_cookie_0600(client: FakeClient, session: FakeSession, tmp_path: Path) -> None:
    session.queue(FakeResponse(json_data={
        "status": 0,
        "user_id": 42,
        "cookie": {"z_c0": "2|1:0|secret", "d_c0": "dc0"},
    }))
    got = qr.poll(client, "T1")
    assert got["status"] == "confirmed"
    assert got["user_id"] == "42"  # 统一为字符串，前端可直接渲染
    target = tmp_path / "cookies.json"
    assert got["saved_to"] == str(target)
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "q_c1": "已有值",       # 原有 Cookie 不被冲掉
        "z_c0": "2|1:0|secret",
        "d_c0": "dc0",
    }
    if os.name != "nt":  # pragma: no cover - Windows 无 POSIX 权限语义
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    # M6 + R2#P0-1：内存合并只走 client.load_cookies（公开方法，内部加锁、
    # 绑定 domain）；qr 不再直接摸 session jar——domain 为空的裸注入是泄露面。
    assert client.session.cookies == {}
    assert client.get_cookies() == {"q_c1": "已有值", "z_c0": "2|1:0|secret", "d_c0": "dc0"}


def test_poll_confirmed_cookie_as_raw_string(client: FakeClient, tmp_path: Path) -> None:
    client.session.queue(FakeResponse(json_data={"user_id": "u", "cookie": "z_c0=a; d_c0=b"}))
    got = qr.poll(client, "T1")
    assert got["status"] == "confirmed"
    assert json.loads((tmp_path / "cookies.json").read_text(encoding="utf-8"))["z_c0"] == "a"


def test_poll_confirmed_without_cookie_payload(client: FakeClient, tmp_path: Path) -> None:
    """知乎只回 user_id 时也算确认成功，但不能凭空写文件。"""
    client.session.queue(FakeResponse(json_data={"user_id": "u1"}))
    got = qr.poll(client, "T1")
    assert got["status"] == "confirmed" and got["saved_to"] is None
    assert not (tmp_path / "cookies.json").exists()


def test_poll_result_never_leaks_cookie_values(client: FakeClient) -> None:
    """poll 结果会被 Web API 直接透传，绝不能含 Cookie 明文。"""
    client.session.queue(FakeResponse(json_data={
        "user_id": "u", "cookie": {"z_c0": "TOP-SECRET", "d_c0": "ALSO-SECRET"},
    }))
    got = qr.poll(client, "T1")
    assert "TOP-SECRET" not in json.dumps(got, ensure_ascii=False)
    assert "ALSO-SECRET" not in json.dumps(got, ensure_ascii=False)


def test_poll_network_error_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(requests.ConnectionError("boom"))
    with pytest.raises(AuthError, match="轮询扫码状态失败"):
        qr.poll(client, "T1")


def test_poll_non_json_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(broken_json=True))
    with pytest.raises(AuthError, match="轮询扫码状态失败"):
        qr.poll(client, "T1")


def test_poll_non_dict_raises(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(json_data=[]))
    with pytest.raises(AuthError, match="不是 JSON 对象"):
        qr.poll(client, "T1")


def test_poll_blank_token_raises(client: FakeClient) -> None:
    with pytest.raises(AuthError, match="token 为空"):
        qr.poll(client, "")


# ----------------------------------------------------------------------
# R2 审计 #7：错误消息与返回体绝不回显远端 payload（repr 泄漏面）
# ----------------------------------------------------------------------

SECRET = "TOP-SECRET-z_c0-value"


def test_poll_non_dict_list_error_has_no_payload(client: FakeClient, session: FakeSession) -> None:
    """响应是 list 且内含 Cookie 样式字符串：异常消息只报类型名。"""
    session.queue(FakeResponse(json_data=[{"z_c0": SECRET}]))
    with pytest.raises(AuthError, match="不是 JSON 对象") as exc:
        qr.poll(client, "T1")
    message = str(exc.value)
    assert SECRET not in message and "z_c0" not in message
    assert "list" in message  # 只允许类型名


def test_start_non_dict_error_has_no_payload(client: FakeClient, session: FakeSession) -> None:
    session.queue(FakeResponse(text="U"), FakeResponse(json_data=[SECRET]))
    with pytest.raises(AuthError, match="响应格式异常") as exc:
        qr.start(client)
    assert SECRET not in str(exc.value) and "list" in str(exc.value)


def test_start_missing_token_error_has_no_payload(client: FakeClient, session: FakeSession) -> None:
    """没有 token 的 dict：错误消息不再 repr 整个 data（可能含 Cookie 字段）。"""
    session.queue(FakeResponse(text="U"), FakeResponse(json_data={"code": 40001, "z_c0": SECRET}))
    with pytest.raises(AuthError, match="没有 token") as exc:
        qr.start(client)
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize("bad_token", ["T" * 65, "bad token", "../x", "T1?next=evil", "T\n1"])
def test_start_rejects_malformed_token(client: FakeClient, session: FakeSession, bad_token: str) -> None:
    """token 强制 ^[A-Za-z0-9_-]{1,64}$；错误消息不回显 token 内容。"""
    session.queue(FakeResponse(text="U"), FakeResponse(json_data={"token": bad_token}))
    with pytest.raises(AuthError, match="token 不合法") as exc:
        qr.start(client)
    assert bad_token.strip() not in str(exc.value)


def test_start_accepts_boundary_token(client: FakeClient, session: FakeSession) -> None:
    """64 位边界内的 URL 安全 token 正常放行。"""
    token = "a" * 61 + "_-9"  # 64 位
    session.queue(FakeResponse(text="U"), FakeResponse(json_data={"token": token}))
    assert qr.start(client)["token"] == token


def test_poll_structured_error_not_reprd(client: FakeClient) -> None:
    """error 是无 message/code/name 的 dict：归 error 且不带原文。"""
    client.session.queue(FakeResponse(json_data={"error": {"detail": {"z_c0": SECRET}}}))
    got = qr.poll(client, "T1")
    assert got["status"] == "error"
    assert SECRET not in str(got["error"])
    assert SECRET not in json.dumps(got, ensure_ascii=False)


def test_poll_list_error_not_reprd(client: FakeClient) -> None:
    client.session.queue(FakeResponse(json_data={"error": [SECRET]}))
    got = qr.poll(client, "T1")
    assert got["status"] == "error" and SECRET not in json.dumps(got, ensure_ascii=False)


def test_poll_unknown_status_is_error_without_raw(client: FakeClient) -> None:
    """未知/漂移状态归 error，只报字段类型名，不回显值。"""
    client.session.queue(FakeResponse(json_data={"status": {"leak": SECRET}}))
    got = qr.poll(client, "T1")
    assert got["status"] == "error"
    assert SECRET not in json.dumps(got, ensure_ascii=False)
    assert "dict" in got["error"]  # 类型名允许出现


def test_poll_struct_user_id_not_confirmed_no_leak(client: FakeClient) -> None:
    """user_id 变成携带 Cookie 的 dict：不得 str() 进返回值，也不得判 confirmed。"""
    client.session.queue(FakeResponse(json_data={"user_id": {"z_c0": SECRET}}))
    got = qr.poll(client, "T1")
    assert got["status"] != "confirmed"
    assert SECRET not in json.dumps(got, ensure_ascii=False)


def test_poll_error_message_truncated(client: FakeClient) -> None:
    client.session.queue(FakeResponse(json_data={"error": "x" * 5000}))
    got = qr.poll(client, "T1")
    assert got["status"] == "error" and len(got["error"]) <= 200


def test_poll_bool_status_not_scanned(client: FakeClient) -> None:
    """True == 1：bool 不得被误判为 scanned。"""
    client.session.queue(FakeResponse(json_data={"status": True}))
    assert qr.poll(client, "T1")["status"] == "error"


def test_poll_and_image_reject_malformed_token(client: FakeClient) -> None:
    """token 会被拼进 URL 路径：poll/image 同样强制白名单形态，且不发出请求。"""
    with pytest.raises(AuthError, match="token 不合法"):
        qr.poll(client, "a b/../c")
    with pytest.raises(AuthError, match="token 不合法"):
        qr.image(client, "a b/../c")
    assert client.session.calls == []


# ----------------------------------------------------------------------
# R1 审查 M6：HTTP 走一次性 Session，client.session 不再被并发共享
# ----------------------------------------------------------------------


def test_qr_http_uses_dedicated_sessions_not_client_session(
    client: FakeClient, session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start/image/poll 各自新建一次性 Session，用完即关；client.session 零 HTTP。"""
    created: list[FakeSession] = []
    queues = [
        [FakeResponse(text="U"), FakeResponse(json_data={"token": "T1"})],  # start：udid + qrcode
        [FakeResponse(content=b"JPEG")],                                   # image
        [FakeResponse(json_data={"status": 0})],                           # poll
    ]

    def factory() -> FakeSession:
        s = FakeSession(queues[len(created)])
        created.append(s)
        return s

    monkeypatch.setattr(qr, "_new_session", factory)
    assert qr.start(client)["token"] == "T1"
    assert qr.image(client, "T1") == b"JPEG"
    assert qr.poll(client, "T1")["status"] == "waiting"
    assert len(created) == 3 and len({id(s) for s in created}) == 3, "每次公开调用一个独立 Session"
    assert all(s.closed for s in created), "一次性 Session 必须用完即关"
    assert client.session.calls == [], "M6：扫码 HTTP 绝不经过 client.session"


def test_poll_concurrent_threads_use_isolated_sessions(
    client: FakeClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """双标签页并发轮询：各自独立 Session、各自队列，零异常零互踩。"""
    import threading

    created: list[FakeSession] = []
    lock = threading.Lock()

    def factory() -> FakeSession:
        s = FakeSession([FakeResponse(json_data={"status": 1})])
        with lock:
            created.append(s)
        return s

    monkeypatch.setattr(qr, "_new_session", factory)
    results: list[str] = []
    errors: list[BaseException] = []

    def loop() -> None:
        try:
            for _ in range(10):
                results.append(qr.poll(client, "T1")["status"])
        except BaseException as exc:  # noqa: BLE001 - 收集线程异常供主线程断言
            errors.append(exc)

    threads = [threading.Thread(target=loop) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], f"并发轮询不得抛任何异常：{errors[:3]}"
    assert results == ["scanned"] * 20
    assert len(created) == 20 and len({id(s) for s in created}) == 20, "每次 poll 一个一次性 Session"
    assert client.session.calls == []


# ----------------------------------------------------------------------
# 辅助函数与协议
# ----------------------------------------------------------------------

def test_qr_headers_defaults_and_override() -> None:
    headers = qr.qr_headers()
    assert headers["Referer"] == "https://www.zhihu.com/signup?next=%2F"
    merged = qr.qr_headers({"Origin": "https://example.com", "x-udid": "U"})
    assert merged["Origin"] == "https://example.com" and merged["x-udid"] == "U"
    assert "Referer" in headers, "extra 不得污染默认字典"


def test_client_without_timeout_uses_default(
    session: FakeSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """鸭子类型客户端没给 timeout 时回落 DEFAULT_TIMEOUT，不抛 AttributeError。"""

    class Bare:
        def __init__(self) -> None:
            self.session = session
            self.cookie_file = tmp_path / "c.json"

    monkeypatch.setattr(qr, "_new_session", lambda: session)
    bare = Bare()
    session.queue(FakeResponse(text="U"), FakeResponse(json_data={"token": "T"}))
    assert qr.start(bare)["token"] == "T"  # type: ignore[arg-type]
    assert session.calls[0]["timeout"] == qr.DEFAULT_TIMEOUT


def test_client_satisfies_protocol(client: FakeClient) -> None:
    assert isinstance(client, qr.QrLoginClient)


def test_status_constants_cover_spec() -> None:
    assert {
        qr.STATUS_WAITING, qr.STATUS_SCANNED, qr.STATUS_CONFIRMED,
        qr.STATUS_ERROR, qr.STATUS_EXPIRED,
    } == {"waiting", "scanned", "confirmed", "error", "expired"}
