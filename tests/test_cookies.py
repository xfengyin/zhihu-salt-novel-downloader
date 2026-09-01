"""auth/cookies.py 测试：三种格式解析 / 0600 权限 / logout / 损坏内容报错。

全部离线（只碰 tmp_path 文件系统）。fixture 直接放在本文件内（约定：不建 conftest.py）。
"""

from __future__ import annotations

import json
import os
import stat
import threading
from pathlib import Path

import pytest

from zhihu_downloader.auth import cookies
from zhihu_downloader.errors import AuthError

# ----------------------------------------------------------------------
# fixture / 常量
# ----------------------------------------------------------------------

NETSCAPE_TEXT = """# Netscape HTTP Cookie File
# https://curl.se/docs/http-cookies.html
.zhihu.com\tTRUE\t/\tFALSE\t1893456000\tz_c0\t"2|1:0|z_c0_value"
#HttpOnly_.zhihu.com\tTRUE\t/\tTRUE\t1893456000\td_c0\tdc0_secret_value
.zhihu.com\tTRUE\t/api\tFALSE\t0\tq_c1\tq1_value

www.zhihu.com\tFALSE\t/section\tFALSE\t1893456000\tzse_ck\tzse_value
"""

RAW_TEXT = "z_c0=abc123; d_c0=dc0value;  q_c1=q1 ;novalue;\n"

JSON_TEXT = json.dumps({"z_c0": "abc123", "d_c0": "dc0value", "空值被丢弃": ""}, ensure_ascii=False)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# ----------------------------------------------------------------------
# 格式 1：JSON
# ----------------------------------------------------------------------

def test_parse_content_json_object():
    """JSON 对象内容解析为字典，空值键被丢弃。"""
    assert cookies.parse_content(JSON_TEXT) == {"z_c0": "abc123", "d_c0": "dc0value"}


def test_parse_content_json_scalar_values_coerced_to_str():
    """JSON 里的非字符串值统一转成字符串（Cookie 值必须是 str）。"""
    assert cookies.parse_content('{"z_c0": 123, "n": true}') == {"z_c0": "123", "n": "True"}


def test_parse_content_json_array_rejected():
    """主审裁决落地（E2 上报的契约问题 #1）：JSON 数组必须明确拒绝，
    不得退化成 name=value 行解析产生垃圾键。"""
    with pytest.raises(AuthError, match="必须是对象"):
        cookies.parse_content('["z_c0=abc"]')


def test_parse_content_json_array_without_equals_raises():
    """数组一律走 JSON 分支拒绝（含无 = 的数组）。"""
    with pytest.raises(AuthError, match="必须是对象"):
        cookies.parse_content('["a", "b"]')


# ----------------------------------------------------------------------
# 格式 2：Netscape cookies.txt
# ----------------------------------------------------------------------

def test_parse_content_netscape_seven_columns():
    """7 列 Netscape 格式：取第 6/7 列为 name/value，跳过注释行。"""
    got = cookies.parse_content(NETSCAPE_TEXT)
    assert got == {
        "z_c0": '"2|1:0|z_c0_value"',
        "d_c0": "dc0_secret_value",
        "q_c1": "q1_value",
        "zse_ck": "zse_value",
    }


def test_parse_content_netscape_httponly_prefix_stripped():
    """#HttpOnly_ 前缀行必须被解析（浏览器导出的 d_c0 常带该前缀）。"""
    line = "#HttpOnly_.zhihu.com\tTRUE\t/\tTRUE\t0\td_c0\tonly_value\n"
    assert cookies.parse_content(line) == {"d_c0": "only_value"}


def test_parse_content_netscape_expiry_zero_kept():
    """会话 Cookie（expiry=0）仍应保留：只要求 name/value 非空。"""
    assert cookies.parse_content(".zhihu.com\tTRUE\t/\tFALSE\t0\tsess\tv1\n") == {"sess": "v1"}


def test_parse_content_netscape_missing_name_value_skipped():
    """name 或 value 为空的行被跳过，避免污染 Cookie。"""
    text = ".zhihu.com\tTRUE\t/\tFALSE\t0\t\t\n.zhihu.com\tTRUE\t/\tFALSE\t0\tok\tv\n"
    assert cookies.parse_content(text) == {"ok": "v"}


# ----------------------------------------------------------------------
# 格式 3：原始 name=value 串
# ----------------------------------------------------------------------

def test_parse_cookie_string_basic():
    """标准 "k=v; k2=v2" 串解析。"""
    assert cookies.parse_cookie_string("z_c0=abc; d_c0=xyz") == {"z_c0": "abc", "d_c0": "xyz"}


def test_parse_cookie_string_tolerates_spaces_and_junk():
    """容忍多余空格、缺 = 的碎片与空值。"""
    assert cookies.parse_cookie_string(RAW_TEXT) == {"z_c0": "abc123", "d_c0": "dc0value", "q_c1": "q1"}


def test_parse_cookie_string_value_with_equals():
    """值里含 = 时只在第一个 = 处切分（z_c0 的 base64 值常含 = 填充）。"""
    assert cookies.parse_cookie_string("z_c0=2|1:0==") == {"z_c0": "2|1:0=="}


def test_parse_content_raw_multi_lines():
    """原始串多行形式（无 tab）也走 name=value 分支。"""
    assert cookies.parse_content("z_c0=abc\nd_c0=xyz\n") == {"z_c0": "abc", "d_c0": "xyz"}


# ----------------------------------------------------------------------
# 损坏 / 非法内容报错（中文可操作）
# ----------------------------------------------------------------------

def test_parse_content_empty_raises():
    with pytest.raises(AuthError, match="为空"):
        cookies.parse_content("   \n ")


def test_parse_content_broken_json_raises():
    """以 { 开头但 JSON 非法：报解析失败，且不回落到行式解析静默成功。"""
    with pytest.raises(AuthError, match="JSON 解析失败"):
        cookies.parse_content('{"z_c0": "abc",,}')


def test_parse_content_unparseable_junk_raises():
    with pytest.raises(AuthError, match="无法从内容中解析出任何 Cookie"):
        cookies.parse_content("这不是 Cookie\n乱七八糟的一行\n")


def test_load_missing_file_raises_with_hint(tmp_path: Path):
    """文件不存在时报错要带下一步（扫码登录）。"""
    missing = tmp_path / "nope.json"
    with pytest.raises(AuthError) as exc:
        cookies.load(missing)
    assert "不存在" in str(exc.value) and "login" in str(exc.value)


def test_load_corrupt_file_raises(tmp_path: Path):
    broken = tmp_path / "cookies.json"
    broken.write_text("{oops", encoding="utf-8")
    with pytest.raises(AuthError, match="JSON 解析失败"):
        cookies.load(broken)


def test_load_directory_raises(tmp_path: Path):
    """路径是目录时也要给出中文 AuthError，而不是裸 OSError。"""
    with pytest.raises(AuthError):
        cookies.load(tmp_path)


# ----------------------------------------------------------------------
# load(dict) 与保存/权限
# ----------------------------------------------------------------------

def test_load_dict_returns_copy():
    source = {"z_c0": "abc"}
    got = cookies.load(source)
    got["d_c0"] = "xyz"
    assert source == {"z_c0": "abc"}, "load 必须返回副本，不能把调用方的字典改脏"


def test_save_creates_parent_and_sets_0600(tmp_path: Path):
    """保存路径的父目录自动创建，且权限 0600（Cookie 等同密码）。"""
    target = tmp_path / "nested" / "dir" / "cookies.json"
    saved = cookies.save({"z_c0": "abc", "d_c0": "xyz"}, target)
    assert saved == target and target.exists()
    if os.name != "nt":  # pragma: no cover - Windows 无 POSIX 权限语义
        assert _mode(target) == 0o600


def test_save_roundtrip_json(tmp_path: Path):
    target = tmp_path / "cookies.json"
    data = {"z_c0": "2|1:0", "d_c0": "abc=", "备注": "中文键"}
    cookies.save(data, target)
    assert json.loads(target.read_text(encoding="utf-8")) == data
    assert cookies.load(target) == data


def test_save_is_atomic_and_leaves_no_tmp(tmp_path: Path):
    """原子写：不留 .tmp 残留；覆盖已有文件后内容正确。"""
    target = tmp_path / "cookies.json"
    cookies.save({"z_c0": "old"}, target)
    cookies.save({"z_c0": "new", "d_c0": "d"}, target)
    assert cookies.load(target) == {"z_c0": "new", "d_c0": "d"}
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_overwrites_permission_of_existing_file(tmp_path: Path):
    """覆盖一个 0644 的旧文件后，最终权限仍是 0600。"""
    target = tmp_path / "cookies.json"
    target.write_text("{}", encoding="utf-8")
    if os.name == "nt":  # pragma: no cover - Windows 无 POSIX 权限语义
        pytest.skip("Windows 不支持 POSIX chmod 断言")
    os.chmod(target, 0o644)
    cookies.save({"z_c0": "abc"}, target)
    assert _mode(target) == 0o600


def test_save_default_path_is_module_constant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """不传 path 时落到 DEFAULT_COOKIE_FILE（CLI/服务端共用同一份 Cookie）。"""
    target = tmp_path / "default" / "cookies.json"
    monkeypatch.setattr(cookies, "DEFAULT_COOKIE_FILE", target)
    assert cookies.save({"z_c0": "abc"}) == target
    assert target.exists()


# ----------------------------------------------------------------------
# R2 审计 #8：0600 竞态窗口（umask=0 下创建瞬间不得全局可读）
# ----------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="Windows 无 POSIX 权限语义")
def test_save_under_umask_zero_is_0600(tmp_path: Path):
    """旧实现 write_text 先以 0666&~umask 落盘再 chmod：umask=0 瞬间全局可读。

    修复后 O_CREAT|O_EXCL 的 0600 在创建当刻生效，任何 umask 下最终都是 0600。
    """
    old_umask = os.umask(0)
    try:
        target = tmp_path / "cookies.json"
        cookies.save({"z_c0": "abc"}, target)
    finally:
        os.umask(old_umask)
    assert _mode(target) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="Windows 无 POSIX 权限语义")
def test_save_under_permissive_umask_never_widens(tmp_path: Path):
    """umask 对 O_CREAT mode 只做减法：严格 umask 下不会更宽（仍 ≤0600）。"""
    old_umask = os.umask(0o077)
    try:
        target = tmp_path / "cookies.json"
        cookies.save({"z_c0": "abc"}, target)
    finally:
        os.umask(old_umask)
    assert _mode(target) == 0o600


def test_save_unaffected_by_legacy_stale_tmp(tmp_path: Path):
    """R1 审查 M1：新 tmp 名带 pid+tid 唯一后缀，旧版固定名残留既不卡保存，
    也绝不被本进程 unlink（那可能是另一个写者正在使用的文件）。"""
    target = tmp_path / "cookies.json"
    legacy = tmp_path / "cookies.json.tmp"
    legacy.write_text("half-written-junk", encoding="utf-8")
    cookies.save({"z_c0": "fresh"}, target)
    assert cookies.load(target) == {"z_c0": "fresh"}
    assert legacy.exists()  # 别人（旧版/他进程）的文件，不碰


def test_save_tmp_name_is_unique_per_thread(tmp_path: Path):
    """R1 M1：tmp 名含 pid+tid——两个线程的 tmp 不可能同名互相 replace。"""
    target = tmp_path / "cookies.json"
    seen: list[str] = []
    real_open = __import__("os").open

    def spy_open(file: object, *args: object, **kwargs: object) -> int:
        seen.append(str(file))
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    import os as os_module
    original = os_module.open
    os_module.open = spy_open  # type: ignore[assignment]
    try:
        cookies.save({"a": "1"}, target)
        cookies.save({"b": "2"}, target)  # 同线程两次：名字相同且已被 replace 消费，OK
    finally:
        os_module.open = original  # type: ignore[assignment]
    assert seen and seen[0].endswith(".tmp")
    import threading
    assert str(threading.get_ident()) in seen[0] and str(__import__("os").getpid()) in seen[0]


def test_save_concurrent_threads_do_not_race(tmp_path: Path):
    """R1 M1 回归钉（主审处方版）：4 线程 save×20 轮 + 同时 2 线程 load。

    旧实现（固定 tmp 名 + 撞名 unlink 重试）在并发下实测：3 次裸
    FileNotFoundError（A 的 os.replace 搬走 B 的 tmp）+ 2 次 load 读到
    空文件 JSONDecodeError（保存窗口内登录态瞬时"损坏"）。修复后必须：
      * 写侧零异常；
      * 读侧每一次 load 都成功，且结果 ∈ {初始值} ∪ {全部写值}
        ——os.replace 原子可见，永远读不到半成品/空文件；
      * 结束后目录只剩目标文件，无 tmp 残留。
    """
    from concurrent.futures import ThreadPoolExecutor

    target = tmp_path / "cookies.json"
    cookies.save({"z_c0": "initial"}, target)  # 先立一个基线值，读线程从第一轮起就有合法结果
    valid = {"initial"} | {f"writer-{n}-{i}" for n in range(4) for i in range(20)}
    stop = threading.Event()
    read_values: list[str] = []
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for i in range(20):
                cookies.save({"z_c0": f"writer-{n}-{i}"}, target)
        except BaseException as exc:  # noqa: BLE001 - 收集线程异常供主线程断言
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                got = cookies.load(target)
                read_values.append(got["z_c0"])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        reads = [pool.submit(reader) for _ in range(2)]
        writes = [pool.submit(writer, n) for n in range(4)]
        for w in writes:
            w.result()
        stop.set()
        for r in reads:
            r.result()

    assert errors == [], f"并发下不得有任何裸异常：{errors[:3]}"
    assert read_values, "读线程必须实际读到过内容"
    assert set(read_values) <= valid, "每次 load 结果 ∈ {旧值, 新值}（原子可见性）"
    assert cookies.load(target)["z_c0"] in valid
    # 目录只剩最终文件：无 tmp 残留（唯一名 + replace 后不存在悬挂写者）
    assert [q.name for q in tmp_path.iterdir()] == ["cookies.json"]


def test_save_os_error_wrapped_as_auth_error(tmp_path: Path):
    """R1 M1：落盘 OSError 不得裸穿（QR/server 路径会 500）→ 中文 AuthError。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("我是一个普通文件", encoding="utf-8")
    with pytest.raises(AuthError) as exc:
        cookies.save({"z_c0": "abc"}, blocker / "cookies.json")
    message = str(exc.value)
    assert "保存 Cookie 失败" in message and "login" in message


def test_save_leaves_no_tmp_on_serialize_error(tmp_path: Path):
    """序列化失败（值不可 JSON 化）时不留半成品 .tmp 明文。"""
    target = tmp_path / "cookies.json"
    with pytest.raises(TypeError):
        cookies.save({"z_c0": object()}, target)
    assert list(tmp_path.glob("*.tmp")) == [] and not target.exists()


# ----------------------------------------------------------------------
# logout
# ----------------------------------------------------------------------

def test_logout_removes_file(tmp_path: Path):
    target = tmp_path / "cookies.json"
    cookies.save({"z_c0": "abc"}, target)
    assert cookies.logout(target) is True
    assert not target.exists()


def test_logout_missing_file_returns_false(tmp_path: Path):
    assert cookies.logout(tmp_path / "nothing.json") is False


def test_logout_race_file_vanishes_between_check_and_unlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """R1 m5：exists→unlink 窗口里文件被抢先删除，不得裸抛 FileNotFoundError。

    打桩 Path.unlink：真删（模拟抢先方）后补抛 FileNotFoundError（模拟竞态），
    logout 必须幂等返回 False。
    """
    target = tmp_path / "cookies.json"
    cookies.save({"z_c0": "abc"}, target)
    real_unlink = Path.unlink

    def stealing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        real_unlink(self, *args, **kwargs)
        raise FileNotFoundError(str(self))

    monkeypatch.setattr(Path, "unlink", stealing_unlink)
    assert cookies.logout(target) is False
    monkeypatch.undo()
    assert not target.exists()


def test_logout_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "cookies.json"
    monkeypatch.setattr(cookies, "DEFAULT_COOKIE_FILE", target)
    cookies.save({"z_c0": "abc"})
    assert cookies.logout() is True
    assert cookies.logout() is False


# ----------------------------------------------------------------------
# 契约常量
# ----------------------------------------------------------------------

def test_key_cookies_contains_signing_cookie():
    """KEY_COOKIES 必须含 d_c0：doctor 与 Web UI 都按它展示签名能力。"""
    assert set(cookies.KEY_COOKIES) == {"z_c0", "zse_ck", "d_c0"}


def test_default_cookie_file_location():
    """默认 Cookie 位置：~/.zhihu_downloader/cookies.json（规格 §3）。"""
    assert cookies.DEFAULT_COOKIE_FILE == Path.home() / ".zhihu_downloader" / "cookies.json"
