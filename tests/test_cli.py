"""cli.py 测试（规格 §2.15 / §4）：全部离线，不触网、不起服务、不写真实 HOME。

覆盖点：
* 参数钳制（rate-limit / workers）与越界告警；
* 子命令分发 + 无参数裸调用 = gui（双击即用）+ --version 单源；
* 批量下载：单本失败不中断其余 + 汇总；
* 进度条渲染（capsys 抓 stderr、CR 原地刷新、retry 行内黄色提示且不重画条体）；
* 失败分类（errors.py 层级）：CheckpointError 透出消息本体（含 --no-resume）、
  未预期异常只打一行中文、任何路径都不许把 traceback 甩给用户；
* rate_limit 语义（E1）：--workers 文案写"并行解析数"，不宣传成倍提速；
* Windows UTF-8 兜底不崩；
* doctor 退出码语义（有 error -> 1，仅警告 -> 0）；
* gui：懒 import create_app、端口 +1 重试、非回环安全告警、--no-browser；
* login：扫码（二维码临时文件 + 轮询）与浏览器导入失败提示；
* shelf：list 表格 / remove / update 追更链路。

约定：不依赖 app/server.py 的真实实现——gui 相关测试往 sys.modules 里注入假模块。
"""

from __future__ import annotations

import argparse
import io
import re
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from zhihu_downloader import __version__, cli, errors
from zhihu_downloader.auth import cookies as cookie_store
from zhihu_downloader.errors import AuthError, ParseError, SaltError, ZhihuError
from zhihu_downloader.shelf import Shelf, book_id_for
from zhihu_downloader.types import (
    Article,
    Block,
    BookResult,
    ChapterRef,
    ProgressEvent,
    ShelfBook,
)

URL = "https://www.zhihu.com/market/paid_column/123"
URL2 = "https://www.zhihu.com/market/paid_column/456"
URL3 = "https://www.zhihu.com/market/paid_column/789"


# ----------------------------------------------------------------------
# 公共夹具与工具
# ----------------------------------------------------------------------


def make_result(title: str = "测试书", url: str = URL, files: list[str] | None = None) -> BookResult:
    """构造一个成功的下载结果。"""
    return BookResult(title=title, url=url, chapters=3,
                      files=files if files is not None else ["/tmp/" + title + ".md"])


def make_meta(urls: list[str]) -> types.SimpleNamespace:
    """构造 resolve_book 的返回值替身（CLI 只用 chapters 字段）。"""
    return types.SimpleNamespace(
        chapters=[ChapterRef(url=u, title=f"第{i}章", index=i) for i, u in enumerate(urls, 1)])


@pytest.fixture()
def shelf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Shelf:
    """把 CLI 用到的书架指向临时文件（绝不写真实 HOME）。"""
    store = Shelf(tmp_path / "shelf.json")
    monkeypatch.setattr(cli, "make_shelf", lambda: store)
    return store


class FakeClient:
    """ZhihuClient 的替身：只实现 CLI 真正消费的成员，并记录被传进来的参数。

    缺失属性会抛出**指名道姓**的 AttributeError：模块层一旦新增消费点，报错直接
    告诉你该往这里补什么，而不是留一个裸的属性错误让人猜。用 __getattr__ 而不是
    塞一堆假属性，是为了让 hasattr(client, "on_retry") 这类探测保持真实的 False 语义。
    """

    def __init__(self) -> None:
        self.cookie_file = Path("/tmp/cookies.json")
        self.rate_limit: float | None = None
        self.loaded: list[dict[str, str]] = []
        self.cookies: dict[str, str] = {}

    def load_cookies(self, source: Any) -> None:
        """CLI 导入 Cookie 的入口（记录每次导入内容，供断言）。"""
        data = dict(source)
        self.loaded.append(data)
        self.cookies = data

    def save_cookies(self, cookie_file: Any = None) -> Path:
        """落盘入口：返回路径，不真的写文件。"""
        return Path(cookie_file) if cookie_file else self.cookie_file

    def get_cookies(self) -> dict[str, str]:
        """与真实客户端同名同义。"""
        return dict(self.cookies)

    def has_valid_signing_cookie(self) -> bool:
        """签名 Cookie（d_c0）是否可用。"""
        return bool(self.cookies.get("d_c0"))

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            "FakeClient 没有属性 " + name + "：CLI/模块层新增了消费点，请把它补进 "
            "tests/test_cli.py 的 FakeClient（与 ZhihuClient 同名同义）")


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """替换 make_client：返回一个记录调用参数的假客户端。"""
    fake = FakeClient()

    def _make(rate_limit: Any = None, cookie_file: Any = None) -> FakeClient:
        fake.rate_limit = rate_limit
        fake.cookie_file = Path(cookie_file) if cookie_file else Path("/tmp/cookies.json")
        return fake

    monkeypatch.setattr(cli, "make_client", _make)
    return fake


@pytest.fixture()
def quiet_shelf(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """屏蔽下载成功后的书架登记（只测下载链路的用例用它）。"""
    calls: list[Any] = []
    monkeypatch.setattr(cli, "_record_to_shelf",
                       lambda result, fmt, meta=None: calls.append((result, fmt, meta)))
    return calls


def seed(shelf: Shelf, url: str = URL, title: str = "长夜难明", fmt: str = "md",
         chapters: int = 2, updated_at: str = "2025-01-02T10:00:00") -> ShelfBook:
    """往临时书架塞一条记录（id 用真实算法，保证 record_download 能合并）。"""
    book = ShelfBook(
        id=book_id_for(url), title=title, url=url, fmt=fmt,
        files=["/tmp/" + title + "." + fmt],
        chapter_urls=[f"{url}/section/{i}" for i in range(1, chapters + 1)],
        downloaded_at="2025-01-01T10:00:00", updated_at=updated_at)
    shelf.add_or_update(book)
    return book


def known_urls(url: str, count: int) -> list[str]:
    """生成 url/section/1 … url/section/count（与 seed() 记账的 URL 对齐）。"""
    return [url + "/section/" + str(i) for i in range(1, count + 1)]


# ----------------------------------------------------------------------
# 参数钳制
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 2.0), (2, 2.0), (2.0, 2.0), (0.5, 0.5), (5, 5.0),
     (0.1, 0.5), (0, 0.5), (-3, 0.5), (99, 5.0),
     (float("nan"), 2.0), (float("inf"), 2.0), ("abc", 2.0)],
)
def test_clamp_rate_limit(raw: Any, expected: float) -> None:
    assert cli.clamp_rate_limit(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 3), (3, 3), (1, 1), (8, 8), (0, 1), (-5, 1), (9, 8), (1000, 8), ("x", 3)],
)
def test_clamp_workers(raw: Any, expected: int) -> None:
    assert cli.clamp_workers(raw) == expected


def test_warn_prefix_is_centralised(capsys: pytest.CaptureFixture[str]) -> None:
    """R2 复核 A：⚠️ 前缀只由 warn() 补，正文原样跟在后面。"""
    cli.warn("裸告警一条")
    assert capsys.readouterr().err == "⚠️  裸告警一条" + cli.NL


def test_warn_prefix_is_unconditional(capsys: pytest.CaptureFixture[str]) -> None:
    """无条件补（而不是"已带就跳过"）：调用点自己写前缀会显示成两个 ⚠️。

    跳过式实现等于允许调用点继续自己写，新增点漏写就静默不一致；无条件补则把
    写错变成看得见的错误。
    """
    cli.warn("⚠️  有人手写了前缀")
    assert capsys.readouterr().err == "⚠️  ⚠️  有人手写了前缀" + cli.NL


def test_note_writes_bare_stderr_line(capsys: pytest.CaptureFixture[str]) -> None:
    """note() 是中性通道：不加图标，行首换行照原样保留。"""
    cli.note("中性回执")
    cli.note(cli.NL + "已取消（Ctrl+C）")
    err = capsys.readouterr().err
    assert err == "中性回执" + cli.NL + cli.NL + "已取消（Ctrl+C）" + cli.NL


def test_output_channels_do_not_bleed(capsys: pytest.CaptureFixture[str]) -> None:
    """三通道契约：echo→stdout、warn→⚠️、fail/usage_fail→❌ 且不再叠 ⚠️。"""
    cli.echo("结果行")
    cli.warn("告警行")
    assert cli.fail("业务失败行") == 1
    assert cli.usage_fail("用法错误行") == 2
    cap = capsys.readouterr()
    assert cap.out == "结果行" + cli.NL
    assert cap.err == ("⚠️  告警行" + cli.NL + "❌ 业务失败行" + cli.NL
                       + "❌ 用法错误行" + cli.NL)


def test_source_has_no_hand_written_warning_prefix() -> None:
    """静态守卫：cli.py 里不许再有调用点手写 ⚠️ 前缀（漂移的根源）。

    R2 复核 A 的契约是"前缀只由 warn() 补"。这条检查不看行为只看源码，所以哪天
    有人在新调用点里写回 warn("⚠️ ...")，这里会先红，而不是等到用户看到两个图标。
    """
    src = Path(cli.__file__).read_text(encoding="utf-8")
    quotes = (chr(34), chr(39))  # 两种引号，避免在本文件里写嵌套引号
    heads = ("warn(", "warn(f", "note(", "note(f")
    offenders: list[str] = []
    for raw in src.splitlines():
        line = raw.strip()
        for head in heads:
            index = line.find(head)
            if index < 0:
                continue
            tail = line[index + len(head):].lstrip("".join(quotes) + "f")
            if tail.startswith(chr(0x26A0)):  # ⚠
                offenders.append(line)
                break
    assert offenders == [], """前缀漂移回来了：交给 warn() 统一补"""


def test_resolve_limits_warns_on_clamp(capsys: pytest.CaptureFixture[str]) -> None:
    rate, workers = cli.resolve_limits(argparse.Namespace(rate_limit=99, workers=0))
    assert (rate, workers) == (5.0, 1)
    err = capsys.readouterr().err
    assert "rate-limit" in err and "workers" in err and "⚠️" in err


def test_resolve_limits_silent_when_in_range(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.resolve_limits(argparse.Namespace(rate_limit=1.5, workers=4)) == (1.5, 4)
    assert capsys.readouterr().err == ""


def test_resolve_limits_tolerates_missing_attrs() -> None:
    """shelf list 这类没有速度参数的命令也复用同一套钳制（缺属性 -> 默认值）。"""
    assert cli.resolve_limits(argparse.Namespace()) == (2.0, 3)


def test_download_clamps_before_calling_fetcher(
    client: Any, quiet_shelf: list, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """钳制必须真正落到 ZhihuClient / download_book，而不是只在 CLI 里显示。"""
    seen: dict[str, Any] = {}

    def fake_download(book_client: Any, url: str, **kwargs: Any) -> BookResult:
        seen.update(kwargs)
        seen["client_rate"] = book_client.rate_limit
        return make_result()

    monkeypatch.setattr(cli, "download_book", fake_download)
    assert cli.main(["download", "--url", URL, "--rate-limit", "50", "--workers", "99"]) == 0
    assert seen["workers"] == 8
    assert seen["client_rate"] == 5.0
    assert "超出允许区间" in capsys.readouterr().err


# ----------------------------------------------------------------------
# 分发与裸调用（双击即用）
# ----------------------------------------------------------------------


@pytest.fixture()
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, argparse.Namespace]]:
    """把五个子命令处理函数换成记录调用的假实现（只验证分发）。"""
    calls: list[tuple[str, argparse.Namespace]] = []

    def make(name: str) -> Callable[[argparse.Namespace], int]:
        def _handler(args: argparse.Namespace) -> int:
            calls.append((name, args))
            return 0

        return _handler

    for name in ("cmd_login", "cmd_download", "cmd_shelf", "cmd_doctor", "cmd_gui"):
        monkeypatch.setattr(cli, name, make(name))
    return calls


def test_bare_invocation_is_gui(recorder: list) -> None:
    """§2.15 双击即用：不带任何参数 = gui。"""
    assert cli.main([]) == 0
    assert [c[0] for c in recorder] == ["cmd_gui"]


def test_bare_invocation_reads_sys_argv(recorder: list, monkeypatch: pytest.MonkeyPatch) -> None:
    """main(None) 走 sys.argv（PyInstaller 双击时 argv 只有程序名）。"""
    monkeypatch.setattr(sys, "argv", ["zhihu-downloader.exe"])
    assert cli.main() == 0
    assert [c[0] for c in recorder] == ["cmd_gui"]


def test_explicit_subcommand_does_not_trigger_gui(recorder: list) -> None:
    assert cli.main(["doctor", "--no-network"]) == 0
    assert [c[0] for c in recorder] == ["cmd_doctor"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [(["login"], "cmd_login"),
     (["download", "--url", URL], "cmd_download"),
     (["shelf"], "cmd_shelf"),
     (["shelf", "list"], "cmd_shelf"),
     (["doctor"], "cmd_doctor"),
     (["gui"], "cmd_gui")],
)
def test_dispatch(argv: list, expected: str, recorder: list) -> None:
    assert cli.main(argv) == 0
    assert [c[0] for c in recorder] == [expected]


def test_gui_defaults_reach_handler(recorder: list) -> None:
    cli.main(["gui"])
    args = recorder[0][1]
    assert args.host == "127.0.0.1" and args.port == 3000
    assert args.no_browser is False and args.no_update_check is False


def test_download_flags_reach_handler(recorder: list) -> None:
    cli.main(["download", "-u", URL, "-f", "txt", "-o", "/tmp/x", "--no-resume",
              "--rate-limit", "1", "--workers", "2", "--batch-file", "b.txt"])
    args = recorder[0][1]
    assert (args.url, args.format, args.output_dir) == (URL, "txt", "/tmp/x")
    assert args.no_resume is True and args.rate_limit == 1.0 and args.workers == 2
    assert args.batch_file == "b.txt"


def test_bad_format_choice_exits_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["download", "--url", URL, "-f", "docx"])
    assert excinfo.value.code == 2


def test_unknown_command_exits_2() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["nope"])
    assert excinfo.value.code == 2


def test_version_flag_is_single_source(capsys: pytest.CaptureFixture[str]) -> None:
    """铁律 4：版本号唯一来源是 __version__，CLI 里不得写死。"""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert "zhihu-downloader " + __version__ in capsys.readouterr().out
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert '"' + __version__ + '"' not in source


def test_main_returns_int_when_handler_forgets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "cmd_gui", lambda args: None)
    assert cli.main([]) == 0


def test_main_wraps_unexpected_salt_error(monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    def boom(args: argparse.Namespace) -> int:
        raise ZhihuError("请求被知乎反爬拦截（HTTP 403）")

    monkeypatch.setattr(cli, "cmd_gui", boom)
    assert cli.main([]) == 1
    assert "403" in capsys.readouterr().err


def test_main_keyboard_interrupt_returns_130(monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    def boom(args: argparse.Namespace) -> int:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "cmd_gui", boom)
    assert cli.main([]) == 130
    assert "已取消" in capsys.readouterr().err


def test_cli_entrypoint_raises_systemexit_main() -> None:
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "raise SystemExit(main())" in source


def test_help_lists_every_subcommand_and_bare_call() -> None:
    text = cli.build_parser().format_help()
    for word in ("login", "download", "shelf", "doctor", "gui", "--version"):
        assert word in text
    assert "双击即用" in text


# ----------------------------------------------------------------------
# Windows UTF-8 兜底（移植 v4 cli.py:224-231）
# ----------------------------------------------------------------------


class RecordingStream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[Any] = []

    def reconfigure(self, **kwargs: Any) -> None:  # type: ignore[override]
        self.calls.append(kwargs)


class ExplodingStream(io.StringIO):
    def reconfigure(self, **kwargs: Any) -> None:  # type: ignore[override]
        raise OSError("流已损坏")


def test_ensure_utf8_streams_reconfigures(monkeypatch: pytest.MonkeyPatch) -> None:
    out, err = RecordingStream(), RecordingStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    cli.ensure_utf8_streams()
    for stream in (out, err):
        assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_ensure_utf8_streams_without_reconfigure(monkeypatch: pytest.MonkeyPatch) -> None:
    """capsys 的流没有 reconfigure：静默跳过而不是崩。"""
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    cli.ensure_utf8_streams()


def test_ensure_utf8_streams_survives_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdout", ExplodingStream())
    monkeypatch.setattr(sys, "stderr", ExplodingStream())
    cli.ensure_utf8_streams()


def test_ensure_utf8_streams_survives_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """pythonw / 冻结包下 stdout 可能整体是 None。"""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    cli.ensure_utf8_streams()


def test_main_survives_ascii_only_console(recorder: list, monkeypatch: pytest.MonkeyPatch) -> None:
    """整条链路在"只认 ASCII 的终端"里也不能因为打印中文而崩。"""
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="ascii"))
    assert cli.main(["gui"]) == 0


def test_progress_bar_survives_ascii_console() -> None:
    """方块字符在 cp1252 终端里最多变成问号，不许抛异常。"""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    printer = cli.ProgressPrinter(stream)  # type: ignore[arg-type]
    printer(ProgressEvent(kind="chapter", current=1, total=2, title="中文标题"))
    printer.finish()


# ----------------------------------------------------------------------
# 进度条渲染
# ----------------------------------------------------------------------


def test_render_progress_format() -> None:
    line = cli.render_progress(ProgressEvent(kind="chapter", current=12, total=47, title="初入江湖"))
    assert line.startswith("[") and "]" in line
    assert "12/47" in line and "(25%)" in line
    assert "第12章：初入江湖" in line
    assert "█" in line and "░" in line


def test_render_progress_zero_total() -> None:
    line = cli.render_progress(ProgressEvent(kind="chapter", current=0, total=0))
    assert "0/0" in line and "(0%)" in line


def test_render_progress_full_bar_and_note() -> None:
    done = cli.render_progress(ProgressEvent(kind="done", current=5, total=5))
    assert done.startswith("[" + "█" * cli.BAR_WIDTH + "]")
    noted = cli.render_progress(ProgressEvent(kind="retry", current=1, total=4), note="第 1 次重试")
    assert "⚠️ 第 1 次重试" in noted


def test_progress_printer_writes_cr_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="toc", current=0, total=47, title="测试书", message="共 47 章"))
    for i in range(1, 13):
        printer(ProgressEvent(kind="chapter", current=i, total=47, title=f"标题{i}"))
    err = capsys.readouterr().err
    assert cli.CR in err, "进度条必须用回车符原地刷新"
    assert "12/47" in err and "(25%)" in err and "第12章：标题12" in err
    assert "📖 测试书（共 47 章）" in err


def test_progress_printer_retry_inline_then_cleared(capsys: pytest.CaptureFixture[str]) -> None:
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="chapter", current=3, total=10, title="第三章"))
    printer(ProgressEvent(kind="retry", current=3, total=10, message="第 1 次重试（2s 后）：超时"))
    assert "⚠️ 第 1 次重试（2s 后）：超时" in capsys.readouterr().err
    printer(ProgressEvent(kind="chapter", current=4, total=10, title="第四章"))
    last = capsys.readouterr().err.splitlines()[-1]
    assert "第四章" in last and "⚠️" not in last, "新章节完成后行内提示应清除"


def test_progress_printer_finish_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="chapter", current=1, total=2, title="一章"))
    printer.finish()
    assert capsys.readouterr().err.endswith(cli.NL)
    printer.finish()
    assert capsys.readouterr().err == ""


def test_progress_printer_export_error_and_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="export", message="正在导出 epub"))
    printer(ProgressEvent(kind="error", message="第 3 章失败"))
    printer(ProgressEvent(kind="mystery", message="未知事件也要能显示"))
    err = capsys.readouterr().err
    assert "📦 正在导出 epub" in err and "❌ 第 3 章失败" in err and "未知事件" in err


def test_progress_printer_is_thread_safe() -> None:
    """fetcher 从工作线程回调：并发写入不得抛。"""
    printer = cli.ProgressPrinter(io.StringIO())

    def worker(i: int) -> None:
        for _ in range(30):
            printer(ProgressEvent(kind="chapter", current=i, total=100, title=f"T{i}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    printer.finish()


def test_progress_printer_swallows_broken_stream() -> None:
    class Broken(io.StringIO):
        def write(self, s: str) -> int:  # type: ignore[override]
            raise ValueError("I/O operation on closed file")

        def flush(self) -> None:
            raise ValueError("closed")

    printer = cli.ProgressPrinter(Broken())
    printer(ProgressEvent(kind="chapter", current=1, total=2, title="x"))
    printer.write_line("行")
    printer.finish()


def test_render_progress_chapter_label_switch() -> None:
    """toc / done 事件的 title 是书名，不得渲染成"第N章：书名"。"""
    event = ProgressEvent(kind="done", current=47, total=47, title="长夜难明")
    assert "第47章：长夜难明" in render_with(event, chapter_label=True)
    assert "第47章" not in render_with(event, chapter_label=False)
    assert "长夜难明" in render_with(event, chapter_label=False)


def render_with(event: ProgressEvent, **kwargs: Any) -> str:
    return cli.render_progress(event, **kwargs)


def test_progress_printer_toc_and_done_use_book_title(capsys: pytest.CaptureFixture[str]) -> None:
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="toc", current=0, total=3, title="长夜难明", message="共 3 章"))
    printer(ProgressEvent(kind="done", current=3, total=3, title="长夜难明", message="完成：1 个文件"))
    err = capsys.readouterr().err
    assert "第3章：长夜难明" not in err
    assert "3/3 (100%) 长夜难明" in err


def test_download_does_not_duplicate_error_from_progress_event(
    client: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """fetcher 已经用 error 事件播报过原因时，CLI 不再重复打一条 ❌。"""
    def fake_download(book_client: Any, url: str, **kwargs: Any) -> BookResult:
        kwargs["progress"](ProgressEvent(kind="error", current=1, total=3,
                                         message="第 2 章《暗巷》下载失败：HTTP 403"))
        raise ZhihuError("第 2 章《暗巷》下载失败：HTTP 403")

    monkeypatch.setattr(cli, "download_book", fake_download)
    assert cli.main(["download", "--url", URL]) == 1
    err = capsys.readouterr().err
    assert err.count("❌") == 1, "同一条失败只播报一次"
    assert "暗巷" in err


def test_download_prints_error_when_fetcher_stays_silent(
    client: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """没有 error 事件（例如目录阶段就炸）时，CLI 必须自己补一条错误行。"""
    monkeypatch.setattr(cli, "download_book",
                        lambda *a, **k: (_ for _ in ()).throw(ZhihuError("目录页 403")))
    assert cli.main(["download", "--url", URL]) == 1
    assert "目录页 403" in capsys.readouterr().err


# ----------------------------------------------------------------------
# E1 对接约定 2：retry 行内黄色提示（不重画整行）
# ----------------------------------------------------------------------


def test_retry_note_is_appended_without_redrawing_bar(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """E1：retry 只做行内提示 —— 不得重画进度条本体（否则中文标题来回跳动）。"""
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="chapter", current=3, total=10, title="第三章"))
    capsys.readouterr()
    printer(ProgressEvent(kind="retry", current=3, total=10, title="第三章",
                         message="第 1 次重试（2s 后）：读超时"))
    err = capsys.readouterr().err
    assert cli.CR not in err, "retry 不该把光标挪回行首重画整行"
    assert "3/10" not in err, "retry 不该再输出一次进度条本体"
    assert "⚠️ 第 1 次重试（2s 后）：读超时" in err


def test_second_retry_repaints_identical_bar_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """同一章连续重试：提示已存在才整行重画一次，条体文字逐字不变 -> 视觉不跳。"""
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="chapter", current=3, total=10, title="第三章"))
    printer(ProgressEvent(kind="retry", current=3, total=10, message="第 1 次重试"))
    first = capsys.readouterr().err
    printer(ProgressEvent(kind="retry", current=3, total=10, message="第 2 次重试"))
    second = capsys.readouterr().err
    assert "第 1 次重试" in first and cli.CR not in first
    assert cli.CR in second
    bar = cli.render_progress(
        ProgressEvent(kind="chapter", current=3, total=10, title="第三章"))
    assert first.count(bar) == 1 and second.count(bar) == 1, "条体文本必须逐字一致，才不会跳动"
    assert "第 2 次重试" in second


def test_retry_note_is_yellow_on_tty_and_plain_otherwise() -> None:
    """上色只在 TTY 生效：管道/重定向里必须是纯文本。"""
    colored = cli.ProgressPrinter(io.StringIO(), color=True)
    colored(ProgressEvent(kind="chapter", current=1, total=4, title="一章"))
    colored(ProgressEvent(kind="retry", current=1, total=4, message="连接被重置"))
    out = colored.stream.getvalue()  # type: ignore[attr-defined]
    assert chr(27) + "[33m" in out and chr(27) + "[0m" in out, "retry 提示应为黄色"

    plain = cli.ProgressPrinter(io.StringIO(), color=False)
    plain(ProgressEvent(kind="chapter", current=1, total=4, title="一章"))
    plain(ProgressEvent(kind="retry", current=1, total=4, message="连接被重置"))
    assert chr(27) not in plain.stream.getvalue()  # type: ignore[attr-defined]


def test_supports_color_follows_tty_and_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """color=None 时按流的 isatty + NO_COLOR + TERM=dumb 决定。"""
    tty = io.StringIO()
    tty.isatty = lambda: True  # type: ignore[method-assign]
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert cli.supports_color(tty) is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli.supports_color(tty) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TERM", "dumb")
    assert cli.supports_color(tty) is False
    assert cli.supports_color(io.StringIO()) is False
    assert cli.supports_color(None) is False  # capsys 的 stderr 不是 TTY


def test_note_cleared_and_long_title_residue_erased(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """下一章节完成清掉提示，并按显示宽度补空格擦除长中文标题的残留。"""
    printer = cli.ProgressPrinter()
    printer(ProgressEvent(kind="chapter", current=3, total=10, title="这一章的中文标题长得离谱"))
    printer(ProgressEvent(kind="retry", current=3, total=10, message="超时"))
    capsys.readouterr()
    printer(ProgressEvent(kind="chapter", current=4, total=10, title="短"))
    err = capsys.readouterr().err
    assert cli.CR in err, "重画前必须回到行首"
    assert "⚠️" not in err, "新章节完成要清掉上一帧的行内提示"
    frame = err.split(cli.CR)[-1]
    assert frame.rstrip(" ").endswith("短") and frame.endswith("  "), "短行后须补空格擦掉长标题残留"


# ----------------------------------------------------------------------
# E1 对接约定 1：按 errors.py 层级分类；CheckpointError 打印消息本体
# ----------------------------------------------------------------------


def test_explain_failure_checkpoint_keeps_message_body() -> None:
    """CheckpointError 自带 --no-resume 指引：原样透出，不叠加重复提示。"""
    exc = errors.CheckpointError(
        "断点文件已损坏：/x/.zhihu_state/a.json。请删除该文件或加 --no-resume 重新下载整本。")
    text = cli.explain_failure(exc)
    assert "断点文件已损坏" in text
    assert text.count("--no-resume") == 1, "模块层已给指引时不得再补一句"


def test_explain_failure_adds_next_step_when_missing() -> None:
    assert "login" in cli.explain_failure(errors.AuthError("登录态已失效"))
    assert ".zhihu_state" in cli.explain_failure(errors.CheckpointError("写入断点文件失败"))
    assert "专栏" in cli.explain_failure(errors.UnsupportedUrlError("该链接不支持"))
    assert "磁盘" in cli.explain_failure(errors.ExportError("导出失败"))
    assert "rate-limit" in cli.explain_failure(errors.ZhihuError("403 拦截"))
    assert "doctor" in cli.explain_failure(errors.ParseError("找不到目录"))


def test_explain_failure_collapses_multiline_and_labels_unknown() -> None:
    """多行消息压成一行；非 SaltError 给类型名 + 自检指引，绝不吐 traceback。"""
    multi = cli.explain_failure(errors.ZhihuError("第一行" + cli.NL + "第二行"))
    assert cli.NL not in multi and "第一行 第二行" in multi
    unknown = cli.explain_failure(RuntimeError("磁盘掉了"))
    assert "未预期错误" in unknown and "RuntimeError" in unknown
    assert "磁盘掉了" in unknown and "Traceback" not in unknown


def test_download_checkpoint_error_prints_hint_without_traceback(
    client: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """断点损坏：把含 --no-resume 的消息本体打到 stderr，且不暴露类名/traceback。"""
    def boom(*args: Any, **kwargs: Any) -> BookResult:
        raise errors.CheckpointError(
            "断点文件已损坏：/x/.zhihu_state/a.json（Expecting value）。"
            "请删除该文件或加 --no-resume 重新下载整本。")

    monkeypatch.setattr(cli, "download_book", boom)
    assert cli.main(["download", "--url", URL]) == 1
    err = capsys.readouterr().err
    assert "--no-resume" in err and ".zhihu_state" in err
    assert "Traceback" not in err and "CheckpointError" not in err


def test_download_unexpected_error_stays_one_line(
    client: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """兜底分支：未预期异常也只打一行中文，且批量模式继续下一本。"""
    def boom(*args: Any, **kwargs: Any) -> BookResult:
        raise IndexError("内部越界")

    monkeypatch.setattr(cli, "download_book", boom)
    assert cli.main(["download", "--url", URL]) == 1
    err = capsys.readouterr().err
    assert "未预期错误" in err and "IndexError" in err and "Traceback" not in err


def test_batch_mode_does_not_swallow_keyboard_interrupt(
    client: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C 必须穿透批量兜底网：返回 130，而不是被 except Exception 吃掉。"""
    batch = tmp_path / "urls.txt"
    batch.write_text(URL + chr(10) + URL + "/section/2" + chr(10), encoding="utf-8")

    def boom(*args: Any, **kwargs: Any) -> BookResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "download_book", boom)
    assert cli.main(["download", "--batch-file", str(batch)]) == 130
    assert "Ctrl+C" in capsys.readouterr().err


def test_batch_failure_classification_is_per_book(
    client: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """同一批混入不同类别的错误：各自给出中文下一步，且互不影响。"""
    batch = tmp_path / "urls.txt"
    first = URL
    second = URL + "/section/2"
    batch.write_text(first + chr(10) + second + chr(10), encoding="utf-8")

    def selective(c: Any, url: str, **kwargs: Any) -> BookResult:
        if url == first:
            raise errors.AuthError("Cookie 已过期")
        return make_result(url=url, title="第二本")

    monkeypatch.setattr(cli, "download_book", selective)
    assert cli.main(["download", "--batch-file", str(batch)]) == 1
    captured = capsys.readouterr()
    assert "login" in captured.err, "AuthError 要给出登录指引"
    assert "Traceback" not in captured.err
    assert "第二本" in captured.out, "失败一本不影响另一本完成"
    assert "成功 1 本" in captured.out and "失败 1 本" in captured.out


def test_main_top_level_unexpected_exception_is_one_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(args: argparse.Namespace) -> int:
        raise ValueError("没料到的异常")

    monkeypatch.setattr(cli, "cmd_gui", boom)
    assert cli.main([]) == 1
    err = capsys.readouterr().err
    assert "未预期错误" in err and "doctor" in err and "Traceback" not in err


def test_login_failure_hint_routes_through_explain_failure(
    client: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(c: Any) -> dict[str, Any]:
        raise errors.AuthError("登录态已失效")

    monkeypatch.setattr(cli.qr, "start", boom)
    assert cli.cmd_login(argparse.Namespace(browser=False, cookie_file=None)) == 1
    assert "login" in capsys.readouterr().err


# ----------------------------------------------------------------------
# E1 对接约定 3：rate_limit 语义 —— help 文案写"并行解析数"，不宣传提速
# ----------------------------------------------------------------------


@pytest.mark.parametrize("cmd", ["download", "shelf"])
def test_workers_help_wording_matches_rate_limit_semantics(
    cmd: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cli.main([cmd, "--help"])
    text = capsys.readouterr().out
    assert "并行解析数" in text
    assert "同时在飞的章节数" not in text and "并发下载" not in text
    assert "不成倍提速" in text or "不会成倍提速" in text
    assert "每秒请求数上限" in text and "吞吐上限" in text


def test_cli_never_advertises_speedup_multiplier() -> None:
    """源码里不许出现"N 倍提速"这类宣传：吞吐上限由 rate_limit 决定，workers 不是加速器。"""
    source = Path(cli.__file__).read_text(encoding="utf-8")
    for banned in ["倍提速!", "速度提升", "快 N 倍", "成倍加快", "并发下载数"]:
        assert banned not in source


def test_rate_limit_zero_is_clamped_up_not_treated_as_unlimited(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """引擎里 0/负数=不限速，但 CLI 出于反爬安全仍抬到下限并说明。"""
    assert cli.clamp_rate_limit(0) == cli.MIN_RATE_LIMIT
    assert cli.clamp_rate_limit(-3) == cli.MIN_RATE_LIMIT
    assert cli.clamp_rate_limit(None) == cli.DEFAULT_RATE_LIMIT
    rate, _workers = cli.resolve_limits(argparse.Namespace(rate_limit=0, workers=3))
    assert rate == cli.MIN_RATE_LIMIT
    err = capsys.readouterr().err
    assert "⚠️" in err and "--rate-limit" in err and "0.5" in err


def test_resolve_limits_explains_throughput_ceiling() -> None:
    rate, workers = cli.resolve_limits(argparse.Namespace(rate_limit=99, workers=99))
    assert (rate, workers) == (5.0, 8)


def test_download_progress_goes_to_stderr_result_to_stdout(
    client: Any, quiet_shelf: list, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_download(book_client: Any, url: str, **kwargs: Any) -> BookResult:
        emit = kwargs["progress"]
        emit(ProgressEvent(kind="chapter", current=1, total=3, title="第一章"))
        emit(ProgressEvent(kind="done", current=3, total=3))
        return make_result(files=[str(Path(kwargs["output_dir"]) / "书.md")])

    monkeypatch.setattr(cli, "download_book", fake_download)
    assert cli.main(["download", "--url", URL, "-o", str(Path.cwd())]) == 0
    captured = capsys.readouterr()
    assert "书.md" in captured.out
    assert cli.CR in captured.err
    assert "书.md" not in captured.err


# ----------------------------------------------------------------------
# download
# ----------------------------------------------------------------------


def test_download_requires_url_or_batch(client: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["download"]) == 2
    assert "batch-file" in capsys.readouterr().err


def test_download_passes_format_resume_workers(
    client: Any, quiet_shelf: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_download(book_client: Any, url: str, **kwargs: Any) -> BookResult:
        seen.update(kwargs)
        return make_result()

    monkeypatch.setattr(cli, "download_book", fake_download)
    assert cli.main(["download", "--url", URL, "-f", "epub", "--no-resume", "--workers", "5"]) == 0
    assert seen["fmt"] == "epub" and seen["resume"] is False and seen["workers"] == 5


def test_download_resume_by_default(client: Any, quiet_shelf: list,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "download_book", lambda c, u, **kw: seen.update(kw) or make_result())
    cli.main(["download", "--url", URL])
    assert seen["resume"] is True


def test_download_failure_returns_1(client: Any, monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    def boom(*args: Any, **kwargs: Any) -> BookResult:
        raise ZhihuError("请求被知乎反爬拦截（HTTP 403），请重新登录或更新 Cookie 后重试")

    monkeypatch.setattr(cli, "download_book", boom)
    assert cli.main(["download", "--url", URL]) == 1
    assert "403" in capsys.readouterr().err


def test_download_finishes_progress_line_on_failure(client: Any, monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    """失败时进度行也必须换行收尾，否则错误消息会叠在半行进度后面。"""
    def boom(*args: Any, **kwargs: Any) -> BookResult:
        raise ZhihuError("炸了")

    monkeypatch.setattr(cli, "download_book", boom)
    cli.main(["download", "--url", URL])
    assert capsys.readouterr().err.endswith(cli.NL)


def test_batch_file_parses_comments_blank_and_dedup(tmp_path: Path) -> None:
    path = tmp_path / "urls.txt"
    path.write_text(cli.NL.join(["# 我的书单", "", URL + " 备注只看第一个字段",
                                 URL2, URL, "   "]), encoding="utf-8")
    assert cli.read_batch_file(path) == [URL, URL2]


def test_batch_file_missing_raises_chinese(tmp_path: Path) -> None:
    with pytest.raises(SaltError) as excinfo:
        cli.read_batch_file(tmp_path / "nope.txt")
    assert "无法读取批量文件" in str(excinfo.value)


def test_batch_file_missing_returns_2(client: Any, tmp_path: Path,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["download", "--batch-file", str(tmp_path / "nope.txt")]) == 2
    assert "批量文件" in capsys.readouterr().err


def test_batch_single_failure_does_not_stop_rest(
    client: Any, shelf: Shelf, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """核心要求：逐本下载，单本失败不中断其余，最后汇总成功/失败与原因。"""
    batch = tmp_path / "urls.txt"
    batch.write_text(cli.NL.join([URL, URL2, URL3]), encoding="utf-8")
    done: list[str] = []

    def fake_download(book_client: Any, url: str, **kwargs: Any) -> BookResult:
        if url == URL2:
            raise ZhihuError("第 7 章下载失败：网络中断")
        done.append(url)
        return make_result(url=url, title="书" + url[-3:])

    monkeypatch.setattr(cli, "download_book", fake_download)
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta([u + "/section/1"]))

    assert cli.main(["download", "--batch-file", str(batch)]) == 1
    assert done == [URL, URL3], "失败的那本之后必须继续跑完剩下的"
    out = capsys.readouterr().out
    assert "成功 2 本 / 失败 1 本" in out
    assert URL2 in out and "网络中断" in out


def test_batch_all_success_returns_zero(
    client: Any, shelf: Shelf, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    batch = tmp_path / "urls.txt"
    batch.write_text(URL + cli.NL + URL2, encoding="utf-8")
    monkeypatch.setattr(cli, "download_book", lambda c, u, **kw: make_result(url=u))
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta([u + "/section/1"]))
    assert cli.main(["download", "--batch-file", str(batch)]) == 0
    assert "成功 2 本 / 失败 0 本" in capsys.readouterr().out


def test_batch_continues_past_non_salt_exception(
    client: Any, shelf: Shelf, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    """模块层之外的意外异常（如 OSError）也不许掀翻整批。"""
    batch = tmp_path / "urls.txt"
    batch.write_text(URL + cli.NL + URL2, encoding="utf-8")
    calls: list[str] = []

    def fake_download(book_client: Any, url: str, **kwargs: Any) -> BookResult:
        calls.append(url)
        if url == URL:
            raise OSError("磁盘掉了")
        return make_result(url=url)

    monkeypatch.setattr(cli, "download_book", fake_download)
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta([]))
    assert cli.main(["download", "--batch-file", str(batch)]) == 1
    assert calls == [URL, URL2]
    assert "磁盘掉了" in capsys.readouterr().err


def test_download_records_shelf_with_chapter_urls(
    client: Any, shelf: Shelf, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """下载成功后登记书架（否则 shelf update 无从追更）。"""
    urls = [URL + "/section/1", URL + "/section/2"]
    monkeypatch.setattr(cli, "download_book", lambda c, u, **kw: make_result())
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta(urls))

    assert cli.main(["download", "--url", URL]) == 0
    book = shelf.get(URL)
    assert book is not None and book.chapter_urls == urls
    assert "已登记书架" in capsys.readouterr().out


# ----------------------------------------------------------------------
# 真引擎接线检查（不替换 resolve_book / download_book）
# ----------------------------------------------------------------------


def test_download_wires_real_engine_with_single_toc_fetch(
    shelf: Shelf, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """标准记账通路必须在**真实 fetcher** 上跑通：目录页只抓一次、记账 URL 有序。"""
    chapters = [ChapterRef(url=URL + "/section/" + str(i), title="第" + str(i) + "章", index=i)
                for i in (1, 2)]
    calls: list[str] = []

    class StubClient:
        """只实现 fetch 的鸭子客户端（fetcher 允许没有 on_retry 能力）。"""

        cookie_file = Path("/tmp/cookies.json")
        rate_limit = None

        def fetch(self, url: str) -> str:
            calls.append(url)
            return "目录页HTML" if url == URL else "正文页HTML"

    fake = StubClient()
    monkeypatch.setattr(cli, "make_client", lambda **kw: fake)
    monkeypatch.setattr("zhihu_downloader.parse.parser.parse_toc",
                        lambda html, url: list(chapters))
    monkeypatch.setattr("zhihu_downloader.parse.parser.parse_page_title",
                        lambda html: "真引擎专栏")
    monkeypatch.setattr(
        "zhihu_downloader.parse.parser.parse_article",
        lambda html, url: Article(title="正文标题", url=url,
                                  blocks=[Block(kind="p", text="正文一段")]))
    monkeypatch.setattr(
        "zhihu_downloader.export.export_book",
        lambda title, articles, fmt, output_dir: [str(Path(output_dir) / (title + "." + fmt))])

    assert cli.main(["download", "--url", URL, "-o", str(tmp_path)]) == 0
    assert calls.count(URL) == 1, "目录页不得被重抓（meta= 复用）"
    assert sorted(c for c in calls if c != URL) == sorted(ch.url for ch in chapters)
    book = shelf.get(URL)
    assert book is not None
    assert book.chapter_urls == [ch.url for ch in chapters], "记账章节表来自 meta 且保持目录顺序"
    out = capsys.readouterr().out
    assert "真引擎专栏" in out and "共 2 章" in out


def test_single_article_download_costs_one_extra_page_fetch(
    shelf: Shelf, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """已知成本：单篇链接走标准通路时正文页会被抓 2 次（prefetched 不经 meta 传递）。

    钉住现状而不是掩盖它：engine._resolve_book 会把单篇正文页随 meta 一起返回，
    但公开的 resolve_book 只返回 meta，所以 download_book(meta=) 仍需重取该页。
    专栏不受影响（目录页与章节页本就不同 URL）。
    """
    section = URL + "/section/9"
    calls: list[str] = []

    class StubClient:
        cookie_file = Path("/tmp/cookies.json")

        def fetch(self, url: str) -> str:
            calls.append(url)
            return "正文页HTML"

    fake = StubClient()
    monkeypatch.setattr(cli, "make_client", lambda **kw: fake)
    monkeypatch.setattr("zhihu_downloader.parse.parser.parse_article",
                        lambda html, url: Article(title="一篇文章", url=url,
                                                  blocks=[Block(kind="p", text="正文")]))
    monkeypatch.setattr("zhihu_downloader.parse.parser.parse_page_title", lambda html: "一篇文章")
    monkeypatch.setattr(
        "zhihu_downloader.export.export_book",
        lambda title, articles, fmt, output_dir: [str(Path(output_dir) / (title + "." + fmt))])

    assert cli.main(["download", "--url", section, "-o", str(tmp_path)]) == 0
    assert calls.count(section) == 2, "单篇：预解析 1 次 + 下载 1 次（已知成本，见 docstring）"
    book = shelf.get(section)
    assert book is not None and book.chapter_urls == [section]


def test_download_preresolves_toc_exactly_once(
    client: Any, shelf: Shelf, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主审裁决的标准记账通路：目录页**恰好被抓 1 次**（不是 0 次，也不是 2 次）。"""
    calls: list[str] = []
    seen: dict[str, Any] = {}

    def fake_resolve(c: Any, u: str) -> Any:
        calls.append(u)
        return make_meta([u + "/section/1", u + "/section/2"])

    def fake_download(c: Any, u: str, **kwargs: Any) -> BookResult:
        seen.update(kwargs)
        return make_result(url=u)

    monkeypatch.setattr(cli, "resolve_book", fake_resolve)
    monkeypatch.setattr(cli, "download_book", fake_download)
    assert cli.main(["download", "--url", URL]) == 0
    assert calls == [URL], "目录页应被抓恰好一次"
    assert seen["meta"] is not None, "预解析结果必须经 meta= 交给 download_book"
    assert [ch.url for ch in seen["meta"].chapters] == [URL + "/section/1", URL + "/section/2"]
    book = shelf.get(URL)
    assert book is not None
    assert book.chapter_urls == [URL + "/section/1", URL + "/section/2"], "记账 URL 来自 meta 且有序"


def test_single_article_url_records_one_ordered_chapter(
    client: Any, shelf: Shelf, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E1：answer/zhuanlan/section 由 resolve_book 按单篇处理，CLI 不再特判。

    标准通路下所有链接都走同一条路：meta 里有几章就记几章（单篇即 1 章），
    因此单章下载同样能被 shelf update 精确 diff，不需要额外的目录请求。
    """
    section = URL + "/section/9"
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta([u]))
    monkeypatch.setattr(cli, "download_book", lambda c, u, **kw: make_result(url=u))
    assert cli.main(["download", "--url", section]) == 0
    book = shelf.get(section)
    assert book is not None and book.chapter_urls == [section]


def test_diff_new_chapters_matches_engine_semantics() -> None:
    """CLI 就地 diff 必须与 engine.check_new_chapters 同语义：保序、过滤空 URL。"""
    urls = [URL + "/section/1", URL + "/section/2", URL + "/section/3"]
    meta = make_meta(urls)
    assert [ch.url for ch in cli.diff_new_chapters(meta, urls)] == []
    assert [ch.url for ch in cli.diff_new_chapters(meta, [urls[1]])] == [urls[0], urls[2]]
    assert [ch.url for ch in cli.diff_new_chapters(meta, ["", None])] == urls  # type: ignore[list-item]


def test_download_survives_shelf_record_failure(
    client: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """书架写不进去（只读目录等）不得把已成功的下载翻成失败。"""
    def broken() -> Shelf:
        raise SaltError("shelf.json 不可写")

    monkeypatch.setattr(cli, "make_shelf", broken)
    monkeypatch.setattr(cli, "download_book", lambda c, u, **kw: make_result())
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta([]))

    assert cli.main(["download", "--url", URL]) == 0
    assert "书架登记失败" in capsys.readouterr().err


def test_download_tolerates_preresolve_failure(
    client: Any, shelf: Shelf, monkeypatch: pytest.MonkeyPatch
) -> None:
    """预解析失败不阻断下载：meta=None 交给 download_book 重解析并给出权威报错。"""
    seen: dict[str, Any] = {}

    def boom(c: Any, u: str) -> Any:
        raise ParseError("目录解析失败")

    monkeypatch.setattr(cli, "resolve_book", boom)
    monkeypatch.setattr(cli, "download_book",
                        lambda c, u, **kw: seen.update(kw) or make_result(url=u))
    assert cli.main(["download", "--url", URL]) == 0
    assert seen["meta"] is None
    assert shelf.get(URL) is not None, "预解析失败也要照常登记书架"


# ----------------------------------------------------------------------
# login
# ----------------------------------------------------------------------


class FakeQr:
    """auth.qr 的桩：按脚本依次给出 poll 结果。"""

    def __init__(self, statuses: list[dict[str, Any]]) -> None:
        self.statuses = statuses
        self.start_calls = 0
        self.image_calls = 0
        self.poll_calls = 0

    def start(self, book_client: Any) -> dict[str, Any]:
        self.start_calls += 1
        return {"token": "TOK", "image_url": "https://x/TOK"}

    def image(self, book_client: Any, token: str) -> bytes:
        self.image_calls += 1
        assert token == "TOK"
        return b"jpeg-bytes"

    def poll(self, book_client: Any, token: str) -> dict[str, Any]:
        index = min(self.poll_calls, len(self.statuses) - 1)
        self.poll_calls += 1
        return self.statuses[index]


def test_login_qr_confirmed(client: Any, monkeypatch: pytest.MonkeyPatch,
                            capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeQr([
        {"status": "waiting", "user_id": None, "error": None, "saved_to": None},
        {"status": "scanned", "user_id": None, "error": None, "saved_to": None},
        {"status": "confirmed", "user_id": "u1", "error": None, "saved_to": "/tmp/cookies.json"},
    ])
    monkeypatch.setattr(cli.qr, "start", fake.start)
    monkeypatch.setattr(cli.qr, "image", fake.image)
    monkeypatch.setattr(cli.qr, "poll", fake.poll)
    slept: list[float] = []

    code = cli._login_with_qrcode(client, sleeper=slept.append, interval=1, timeout=99,
                                  clock=iter([0, 1, 2, 3, 4, 5]).__next__)

    assert code == 0
    out = capsys.readouterr().out
    assert "登录成功" in out and "u1" in out
    assert ".jpg" in out, "必须打印二维码临时文件路径"
    assert "已扫码" in out
    assert slept == [1, 1], "waiting / scanned 各等一轮"
    assert fake.poll_calls == 3


def test_login_qr_confirmed_without_saved_to(client: Any, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeQr([])
    monkeypatch.setattr(cli.qr, "start", fake.start)
    monkeypatch.setattr(cli.qr, "image", fake.image)
    monkeypatch.setattr(cli.qr, "poll", lambda c, t: {"status": "confirmed", "user_id": "u2",
                                                      "error": None, "saved_to": None})
    assert cli._login_with_qrcode(client, sleeper=lambda s: None,
                                  clock=iter([0, 1]).__next__) == 0
    assert "cookies.json" in capsys.readouterr().out


def test_login_qr_expired(client: Any, monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeQr([{"status": "expired", "user_id": None, "error": None, "saved_to": None}])
    monkeypatch.setattr(cli.qr, "start", fake.start)
    monkeypatch.setattr(cli.qr, "image", fake.image)
    monkeypatch.setattr(cli.qr, "poll", fake.poll)
    assert cli._login_with_qrcode(client, sleeper=lambda s: None, timeout=99,
                                  clock=iter([0, 1, 2]).__next__) == 1
    assert "过期" in capsys.readouterr().err


def test_login_qr_error_status(client: Any, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeQr([{"status": "error", "user_id": None, "error": "二维码校验失败", "saved_to": None}])
    monkeypatch.setattr(cli.qr, "start", fake.start)
    monkeypatch.setattr(cli.qr, "image", fake.image)
    monkeypatch.setattr(cli.qr, "poll", fake.poll)
    assert cli._login_with_qrcode(client, sleeper=lambda s: None, timeout=99,
                                  clock=iter([0, 1, 2]).__next__) == 1
    assert "二维码校验失败" in capsys.readouterr().err


def test_login_qr_timeout(client: Any, monkeypatch: pytest.MonkeyPatch,
                          capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeQr([{"status": "waiting", "user_id": None, "error": None, "saved_to": None}])
    monkeypatch.setattr(cli.qr, "start", fake.start)
    monkeypatch.setattr(cli.qr, "image", fake.image)
    monkeypatch.setattr(cli.qr, "poll", fake.poll)
    assert cli._login_with_qrcode(client, sleeper=lambda s: None, timeout=10,
                                  clock=iter([0, 5, 50]).__next__) == 1
    assert "超时" in capsys.readouterr().err


def test_login_qr_start_failure_is_clean(client: Any, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    def boom(c: Any) -> dict[str, Any]:
        raise AuthError("获取登录二维码失败：网络不通 → 请检查网络后重新运行 zhihu-downloader login")

    monkeypatch.setattr(cli.qr, "start", boom)
    assert cli.cmd_login(argparse.Namespace(browser=False, cookie_file=None)) == 1
    assert "获取登录二维码失败" in capsys.readouterr().err


def test_login_dispatches_to_qr_by_default(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(cli, "_login_with_qrcode", lambda c: seen.append("qr") or 0)
    monkeypatch.setattr(cli, "_login_with_browser", lambda c: seen.append("br") or 0)
    assert cli.cmd_login(argparse.Namespace(browser=False, cookie_file=None)) == 0
    assert seen == ["qr"]


def test_login_browser_success(client: Any, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    captured: dict[str, Any] = {}

    def fake_fetch(browsers: Any = None, *, save_to: Any = None) -> dict[str, str]:
        captured["save_to"] = save_to
        return {"z_c0": "a", "zse_ck": "b", "d_c0": "c"}

    monkeypatch.setattr(cli.browser, "fetch_zhihu_cookies", fake_fetch)
    assert cli.cmd_login(argparse.Namespace(browser=True, cookie_file=None)) == 0
    assert captured["save_to"] == client.cookie_file
    assert client.loaded == [{"z_c0": "a", "zse_ck": "b", "d_c0": "c"}]
    assert "已导入 3 个 Cookie" in capsys.readouterr().out


def test_login_browser_missing_extra_hint(client: Any, monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    def boom(browsers: Any = None, *, save_to: Any = None) -> dict[str, str]:
        raise AuthError("未安装 browser-cookie3，请 pip install 'zhihu-salt-novel-downloader[browser]'")

    monkeypatch.setattr(cli.browser, "fetch_zhihu_cookies", boom)
    assert cli.cmd_login(argparse.Namespace(browser=True, cookie_file=None)) == 1
    err = capsys.readouterr().err
    assert "browser-cookie3" in err or "[browser]" in err


def test_login_browser_warns_when_d_c0_missing(client: Any, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli.browser, "fetch_zhihu_cookies",
                        lambda browsers=None, save_to=None: {"z_c0": "a"})
    assert cli.cmd_login(argparse.Namespace(browser=True, cookie_file=None)) == 0
    err = capsys.readouterr().err
    assert "d_c0" in err and "⚠️" in err


def test_login_browser_third_party_exception_becomes_human(
    client: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(browsers: Any = None, *, save_to: Any = None) -> dict[str, str]:
        raise RuntimeError("浏览器数据库被锁")

    monkeypatch.setattr(cli.browser, "fetch_zhihu_cookies", boom)
    assert cli.cmd_login(argparse.Namespace(browser=True, cookie_file=None)) == 1
    assert "扫码登录" in capsys.readouterr().err


def test_cookie_default_path_comes_from_auth_layer() -> None:
    """CLI 不得自己拼 Cookie 路径（单一来源在 auth.cookies）。"""
    assert cookie_store.DEFAULT_COOKIE_FILE.name == "cookies.json"


# ----------------------------------------------------------------------
# shelf
# ----------------------------------------------------------------------


def test_shelf_list_empty(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["shelf", "list"]) == 0
    assert "书架为空" in capsys.readouterr().out


def test_shelf_list_table(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    seed(shelf)
    assert cli.main(["shelf"]) == 0  # 缺省动作 = list
    out = capsys.readouterr().out
    for column in ("书名", "章节数", "更新时间", "文件数"):
        assert column in out
    assert "长夜难明" in out and book_id_for(URL) in out
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", out), "更新时间列必须是 ISO 时间"


def test_render_shelf_table_alignment() -> None:
    books = [
        ShelfBook(id="i1", title="中文书名很长很长", url=URL, fmt="md", files=["a", "b"],
                  chapter_urls=["1", "2", "3"], updated_at="2025-01-01T00:00:00"),
        ShelfBook(id="i2", title="Short", url=URL2, fmt="txt", files=[], chapter_urls=[],
                  updated_at="2025-01-02T00:00:00"),
    ]
    lines = cli.render_shelf_table(books).splitlines()
    assert len(lines) == 4, "表头 + 分隔线 + 两行数据"
    assert cli.display_width("中文") == 4
    assert lines[2].startswith("中文书名很长很长")
    assert lines[3].startswith("Short ")


def test_shelf_remove(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    book = seed(shelf)
    assert cli.main(["shelf", "remove", book.id]) == 0
    assert shelf.list() == []
    assert "已从书架移除" in capsys.readouterr().out


def test_shelf_remove_keeps_files(shelf: Shelf, tmp_path: Path) -> None:
    keep = tmp_path / "书.md"
    keep.write_text("正文", encoding="utf-8")
    book = seed(shelf)
    book.files = [str(keep)]
    shelf.add_or_update(book)
    cli.main(["shelf", "remove", book.id])
    assert keep.exists(), "移除书架条目不得删用户已导出的文件"


def test_shelf_remove_prunes_checkpoint(shelf: Shelf, tmp_path: Path) -> None:
    """主审接线（镜像 server DELETE）：remove 成功即显式 prune 该书断点缓存。"""
    from zhihu_downloader.engine.checkpoint import CheckpointStore

    store = CheckpointStore(tmp_path / ".zhihu_state", book_key=URL)
    store.save({"title": "长夜难明", "done": {URL + "/section/1": {"size": 1}}})
    assert store.state_path.exists()
    book = seed(shelf)
    assert cli.main(["shelf", "remove", book.id, "-o", str(tmp_path)]) == 0
    assert not store.state_path.exists(), "书架移除应 prune 断点状态（keep-on-success 的对偶）"


def test_shelf_remove_survives_oserror_from_prune(
    shelf: Shelf, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """prune 里抛 OSError 也不许反悔删除：只兜 SaltError 会在这里甩 traceback。

    prune 的实现是 unlink：只读挂载、EACCES、Windows 文件占用抛的都是 OSError，
    不是 SaltError。上一版只兜 SaltError，等于把"失败仅 ⚠️"的契约漏给了 traceback。
    """
    from zhihu_downloader.engine import checkpoint as ck

    def boom(self: object, book_key: str | None = None) -> None:
        raise OSError(30, "只读文件系统")

    monkeypatch.setattr(ck.CheckpointStore, "prune", boom)
    book = seed(shelf)
    assert cli.main(["shelf", "remove", book.id, "-o", str(tmp_path)]) == 0
    assert shelf.list() == [], "断点没清掉不代表书架条目可以留着"
    err = capsys.readouterr().err
    assert "prune 失败" in err and "手工删" in err and err.startswith("⚠️")


def test_shelf_remove_prunes_exactly_where_download_writes(
    shelf: Shelf, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """prune 的目标目录必须等于 CLI 下载写断点的那个，否则接线只是看着对。

    CLI 下载走 output_dir/.zhihu_state，server 走自己的任务目录，两者不同名；
    这条钉住 CLI 侧的推导与 fetcher.DEFAULT_STATE_SUBDIR 同源（不各自拼字面量）。
    """
    from zhihu_downloader.engine import checkpoint as ck
    from zhihu_downloader.engine import fetcher

    seen: dict[str, object] = {}

    class Spy:
        def __init__(self, state_dir: object, book_key: str) -> None:
            seen["target"] = (str(state_dir), book_key)

        def prune(self, book_key: str | None = None) -> None:
            seen["pruned"] = True

    monkeypatch.setattr(ck, "CheckpointStore", Spy)
    book = seed(shelf)
    assert cli.main(["shelf", "remove", book.id, "-o", str(tmp_path)]) == 0
    assert seen.get("pruned") is True
    assert seen["target"] == (str(tmp_path / fetcher.DEFAULT_STATE_SUBDIR), URL), (
        "目标目录应与 CLI 下载断点目录逐字一致，book_key 用书的 URL")


def test_shelf_remove_skips_prune_when_removal_fails(
    shelf: Shelf, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """id 不存在 → 删除失败，此时绝不能顺手 prune（会误删别处的断点）。"""
    from zhihu_downloader.engine import checkpoint as ck

    calls: list[str] = []
    monkeypatch.setattr(ck.CheckpointStore, "prune",
                        lambda self, book_key=None: calls.append("prune"))
    seed(shelf)
    assert cli.main(["shelf", "remove", "no-such-id", "-o", str(tmp_path)]) == 1
    assert calls == [], "移除没成功就不该清断点"


def test_shelf_remove_without_url_silently_skips_prune(
    shelf: Shelf, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """取不到条目 url（老数据/并发删除）：安静跳过 prune，不算失败也不吓用户。"""
    from zhihu_downloader.engine import checkpoint as ck

    calls: list[str] = []
    monkeypatch.setattr(ck.CheckpointStore, "prune",
                        lambda self, book_key=None: calls.append("prune"))
    book = seed(shelf)
    monkeypatch.setattr(type(shelf), "get", lambda self, book_id: None)
    assert cli.main(["shelf", "remove", book.id, "-o", str(tmp_path)]) == 0
    assert calls == []
    assert "prune 失败" not in capsys.readouterr().err


def test_shelf_remove_survives_prune_failure(shelf: Shelf, tmp_path: Path,
                                             monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    """prune 失败只 warn 不反悔：磁盘垃圾不阻塞书架操作（与 server 同语义）。"""
    from zhihu_downloader.engine.checkpoint import CheckpointStore
    from zhihu_downloader.errors import CheckpointError

    def boom(self: CheckpointStore, book_key: str | None = None) -> None:
        raise CheckpointError("模拟 prune 失败")

    monkeypatch.setattr(CheckpointStore, "prune", boom)
    book = seed(shelf)
    assert cli.main(["shelf", "remove", book.id, "-o", str(tmp_path)]) == 0
    assert shelf.list() == [], "条目必须真的移除"
    err = capsys.readouterr().err
    assert "prune 失败" in err and "手工删" in err


def test_shelf_remove_unknown_id(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["shelf", "remove", "nope"]) == 1
    assert "shelf list" in capsys.readouterr().err


def test_shelf_remove_without_id(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["shelf", "remove"]) == 2
    assert "remove 需要指定书架 id" in capsys.readouterr().err


def test_shelf_update_requires_target(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["shelf", "update"]) == 2
    assert "--all" in capsys.readouterr().err


def test_shelf_update_unknown_id(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["shelf", "update", "--id", "ghost"]) == 1
    assert "ghost" in capsys.readouterr().err


def test_shelf_update_all_on_empty_shelf(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["shelf", "update", "--all"]) == 0
    assert "书架为空" in capsys.readouterr().out


def test_shelf_update_no_new_chapters(shelf: Shelf, client: Any,
                                      monkeypatch: pytest.MonkeyPatch,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    seed(shelf)
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta(known_urls(u, 2)))
    monkeypatch.setattr(cli, "download_book", lambda *a, **k: pytest.fail("无新章节不应下载"))
    assert cli.main(["shelf", "update", "--all"]) == 0
    assert "已是最新" in capsys.readouterr().out


def test_shelf_update_downloads_and_merges(shelf: Shelf, client: Any,
                                           monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    """追更链路：resolve_book -> download_book(meta=) -> shelf.record_download。"""
    book = seed(shelf)
    called: dict[str, Any] = {}
    resolves: list[str] = []

    def fake_resolve(book_client: Any, url: str) -> Any:
        resolves.append(url)
        return make_meta(known_urls(url, 3))  # 已知 1~2 章，第 3 章是新增

    def fake_download(book_client: Any, url: str, **kwargs: Any) -> BookResult:
        called.update(url=url, fmt=kwargs["fmt"], progress=kwargs["progress"],
                      resume=kwargs["resume"], meta=kwargs.get("meta"))
        return make_result(url=url, files=["/tmp/长夜难明.md"])

    monkeypatch.setattr(cli, "resolve_book", fake_resolve)
    monkeypatch.setattr(cli, "download_book", fake_download)

    assert cli.main(["shelf", "update", "--id", book.id]) == 0
    assert called["url"] == URL and called["fmt"] == "md" and called["resume"] is True
    assert isinstance(called["progress"], cli.ProgressPrinter)
    assert resolves == [URL], "追更全程目录页只抓一次（diff 与下载共用同一份 meta）"
    assert called["meta"] is not None, "download_book 必须经 meta= 复用目录"
    merged = shelf.get(book.id)
    assert merged is not None
    assert merged.chapter_urls == [URL + "/section/1", URL + "/section/2", URL + "/section/3"]
    out = capsys.readouterr().out
    assert "发现 1 章更新" in out and "追更汇总：更新 1 本" in out


def test_shelf_update_honours_format_override(shelf: Shelf, client: Any,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    book = seed(shelf, fmt="md")
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta(known_urls(u, 3)))
    monkeypatch.setattr(cli, "download_book",
                        lambda c, u, **kw: seen.update(fmt=kw["fmt"]) or make_result(url=u))
    cli.main(["shelf", "update", "--all", "-f", "epub"])
    assert seen["fmt"] == "epub"
    assert shelf.get(book.id).fmt == "epub"


def test_shelf_update_single_failure_continues(shelf: Shelf, client: Any,
                                               monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    seed(shelf)
    second = seed(shelf, url=URL2, title="第二本", fmt="txt", chapters=1,
                  updated_at="2025-01-03T00:00:00")

    def fake_resolve(c: Any, url: str) -> Any:
        if url == URL:
            raise ZhihuError("目录页 403")
        return make_meta([url + "/section/1", url + "/section/2"])

    monkeypatch.setattr(cli, "resolve_book", fake_resolve)
    monkeypatch.setattr(cli, "download_book", lambda c, u, **kw: make_result(url=u, title="第二本"))

    assert cli.main(["shelf", "update", "--all"]) == 1
    out = capsys.readouterr().out
    assert "更新 1 本" in out and "失败 1 本" in out and "403" in out
    assert shelf.get(second.id).chapter_urls == [URL2 + "/section/1", URL2 + "/section/2"]


def test_shelf_update_survives_record_failure(shelf: Shelf, client: Any,
                                              monkeypatch: pytest.MonkeyPatch,
                                              capsys: pytest.CaptureFixture[str]) -> None:
    book = seed(shelf)
    monkeypatch.setattr(cli, "resolve_book", lambda c, u: make_meta(known_urls(u, 3)))
    monkeypatch.setattr(cli, "download_book", lambda c, u, **kw: make_result(url=u))
    monkeypatch.setattr(shelf, "record_download",
                        lambda *a, **k: (_ for _ in ()).throw(SaltError("写不进去")))
    assert cli.main(["shelf", "update", "--id", book.id]) == 0
    assert "书架条目更新失败" in capsys.readouterr().err


def test_shelf_unknown_action(shelf: Shelf, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.cmd_shelf(argparse.Namespace(action="teleport")) == 1
    assert "未知的 shelf 操作" in capsys.readouterr().err


def test_shelf_book_roundtrip_for_table(tmp_path: Path) -> None:
    """表格数据来自 shelf.json 真实读写（防字段名漂移）。"""
    store = Shelf(tmp_path / "shelf.json")
    store.record_download(make_result(), "md", chapter_urls=["a", "b"])
    table = cli.render_shelf_table(store.list())
    assert "测试书" in table and "2" in table


# ----------------------------------------------------------------------
# doctor
# ----------------------------------------------------------------------


def test_doctor_exit_zero_when_only_warnings(monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    results = [("info", "版本", "zhihu-downloader 5.0.0"), ("warn", "Cookie 存在", "不存在")]
    monkeypatch.setattr(cli.doctor, "run_checks", lambda **kw: results)
    assert cli.main(["doctor", "--no-network", "--no-update-check"]) == 0
    out = capsys.readouterr().out
    assert "ℹ️ [版本]" in out and "⚠️ [Cookie 存在]" in out
    assert "无错误" in out


def test_doctor_exit_one_when_errors(monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str]) -> None:
    results = [("error", "签名自检", "x-zse-96 前缀异常"), ("warn", "z_c0", "缺少")]
    monkeypatch.setattr(cli.doctor, "run_checks", lambda **kw: results)
    assert cli.main(["doctor", "--no-network", "--no-update-check"]) == 1
    captured = capsys.readouterr()
    assert "❌ [签名自检]" in captured.out
    assert "1 个错误" in captured.err and "exit 1" in captured.err


def test_doctor_passes_flags_to_run_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_checks(**kwargs: Any) -> list[Any]:
        seen.update(kwargs)
        return [("ok", "版本", "v")]

    monkeypatch.setattr(cli.doctor, "run_checks", fake_checks)
    assert cli.main(["doctor", "--cookie-file", "/tmp/c.json", "--no-network",
                     "--no-update-check"]) == 0
    assert seen["cookie_file"] == "/tmp/c.json" and seen["network"] is False


def test_doctor_network_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli.doctor, "run_checks", lambda **kw: seen.update(kw) or [("ok", "版本", "v")])
    cli.main(["doctor", "--no-update-check"])
    assert seen["network"] is True


def test_doctor_shows_update_line_only_when_newer(monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli.doctor, "run_checks", lambda **kw: [("ok", "版本", "v")])
    monkeypatch.setattr(cli, "check_tool_update",
                        lambda current: {"latest": "v9.9.9", "url": "u", "has_update": True})
    assert cli.main(["doctor", "--no-network"]) == 0
    assert "v9.9.9" in capsys.readouterr().out


def test_doctor_silent_when_up_to_date(monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli.doctor, "run_checks", lambda **kw: [("ok", "版本", "v")])
    monkeypatch.setattr(cli, "check_tool_update",
                        lambda current: {"latest": "v5.0.0", "url": "u", "has_update": False})
    cli.main(["doctor", "--no-network"])
    assert "⬆" not in capsys.readouterr().out


def test_doctor_no_update_check_never_calls_updater(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.doctor, "run_checks", lambda **kw: [("ok", "版本", "v")])

    def never(current: str) -> None:
        pytest.fail("--no-update-check 时不得触网")

    monkeypatch.setattr(cli, "check_tool_update", never)
    assert cli.main(["doctor", "--no-network", "--no-update-check"]) == 0


def test_doctor_update_check_failure_is_silent(monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    """升级检查炸了也不能影响诊断结论（§2.16 静默）。"""
    monkeypatch.setattr(cli.doctor, "run_checks", lambda **kw: [("ok", "版本", "v")])

    def boom(current: str) -> dict:
        raise RuntimeError("不该抛出来的东西")

    monkeypatch.setattr(cli, "check_tool_update", boom)
    assert cli.main(["doctor", "--no-network"]) == 0
    assert "不该抛出来" not in capsys.readouterr().err


def test_doctor_real_checks_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    """真跑一遍 auth.doctor（network=False）：无 Cookie 属首次使用，只告警不报错。"""
    monkeypatch.setattr(cli, "check_tool_update", lambda current: None)
    missing = tmp_path / "cookies.json"
    assert cli.main(["doctor", "--cookie-file", str(missing), "--no-network",
                     "--no-update-check"]) == 0
    assert "login" in capsys.readouterr().out


# ----------------------------------------------------------------------
# gui
# ----------------------------------------------------------------------


@pytest.fixture()
def fake_server(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """注入假的 zhihu_downloader.app.server（不依赖 I1 的真实文件）。"""
    holder: dict[str, Any] = {"calls": []}
    module = types.ModuleType("zhihu_downloader.app.server")

    def create_app(*args: Any, **kwargs: Any) -> str:
        holder["calls"].append((args, kwargs))
        return "FAKE_APP"

    module.create_app = create_app  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "zhihu_downloader.app.server", module)
    return holder


@pytest.fixture()
def served(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """拦下 uvicorn：记录 (app, host, port)，不真的起服务。"""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(cli, "serve_app",
                        lambda app, host, port: calls.append({"app": app, "host": host, "port": port}))
    return calls


@pytest.fixture()
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """同步拦下"打开浏览器"：直接替换 open_browser_later，杜绝守护线程带来的竞态。"""
    urls: list[str] = []
    monkeypatch.setattr(cli, "open_browser_later",
                        lambda url, **kw: urls.append(url))
    return urls


@pytest.fixture()
def opened_live(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """走真实的 open_browser_later（守护线程 + 就绪探测），验证线程确实会落地。"""
    urls: list[str] = []
    # serve_app 在别处被替换掉了，真没有服务在听；直接把探测钉成"已就绪"。
    monkeypatch.setattr(cli, "http_status", lambda url, timeout=None: 200)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url, **kw: (urls.append(url), True)[1])
    return urls


def wait_opened(urls: list[str], count: int = 1, timeout: float = 5.0) -> bool:
    """等后台开浏览器线程落地（它是守护线程，不能假设 main 返回时已执行）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(urls) >= count:
            return True
        time.sleep(0.01)
    return len(urls) >= count


def test_gui_imports_create_app_lazily(fake_server: dict, served: list, opened: list) -> None:
    """create_app 只在 cmd_gui 里 import；模块级不得拉起 Web 层。"""
    assert "create_app" not in dir(cli)
    assert cli.main(["gui", "--no-update-check"]) == 0
    assert len(fake_server["calls"]) == 1
    assert served[0]["app"] == "FAKE_APP"


def test_importing_cli_does_not_import_web_layer() -> None:
    """子进程验证：import zhihu_downloader.cli 之后 sys.modules 里没有 app.server。"""
    src = Path(cli.__file__).parents[1]
    code = ("import sys, zhihu_downloader.cli as c;"
            "print('zhihu_downloader.app.server' in sys.modules)")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(src.parent), env={"PYTHONPATH": str(src), "HOME": "/tmp"},
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def test_gui_opens_actual_port_in_browser(fake_server: dict, served: list, opened: list,
                                          monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    """端口被占 -> 自动 +1，浏览器打开的必须是实际端口。"""
    occupied = {3000, 3001}
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: port not in occupied)
    assert cli.main(["gui", "--no-update-check"]) == 0
    assert served[0]["port"] == 3002
    assert opened == ["http://127.0.0.1:3002"], "浏览器必须打开实际端口"
    assert "自动改用 3002" in capsys.readouterr().err


def test_gui_browser_thread_actually_opens_url(
    fake_server: dict, served: list, opened_live: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不替换 open_browser_later 的那条路径：守护线程确实会去开实际 URL。"""
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    assert cli.main(["gui", "--no-update-check"]) == 0
    assert wait_opened(opened_live, timeout=5.0), "延迟线程应把浏览器打开调用落地"
    assert opened_live == ["http://127.0.0.1:3000"]


def test_gui_port_retry_limit(fake_server: dict, served: list, opened: list,
                              monkeypatch: pytest.MonkeyPatch,
                              capsys: pytest.CaptureFixture[str]) -> None:
    """默认端口 + 3 次 +1 全被占 -> 中文报错 + 退出码 1，且不起服务。"""
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: False)
    assert cli.main(["gui", "--no-update-check"]) == 1
    err = capsys.readouterr().err
    assert "都被占用" in err and "--port" in err
    assert served == []


def test_gui_free_port_uses_default(fake_server: dict, served: list, opened: list,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    assert cli.main(["gui", "--no-update-check"]) == 0
    assert served[0]["port"] == 3000
    assert opened == ["http://127.0.0.1:3000"]


def test_gui_custom_port(fake_server: dict, served: list, opened: list,
                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    assert cli.main(["gui", "--port", "8123", "--no-update-check"]) == 0
    assert served[0]["port"] == 8123
    assert opened == ["http://127.0.0.1:8123"]


def test_gui_no_browser_skips_open(fake_server: dict, served: list, opened: list,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    assert cli.main(["gui", "--no-browser", "--no-update-check"]) == 0
    assert served and opened == []


def test_gui_warns_on_public_host(fake_server: dict, served: list, opened: list,
                                  monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    assert cli.main(["gui", "--host", "0.0.0.0", "--no-browser", "--no-update-check"]) == 0
    err = capsys.readouterr().err
    assert "安全告警" in err and "0.0.0.0" in err
    assert served[0]["host"] == "0.0.0.0"


def test_public_host_warning_covers_every_consequence(
    fake_server: dict, served: list, opened: list, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """R2 复核 B：四类后果写全，且措辞必须跟 S1 已落地校验的**真实覆盖面**一致。

    /api/cookies 只回布尔（不吐 Cookie 值），旧文案的"读取你的 Cookie"是失实描述；
    S1 的 server.check_origin 落地后，"无鉴权"也失实了。但它只挂 POST/DELETE、
    Origin/Referer 双缺即放行、GET 完全不校验 —— 所以"仅校验请求来自本机"同样是
    过度承诺。两头都不许写，必须写明可被不带来源头的脚本绕过（改校验前先改这里）。
    """
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    assert cli.main(["gui", "--host", "0.0.0.0", "--no-browser",
                     "--no-update-check"]) == 0
    err = capsys.readouterr().err
    for token in ("发起下载", "配额", "已导出的全部文件", "覆盖或清除你的登录 Cookie",
                  "内网里的其它服务", "metadata"):
        assert token in err, token
    assert "读取你的 Cookie" not in err, "该端点只回布尔，别吓用户"
    assert "无鉴权" not in err, "S1 已挡浏览器跨站，这话现在失实"
    for over_claim in ("仅校验请求来自本机", "只接受本机请求", "只允许本机访问"):
        assert over_claim not in err, "过度承诺：脚本不带 Origin 就能绕过"
    for honest in ("写接口只挡来自浏览器的跨站请求", "不带来源头的脚本连接",
                   "全部读取接口都不在其内"):
        assert honest in err, honest
    assert "无账号体系" in err and "--host 127.0.0.1" in err
    assert err.startswith("⚠️"), "前缀由 warn() 统一补，调用点不写"


def test_gui_no_warning_on_loopback(fake_server: dict, served: list, opened: list,
                                    monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    cli.main(["gui", "--host", "localhost", "--no-browser", "--no-update-check"])
    assert "安全告警" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("host", "loopback"),
    [("127.0.0.1", True), ("localhost", True), ("::1", True), ("127.1.2.3", True),
     ("0.0.0.0", False), ("192.168.1.10", False), ("", False)],
)
def test_is_loopback(host: str, loopback: bool) -> None:
    assert cli.is_loopback(host) is loopback


def test_display_host_maps_wildcard() -> None:
    assert cli.display_host("0.0.0.0") == "127.0.0.1"
    assert cli.display_host("::") == "127.0.0.1"
    assert cli.display_host("192.168.0.5") == "192.168.0.5"


def test_gui_update_hint_printed_when_newer(fake_server: dict, served: list, opened: list,
                                            monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    monkeypatch.setattr(cli, "check_tool_update",
                        lambda current: {"latest": "v7.7.7", "url": "u", "has_update": True})
    assert cli.main(["gui"]) == 0
    assert "v7.7.7" in capsys.readouterr().out


def test_gui_no_update_check_never_touches_network(fake_server: dict, served: list,
                                                   opened: list,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)

    def never(current: str) -> None:
        pytest.fail("不得触网")

    monkeypatch.setattr(cli, "check_tool_update", never)
    assert cli.main(["gui", "--no-update-check"]) == 0


def test_gui_survives_broken_web_layer(served: list, opened: list,
                                       monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    """Web 层能 import 但 create_app 炸了：给中文可操作提示，而不是 traceback。"""
    module = types.ModuleType("zhihu_downloader.app.server")

    def explode() -> Any:
        raise ImportError("No module named 'fastapi'")

    module.create_app = explode  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "zhihu_downloader.app.server", module)
    assert cli.main(["gui", "--no-browser", "--no-update-check"]) == 1
    assert "Web 服务初始化失败" in capsys.readouterr().err


def test_gui_reports_missing_web_module(served: list, opened: list,
                                        monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    """连模块都 import 不到时（例如只装了 CLI 依赖）也要说人话。"""
    monkeypatch.setitem(sys.modules, "zhihu_downloader.app.server", None)  # type: ignore[arg-type]
    assert cli.main(["gui", "--no-browser", "--no-update-check"]) == 1
    assert "无法加载 Web 服务模块" in capsys.readouterr().err


def test_gui_keyboard_interrupt_is_clean(fake_server: dict, opened: list,
                                         monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)

    def stop(app: Any, host: str, port: int) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "serve_app", stop)
    assert cli.main(["gui", "--no-browser", "--no-update-check"]) == 0
    assert "已停止" in capsys.readouterr().err


def test_gui_oserror_on_bind(fake_server: dict, opened: list, monkeypatch: pytest.MonkeyPatch,
                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)

    def stop(app: Any, host: str, port: int) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(cli, "serve_app", stop)
    assert cli.main(["gui", "--no-browser", "--no-update-check"]) == 1
    assert "换端口" in capsys.readouterr().err


def test_find_free_port_walks_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: port >= 3001)
    assert cli.find_free_port("127.0.0.1", 3000) == 3001


def test_find_free_port_tries_four_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    tried: list[int] = []

    def probe(host: str, port: int) -> bool:
        tried.append(port)
        return False

    monkeypatch.setattr(cli, "is_port_free", probe)
    assert cli.find_free_port("127.0.0.1", 3000) is None
    assert tried == [3000, 3001, 3002, 3003], "默认端口 + 3 次 +1"


def test_is_port_free_real_socket() -> None:
    """真 bind 一次（仅 127.0.0.1，不触外网）：占用中 False，释放后 True。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    probe.listen(1)
    port = probe.getsockname()[1]
    try:
        assert cli.is_port_free("127.0.0.1", port) is False
    finally:
        probe.close()
    assert cli.is_port_free("127.0.0.1", port) is True


def test_open_browser_later_swallows_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """opener 炸了也不能拖死线程，且要把地址告诉用户（静默最糟）。"""
    def boom(url: str, **kw: Any) -> Any:
        raise RuntimeError("没有桌面环境")

    thread = cli.open_browser_later("http://x", delay=0.0, opener=boom,
                                    probe=lambda url: 200)
    thread.join(timeout=5)
    assert not thread.is_alive(), "异常必须被吞掉，线程正常收尾"
    err = capsys.readouterr().err
    assert "http://x" in err and "手动访问" in err and chr(27) not in err


def test_open_browser_later_adds_extra_grace_after_ready() -> None:
    """就绪后仍可再宽限 delay（保留该参数只为能钉住"线程确实等过"）。"""
    seen: list[str] = []
    slept: list[float] = []
    thread = cli.open_browser_later("http://y", delay=1.5,
                                    opener=lambda url, **kw: (seen.append(url), True)[1],
                                    sleeper=slept.append,
                                    probe=lambda url: 200)
    thread.join(timeout=5)
    assert slept == [1.5] and seen == ["http://y"]


# ----------------------------------------------------------------------
# R2 #10：gui 的就绪探测取代盲睡
# ----------------------------------------------------------------------


def test_wait_until_ready_polls_health_endpoint() -> None:
    """未就绪时按间隔轮询，一旦 200 立刻返回 True（不再白睡固定秒数）。"""
    seen: list[str] = []
    slept: list[float] = []
    answers = [-1, -1, 200]

    def fake_clock() -> float:
        fake_clock.t += 0.1
        return fake_clock.t

    fake_clock.t = 0.0
    ready = cli.wait_until_ready(
        "http://127.0.0.1:3000/",
        timeout=5.0,
        interval=0.25,
        probe=lambda url: (seen.append(url), answers[min(len(seen) - 1, 2)])[1],
        clock=fake_clock,
        sleeper=slept.append,
    )
    assert ready is True
    assert seen == ["http://127.0.0.1:3000" + cli.HEALTH_PATH] * 3
    assert slept == [0.25, 0.25], "两次未就绪之间各睡一个间隔"


def test_wait_until_ready_gives_up_at_budget_but_stops_polling() -> None:
    """预算用完返回 False（调用方仍会开浏览器），且不会变成无限循环。"""
    calls: list[int] = []
    state = {"t": 0.0}

    def clock() -> float:
        state["t"] += 1.0
        return state["t"]

    ready = cli.wait_until_ready(
        "http://127.0.0.1:3000", timeout=3.0, interval=0.25,
        probe=lambda url: (calls.append(1), 503)[1], clock=clock, sleeper=lambda s: None)
    assert ready is False
    assert 0 < len(calls) <= 5


def test_wait_until_ready_default_budget_is_read_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认预算运行时读取模块常量，测试可以改小它而不必真等 5 秒。"""
    monkeypatch.setattr(cli, "GUI_READY_TIMEOUT", 0.0)
    assert cli.wait_until_ready("http://127.0.0.1:1", probe=lambda url: -1) is False


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ConnectionRefusedError("拒绝连接"), -1),
        (OSError("网络不可达"), -1),
        (urllib.error.HTTPError("u", 404, "not found", None, None), 404),
        (urllib.error.HTTPError("u", 503, "busy", None, None), 503),
    ],
)
def test_http_status_maps_failures_without_raising(
    exc: Exception, expected: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """探测通道只报状态码：任何异常都不得冒到调用方（连接被拒=还没起来）。"""
    def fake_urlopen(request, timeout=None):
        raise exc

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    assert cli.http_status("http://127.0.0.1:3000/api/health") == expected


def test_http_status_reads_status_from_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常路径：优先读 response.status，退回 getcode()。"""
    recorded: list[str] = []

    class Resp:
        status = 200

        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(
        cli.urllib.request, "urlopen",
        lambda request, timeout=None: (recorded.append(request.full_url), Resp())[1])
    assert cli.http_status("http://127.0.0.1:3999" + cli.HEALTH_PATH) == 200
    assert recorded == ["http://127.0.0.1:3999/api/health"]

    class NoStatus:
        def getcode(self) -> int:
            return 204

        def __enter__(self) -> NoStatus:
            return self

        def __exit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(cli.urllib.request, "urlopen",
                        lambda request, timeout=None: NoStatus())
    assert cli.http_status("http://127.0.0.1:3999/api/health") == 204


def test_open_browser_later_probes_before_opening() -> None:
    """顺序即结论：必须先探到就绪，再调 opener（R2 #10 的正题）。"""
    order: list[str] = []
    thread = cli.open_browser_later(
        "http://127.0.0.1:3000",
        probe=lambda url: (order.append("probe:" + url), 200)[1],
        opener=lambda url, **kw: (order.append("open:" + url), True)[1])
    thread.join(timeout=5)
    assert order == ["probe:http://127.0.0.1:3000" + cli.HEALTH_PATH, "open:http://127.0.0.1:3000"]


def test_open_browser_later_opens_even_when_never_ready(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """探测超时也照样开浏览器（白屏刷新比什么都不开好），并给用户一行提示。"""
    opened: list[str] = []
    thread = cli.open_browser_later(
        "http://127.0.0.1:3000", timeout=0.0,
        probe=lambda url: -1, opener=lambda url, **kw: (opened.append(url), True)[1])
    thread.join(timeout=5)
    assert opened == ["http://127.0.0.1:3000"]
    assert "刷新" in capsys.readouterr().err


def test_open_browser_later_swallows_probe_errors() -> None:
    """探测函数本身抛异常也不能拖死线程，更不能阻止开浏览器。"""
    opened: list[str] = []

    def bad_probe(url: str) -> int:
        raise RuntimeError("探测炸了")

    thread = cli.open_browser_later("http://z", timeout=0.0, probe=bad_probe,
                                    opener=lambda url, **kw: opened.append(url))
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert opened == [], "探测异常发生在开浏览器之前，被外层吞掉后不再继续"


def test_gui_banner_shows_version(fake_server: dict, served: list, opened: list,
                                  monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    cli.main(["gui", "--no-browser", "--no-update-check"])
    assert __version__ in capsys.readouterr().out


def test_gui_banner_does_not_advertise_disabled_docs(
    fake_server: dict, served: list, opened: list,
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """D1 发现（S1 已按 R2-P0-3 关掉 docs）：横幅不得再指向 /docs。

    那行原本写的是 API 文档链接，而 create_app 现在传 docs_url=None、
    redoc_url=None、openapi_url=None —— 点进去只有 404，等于把用户往我们
    亲手关掉的门前引。行已在终态提交里删除，这条用例负责防回归。
    """
    monkeypatch.setattr(cli, "is_port_free", lambda host, port: True)
    assert cli.main(["gui", "--no-browser", "--no-update-check"]) == 0
    out = capsys.readouterr().out
    assert "API 文档" not in out and "/docs" not in out and "/redoc" not in out
    assert "Web 界面" in out, "删掉文档行后，横幅仍要告诉用户去哪儿打开界面"
