"""auth/doctor.py 测试：d_c0 缺失告警 / 签名自检分支 / 限速 / 网络探测跳过。

全部离线：网络探测一律 network=False，需要覆盖探测分支时用 monkeypatch 打桩
requests.get（不产生真实请求）。fixture 直接放在本文件内（约定：不建 conftest.py）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import requests

from zhihu_downloader import __version__
from zhihu_downloader.auth import cookies, doctor
from zhihu_downloader.auth.doctor import Check, run_checks

# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------

FULL_COOKIES = {"z_c0": "2|1:0|xyz", "zse_ck": "ck-value", "d_c0": "100#dc0value"}


def by_name(results: list[Check]) -> dict[str, tuple[str, str]]:
    """按检查项名称索引：name -> (level, message)。"""
    return {name: (level, msg) for level, name, msg in results}


def level_of(results: list[Check], name: str) -> str:
    return by_name(results)[name][0]


def msg_of(results: list[Check], name: str) -> str:
    return by_name(results)[name][1]


@pytest.fixture()
def cookie_file(tmp_path: Path) -> Path:
    """写一份完整 Cookie（0600）并返回路径。"""
    path = tmp_path / "cookies.json"
    cookies.save(FULL_COOKIES, path)
    return path


# ----------------------------------------------------------------------
# 输出结构
# ----------------------------------------------------------------------

def test_run_checks_returns_triples(cookie_file: Path) -> None:
    """每项都是 (level, name, msg) 三元字符串，level 取值受限。"""
    results = run_checks(cookie_file=cookie_file, network=False)
    assert results
    for level, name, msg in results:
        assert isinstance(level, str) and isinstance(name, str) and isinstance(msg, str)
        assert level in doctor.ICONS, f"非法 level: {level}"
        assert name and msg


def test_check_names_follow_spec_order(cookie_file: Path) -> None:
    """检查项名称与顺序符合规格 §2.7（CLI 直接按序打印）。

    磁盘占用为 S3 接线后追加的 info 级观测项，固定排在最后。
    """
    names = [name for _lv, name, _msg in run_checks(cookie_file=cookie_file, network=False)]
    expected = ["版本", "Python/系统", "Cookie 存在", "z_c0", "zse_ck", "d_c0",
                "签名自检", "限速", "网络", "磁盘占用"]
    assert names[:3] == expected[:3]
    assert [n for n in names if n != "Cookie 权限"] == expected


def test_version_and_python_items(cookie_file: Path) -> None:
    results = run_checks(cookie_file=cookie_file, network=False)
    assert __version__ in msg_of(results, "版本")
    assert level_of(results, "Python/系统") == "ok"
    assert f"Python {'.'.join(str(x) for x in sys.version_info[:3])}" in msg_of(results, "Python/系统")


def test_python_below_min_is_error(monkeypatch: pytest.MonkeyPatch, cookie_file: Path) -> None:
    class V(tuple):
        pass

    fake = V((3, 9, 1))
    fake.major, fake.minor, fake.micro = 3, 9, 1  # type: ignore[attr-defined]
    monkeypatch.setattr(doctor.sys, "version_info", fake)
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "Python/系统") == "error"
    assert "3.10" in msg_of(results, "Python/系统")


# ----------------------------------------------------------------------
# Cookie 存在 / 关键字段
# ----------------------------------------------------------------------

def test_missing_cookie_file_is_warning_only(tmp_path: Path) -> None:
    """首次使用（无 Cookie）只告警不报错，且给出下一步命令。"""
    results = run_checks(cookie_file=tmp_path / "none.json", network=False)
    assert level_of(results, "Cookie 存在") == "warn"
    assert "login" in msg_of(results, "Cookie 存在")
    assert level_of(results, "z_c0") == "warn"
    assert level_of(results, "d_c0") == "warn", "未登录时 d_c0 缺失属正常，只 warn"
    assert not doctor.has_errors(results)


def test_corrupt_cookie_file_is_error(tmp_path: Path) -> None:
    path = tmp_path / "cookies.json"
    path.write_text("{ this is not json", encoding="utf-8")
    results = run_checks(cookie_file=path, network=False)
    assert level_of(results, "Cookie 存在") == "error"
    assert "重新登录" in msg_of(results, "Cookie 存在")
    assert doctor.has_errors(results)


def test_netscape_cookie_file_accepted(tmp_path: Path) -> None:
    """浏览器导出的 cookies.txt（含 #HttpOnly_）同样能诊断。"""
    path = tmp_path / "cookies.txt"
    path.write_text(
        ".zhihu.com\tTRUE\t/\tFALSE\t0\tz_c0\tv1\n"
        "#HttpOnly_.zhihu.com\tTRUE\t/\tTRUE\t0\td_c0\tv2\n",
        encoding="utf-8",
    )
    results = run_checks(cookie_file=path, network=False)
    assert level_of(results, "Cookie 存在") == "ok"
    assert level_of(results, "d_c0") == "ok"


def test_z_c0_missing_after_login_is_warn(cookie_file: Path, tmp_path: Path) -> None:
    partial = {k: v for k, v in FULL_COOKIES.items() if k != "z_c0"}
    path = tmp_path / "partial.json"
    cookies.save(partial, path)
    results = run_checks(cookie_file=path, network=False)
    assert level_of(results, "z_c0") == "warn"
    assert "重新登录" in msg_of(results, "z_c0") and "login" in msg_of(results, "z_c0")


def test_zse_ck_missing_is_warn_not_error(cookie_file: Path, tmp_path: Path) -> None:
    partial = {k: v for k, v in FULL_COOKIES.items() if k != "zse_ck"}
    path = tmp_path / "partial.json"
    cookies.save(partial, path)
    results = run_checks(cookie_file=path, network=False)
    assert level_of(results, "zse_ck") == "warn"
    assert not doctor.has_errors(results), "zse_ck 缺失属可降级项，不应判为错误"


def test_d_c0_missing_is_error(cookie_file: Path, tmp_path: Path) -> None:
    """已登录却缺 d_c0：签名必需字段缺失 → error，并说明后果（403）与下一步。"""
    partial = {k: v for k, v in FULL_COOKIES.items() if k != "d_c0"}
    path = tmp_path / "no_dc0.json"
    cookies.save(partial, path)
    results = run_checks(cookie_file=path, network=False)
    assert level_of(results, "d_c0") == "error"
    msg = msg_of(results, "d_c0")
    assert "x-zse-96" in msg and "403" in msg and "login" in msg
    assert doctor.has_errors(results)
    # 排障路径一：属 Cookie 缺失，签名自检只跳过，不谎报"签名失效"
    assert level_of(results, "签名自检") == "info"
    assert "跳过" in msg_of(results, "签名自检")


def test_cookie_permissions_checked(cookie_file: Path) -> None:
    if os.name == "nt":  # pragma: no cover - Windows 无 POSIX 权限语义
        pytest.skip("Windows 不支持 POSIX 权限断言")
    assert level_of(run_checks(cookie_file=cookie_file, network=False), "Cookie 权限") == "ok"
    os.chmod(cookie_file, 0o644)
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "Cookie 权限") == "warn"
    assert "chmod 600" in msg_of(results, "Cookie 权限")


def test_cookie_mode_info_on_windows(cookie_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R2 审计 #8：win32 上 os.chmod 语义弱，权限检查降级为 info 级 NTFS/OneDrive 提示。"""
    monkeypatch.setattr(doctor, "_os_is_windows", lambda: True)
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "Cookie 权限") == "info"
    msg = msg_of(results, "Cookie 权限")
    assert "NTFS ACL" in msg and "OneDrive" in msg
    assert not doctor.has_errors(results)


def test_cookie_mode_posix_still_asserts_0600(cookie_file: Path) -> None:
    """POSIX 分支保持 0600 断言（win32 提示不得吞掉真实权限检查）。"""
    if os.name == "nt":  # pragma: no cover
        pytest.skip("POSIX only")
    assert level_of(run_checks(cookie_file=cookie_file, network=False), "Cookie 权限") == "ok"


# ----------------------------------------------------------------------
# 签名自检：区分"Cookie 缺失"与"签名失效"
# ----------------------------------------------------------------------

def test_signature_self_check_ok(cookie_file: Path) -> None:
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "签名自检") == "ok"
    assert doctor.SIGN_PREFIX in msg_of(results, "签名自检")


def test_signature_self_check_uses_fixed_url(cookie_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    def fake(url: str, ck: dict[str, str]) -> dict[str, str]:
        seen.append((url, ck))
        return {"x-zse-96": doctor.SIGN_PREFIX + "abc", "x-zst-81": "3_2.0x"}

    monkeypatch.setattr(doctor.signature, "generate_zhihu_sign", fake)
    results = run_checks(cookie_file=cookie_file, network=False)
    assert seen and seen[0][0] == doctor.SIGN_CHECK_URL
    assert seen[0][1]["d_c0"] == FULL_COOKIES["d_c0"]
    assert level_of(results, "签名自检") == "ok"


def test_signature_expired_prefix_is_distinct_error(
    cookie_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """排障路径二：前缀不是 2.0_ → 判定为签名失效（算法问题），不得与 Cookie 缺失混淆。"""
    monkeypatch.setattr(
        doctor.signature, "generate_zhihu_sign",
        lambda url, ck: {"x-zse-96": "1.0_bad", "x-zst-81": "3_2.0x"},
    )
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "签名自检") == "error"
    msg = msg_of(results, "签名自检")
    assert "签名失效" in msg and "升级" in msg
    assert "重新登录" not in msg, "签名失效不应引导用户去重新登录"
    assert level_of(results, "d_c0") == "ok", "Cookie 本身没问题，只有算法版本不匹配"


def test_signature_empty_result_is_error(cookie_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.signature, "generate_zhihu_sign", lambda url, ck: {})
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "签名自检") == "error"
    assert "x-zse-96" in msg_of(results, "签名自检")


def test_signature_exception_is_error(cookie_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, ck: dict[str, str]) -> dict[str, str]:
        raise RuntimeError("算法炸了")

    monkeypatch.setattr(doctor.signature, "generate_zhihu_sign", boom)
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "签名自检") == "error"
    assert "签名生成异常" in msg_of(results, "签名自检")


def test_signature_missing_zst81_is_warn(cookie_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor.signature, "generate_zhihu_sign",
        lambda url, ck: {"x-zse-96": doctor.SIGN_PREFIX + "abc"},
    )
    results = run_checks(cookie_file=cookie_file, network=False)
    assert level_of(results, "签名自检") == "warn"
    assert "x-zst-81" in msg_of(results, "签名自检")


def test_real_signature_passes_self_check(cookie_file: Path) -> None:
    """不打桩跑真实 signature：钉住"当前实现能过自检"这一回归点。"""
    sign = doctor.signature.generate_zhihu_sign(doctor.SIGN_CHECK_URL, dict(FULL_COOKIES))
    assert sign["x-zse-96"].startswith(doctor.SIGN_PREFIX)
    assert level_of(run_checks(cookie_file=cookie_file, network=False), "签名自检") == "ok"


# ----------------------------------------------------------------------
# 限速合理性
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "level"),
    [
        (None, "ok"),
        (2.0, "ok"),
        (0.5, "ok"),
        (5.0, "ok"),
        (0, "warn"),
        (-1, "warn"),
        (0.1, "warn"),
        (50.0, "warn"),
    ],
)
def test_rate_limit_levels(value: float | None, level: str) -> None:
    results = run_checks(cookie_file=None, rate_limit=value, network=False)
    assert level_of(results, "限速") == level


def test_rate_limit_message_actionable() -> None:
    results = run_checks(cookie_file=None, rate_limit=99, network=False)
    assert str(doctor.MAX_RATE_LIMIT) in msg_of(results, "限速")
    results = run_checks(cookie_file=None, rate_limit=0, network=False)
    assert "限速" in msg_of(results, "限速") and "反爬" in msg_of(results, "限速")


def test_rate_limit_unparseable_is_warn() -> None:
    results = run_checks(cookie_file=None, rate_limit="很快", network=False)  # type: ignore[arg-type]
    assert level_of(results, "限速") == "warn"


# ----------------------------------------------------------------------
# 网络探测（默认跳过，测试零网络）
# ----------------------------------------------------------------------

def test_network_skipped() -> None:
    results = run_checks(cookie_file=None, network=False)
    assert level_of(results, "网络") == "info"
    assert "跳过" in msg_of(results, "网络")


def test_network_probe_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class Resp:
        status_code = 200

    def fake_get(url: str, **kwargs: object) -> Resp:
        calls.append(url)
        return Resp()

    monkeypatch.setattr(doctor.requests, "get", fake_get)
    results = run_checks(cookie_file=None, network=True, network_timeout=3)
    assert calls == [doctor.NETWORK_PROBE_URL]
    assert level_of(results, "网络") == "ok"
    assert "200" in msg_of(results, "网络")


def test_network_probe_403_is_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    class Resp:
        status_code = 403

    monkeypatch.setattr(doctor.requests, "get", lambda url, **kw: Resp())
    results = run_checks(cookie_file=None, network=True)
    assert level_of(results, "网络") == "warn"
    assert "Cookie" in msg_of(results, "网络")


def test_network_probe_failure_is_warn_not_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **kwargs: object) -> None:
        raise requests.ConnectionError("离线")

    monkeypatch.setattr(doctor.requests, "get", boom)
    results = run_checks(cookie_file=None, network=True)
    assert level_of(results, "网络") == "warn"
    assert "离线" in msg_of(results, "网络")


# ----------------------------------------------------------------------
# 渲染辅助（CLI / Web 共用）
# ----------------------------------------------------------------------

def test_format_checks_and_counts(cookie_file: Path) -> None:
    results = run_checks(cookie_file=cookie_file, network=False)
    text = doctor.format_checks(results)
    assert text.count("\n") == len(results) - 1
    assert doctor.ICONS["ok"] in text
    counts = doctor.count_levels(results)
    assert sum(counts.values()) == len(results)
    assert doctor.has_errors(results) is False
    assert "无错误" in doctor.summary_line(results)


def test_summary_line_reports_errors(cookie_file: Path, tmp_path: Path) -> None:
    partial = {k: v for k, v in FULL_COOKIES.items() if k != "d_c0"}
    path = tmp_path / "no_dc0.json"
    cookies.save(partial, path)
    results = run_checks(cookie_file=path, network=False)
    assert doctor.has_errors(results)
    assert "1 个错误" in doctor.summary_line(results)


def test_default_cookie_file_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """cookie_file=None 时诊断 DEFAULT_COOKIE_FILE。"""
    target = tmp_path / "default.json"
    monkeypatch.setattr(cookies, "DEFAULT_COOKIE_FILE", target)
    results = run_checks(network=False)
    assert str(target) in msg_of(results, "Cookie 存在")
    cookies.save(FULL_COOKIES, target)
    assert level_of(run_checks(network=False), "Cookie 存在") == "ok"


# ----------------------------------------------------------------------
# 磁盘占用（S3 接线：CheckpointStore.total_bytes，info 级观测项）
# ----------------------------------------------------------------------

def _disk_item(results: list[Check]) -> Check:
    items = [c for c in results if c[1] == "磁盘占用"]
    assert len(items) == 1, "磁盘占用必须恰好一条"
    return items[0]


def test_disk_usage_appended_last_and_info(cookie_file: Path, tmp_path: Path) -> None:
    """固定排在最后；level 恒为 info（观测项不得影响 has_errors/退出码）。"""
    results = run_checks(cookie_file=cookie_file, network=False, state_dir=tmp_path / "state")
    assert results[-1][1] == "磁盘占用"
    assert _disk_item(results)[0] == "info"
    assert not doctor.has_errors(results)


def test_disk_usage_missing_dir_counts_zero(cookie_file: Path, tmp_path: Path) -> None:
    """state_dir 不存在 → total_bytes 语义为 0，正常出 info。"""
    _lv, _n, msg = _disk_item(
        run_checks(cookie_file=cookie_file, network=False, state_dir=tmp_path / "nothing")
    )
    assert "0 B" in msg


def test_disk_usage_recursive_total_includes_chapters(cookie_file: Path, tmp_path: Path) -> None:
    """rglob 汇总：书状态 json 与 chapters/ 缓存一并计入（2048+1024=3.0 KB）。"""
    sd = tmp_path / "state"
    (sd / "chapters").mkdir(parents=True)
    (sd / "book.json").write_bytes(b"x" * 2048)
    (sd / "chapters" / "c1.json").write_bytes(b"y" * 1024)
    _lv, _n, msg = _disk_item(
        run_checks(cookie_file=cookie_file, network=False, state_dir=sd)
    )
    assert "3.0 KB" in msg


def test_disk_usage_over_soft_limit_hints_prune(
    cookie_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """>500MB：中文 prune 指引原文钉（书架移除不再追更的书）。"""
    monkeypatch.setattr(doctor.CheckpointStore, "total_bytes", lambda self: 600 * 1024 * 1024)
    _lv, _n, msg = _disk_item(
        run_checks(cookie_file=cookie_file, network=False, state_dir=tmp_path / "state")
    )
    assert "500 MB" in msg
    assert "可在书架移除不再追更的书以 prune 缓存" in msg


def test_disk_usage_stats_failure_degrades_to_info(
    cookie_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """total_bytes 抛 OSError 也只 info + "不影响其他诊断"，绝不起 error。"""
    def boom(self: object) -> int:
        raise OSError("磁盘怪癖")

    monkeypatch.setattr(doctor.CheckpointStore, "total_bytes", boom)
    results = run_checks(cookie_file=cookie_file, network=False, state_dir=tmp_path / "state")
    level, _n, msg = _disk_item(results)
    assert level == "info"
    assert "不影响其他诊断" in msg
    assert not doctor.has_errors(results)


def test_disk_usage_default_state_dir(cookie_file: Path) -> None:
    """不传 state_dir（CLI cmd_doctor 现况）：懒 import 解析默认目录，不抛。"""
    results = run_checks(cookie_file=cookie_file, network=False)
    assert _disk_item(results)[0] == "info"
    assert str(doctor._default_state_dir()) in _disk_item(results)[2]
