"""auth/browser.py 测试：可选依赖缺失提示 / 多浏览器降级 / 知乎域过滤 / 落盘。

全部离线：browser_cookie3 用 sys.modules 注入替身，绝不触碰真实浏览器 Cookie 库。
fixture 直接放在本文件内（约定：不建 conftest.py）。
"""

from __future__ import annotations

import os
import stat
import sys
import types
from pathlib import Path

import pytest

from zhihu_downloader.auth import browser, cookies
from zhihu_downloader.errors import AuthError

# ----------------------------------------------------------------------
# 替身
# ----------------------------------------------------------------------


class FakeCookie:
    """http.cookiejar.Cookie 的最小替身。"""

    def __init__(self, name: str, value: str, domain: str) -> None:
        self.name = name
        self.value = value
        self.domain = domain


def make_backend(**jars: object) -> types.SimpleNamespace:
    """构造 browser_cookie3 替身模块：每个浏览器返回 jar 或抛异常。"""

    def factory(key: str):
        def getter(domain_name: str = "") -> object:
            item = jars.get(key, [])
            if isinstance(item, BaseException):
                raise item
            return item  # type: ignore[return-value]

        return getter

    return types.SimpleNamespace(
        chrome=factory("chrome"),
        firefox=factory("firefox"),
        edge=factory("edge"),
    )


@pytest.fixture()
def no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 import browser_cookie3 失败（模拟未安装可选依赖）。"""
    monkeypatch.setitem(sys.modules, "browser_cookie3", None)


# ----------------------------------------------------------------------
# 可选依赖缺失（规格 §2.6 硬要求）
# ----------------------------------------------------------------------

def test_missing_dependency_message(no_backend: None) -> None:
    with pytest.raises(AuthError) as exc:
        browser.fetch_zhihu_cookies()
    msg = str(exc.value)
    assert "browser-cookie3" in msg
    assert "pip install" in msg and "[browser]" in msg, "必须给出可直接复制的安装命令"
    assert "zhihu-downloader login" in msg, "还要给出扫码登录这条替代路径"


def test_load_backend_missing(no_backend: None) -> None:
    with pytest.raises(AuthError):
        browser.load_backend()


def test_is_available_false(no_backend: None) -> None:
    assert browser.is_available() is False


def test_is_available_true_with_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入替身模块即可视为可用（本仓库 venv 未装 browser-cookie3 属正常）。"""
    monkeypatch.setitem(sys.modules, "browser_cookie3", make_backend())
    assert browser.is_available() is True


# ----------------------------------------------------------------------
# 正常导入
# ----------------------------------------------------------------------

def test_fetch_from_chrome(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make_backend(chrome=[
        FakeCookie("z_c0", "secret", ".zhihu.com"),
        FakeCookie("d_c0", "dc0", "#HttpOnly_.zhihu.com"),
        FakeCookie("other", "x", ".example.com"),
    ])
    monkeypatch.setitem(sys.modules, "browser_cookie3", backend)
    got = browser.fetch_zhihu_cookies()
    assert got == {"z_c0": "secret", "d_c0": "dc0"}, "非知乎域 Cookie 必须被过滤掉"


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("zhihu.com", True),
        (".zhihu.com", True),
        ("www.zhihu.com", True),
        (".www.zhihu.com", True),
        ("#HttpOnly_.zhihu.com", True),
        ("ZHIHU.COM", True),
        ("notzhihu.com", False),
        ("zhihu.com.evil.cn", False),
        ("evil.cn", False),
        ("", False),
    ],
)
def test_domain_matches(domain: str, expected: bool) -> None:
    """域匹配按后缀精确判定，仿冒域不得混入。"""
    assert browser._domain_matches(domain) is expected


def test_fetch_excludes_lookalike_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make_backend(chrome=[
        FakeCookie("a", "1", "zhihu.com"),
        FakeCookie("b", "2", "www.zhihu.com"),
        FakeCookie("evil", "3", "zhihu.com.evil.cn"),
    ])
    monkeypatch.setitem(sys.modules, "browser_cookie3", backend)
    assert browser.fetch_zhihu_cookies() == {"a": "1", "b": "2"}


def test_fetch_falls_back_to_firefox(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make_backend(
        chrome=[],
        firefox=[FakeCookie("z_c0", "from_ff", ".zhihu.com")],
    )
    monkeypatch.setitem(sys.modules, "browser_cookie3", backend)
    assert browser.fetch_zhihu_cookies() == {"z_c0": "from_ff"}


def test_fetch_skips_broken_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chrome 锁库/解密失败时继续尝试下一个浏览器。"""
    backend = make_backend(
        chrome=PermissionError("database is locked"),
        edge=[FakeCookie("d_c0", "from_edge", ".zhihu.com")],
    )
    monkeypatch.setitem(sys.modules, "browser_cookie3", backend)
    assert browser.fetch_zhihu_cookies() == {"d_c0": "from_edge"}


def test_fetch_legacy_signature_without_domain_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """老版本 browser_cookie3 无 domain_name 形参：TypeError 后应无参重试。"""
    calls: list[str] = []

    def chrome() -> list[FakeCookie]:
        calls.append("no_kw")
        return [FakeCookie("z_c0", "v", ".zhihu.com")]

    monkeypatch.setitem(sys.modules, "browser_cookie3", types.SimpleNamespace(chrome=chrome))
    assert browser.fetch_zhihu_cookies(["chrome"]) == {"z_c0": "v"}
    assert calls == ["no_kw"]


def test_fetch_all_empty_raises_with_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = make_backend(chrome=[], firefox=[], edge=RuntimeError("解密失败"))
    monkeypatch.setitem(sys.modules, "browser_cookie3", backend)
    with pytest.raises(AuthError) as exc:
        browser.fetch_zhihu_cookies()
    msg = str(exc.value)
    assert "Chrome" in msg and "Firefox" in msg and "Edge" in msg, "逐个列出失败原因便于排障"
    assert "www.zhihu.com" in msg and "zhihu-downloader login" in msg


def test_fetch_unknown_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "browser_cookie3", make_backend())
    with pytest.raises(AuthError, match="不支持的浏览器类型"):
        browser.fetch_zhihu_cookies(["safari"])


def test_fetch_empty_browser_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "browser_cookie3", make_backend())
    with pytest.raises(AuthError, match="浏览器列表为空"):
        browser.fetch_zhihu_cookies(["  "])


def test_fetch_backend_without_getter(monkeypatch: pytest.MonkeyPatch) -> None:
    """替身模块缺 chrome 函数：记为不支持并继续降级，最终报错而不是崩。"""
    monkeypatch.setitem(sys.modules, "browser_cookie3", types.SimpleNamespace())
    with pytest.raises(AuthError, match="不支持该浏览器"):
        browser.fetch_zhihu_cookies(["chrome"])


def test_fetch_saves_with_0600(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    backend = make_backend(chrome=[FakeCookie("z_c0", "v", ".zhihu.com")])
    monkeypatch.setitem(sys.modules, "browser_cookie3", backend)
    target = tmp_path / "cookies.json"
    got = browser.fetch_zhihu_cookies(save_to=target)
    assert got == {"z_c0": "v"}
    assert cookies.load(target) == {"z_c0": "v"}
    if os.name != "nt":  # pragma: no cover - Windows 无 POSIX 权限语义
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_default_browsers_match_spec() -> None:
    assert browser.DEFAULT_BROWSERS == ("chrome", "firefox", "edge")
