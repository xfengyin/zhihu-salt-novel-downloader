"""命令行入口（架构规格书 §2.15）：login / download / shelf / doctor / gui。

职责单一：解析参数 -> 装配客户端 -> 调用模块层 -> 渲染进度与结果。
业务逻辑一律不在本文件里（下载编排在 engine.fetcher，诊断在 auth.doctor，
升级检查在 update），因此 CLI 与 Web 层共享同一套内核。

两个产品级决策（§2.15）：

1. 双击即用：不带任何参数直接运行等价于 gui 子命令（起本地服务 + 自动开浏览器），
   Windows 用户双击 EXE 即进入图形界面；已显式给出子命令时不触发。
2. gui 对 app.server 的依赖是**函数内懒 import**：import 本模块不会拉起
   FastAPI/uvicorn，既省启动时间，也让 CLI 测试与 Web 层文件互不阻塞。

进度条：纯标准库实现，靠回车符把输出压回行首，只写 stderr（stdout 留给结果输出，
方便管道处理文件清单）；线程安全（fetcher 从工作线程回调）；retry 事件只在行尾就地
追加一段黄色提示，不重画整行（避免中文标题来回跳动）；非 TTY 自动退回纯文本。
"""

from __future__ import annotations

import argparse
import math
import os
import socket
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .auth import browser, doctor, qr
from .auth import cookies as cookie_store
from .engine.client import ZhihuClient
from .engine.fetcher import download_book, resolve_book
from .errors import (
    AuthError,
    CheckpointError,
    ExportError,
    ParseError,
    SaltError,
    UnsupportedUrlError,
    ZhihuError,
)
from .export import FORMATS
from .shelf import Shelf
from .types import BookMeta, BookResult, ChapterRef, ProgressEvent, ShelfBook
from .update import check_tool_update, format_release_hint

__all__ = [
    "ProgressPrinter",
    "build_parser",
    "clamp_rate_limit",
    "clamp_workers",
    "cmd_doctor",
    "cmd_download",
    "cmd_gui",
    "cmd_login",
    "cmd_shelf",
    "main",
    "read_batch_file",
    "render_progress",
    "render_shelf_table",
]

# 控制字符显式用 chr() 构造：进度条依赖回车符，写成转义字符容易被打包/转义链吃掉。
#: 回车符（CR）：把光标压回行首，实现单行刷新的进度条。
CR = chr(13)
#: 换行符（LF）。
NL = chr(10)

# 限速阈值与 auth.doctor 共用同一组常量，避免 CLI 与诊断口径漂移（规格 §2.7）。
#: 每秒请求数默认值与允许区间（超出自动钳制并告警）。
DEFAULT_RATE_LIMIT = doctor.DEFAULT_RATE_LIMIT
MIN_RATE_LIMIT = doctor.MIN_RATE_LIMIT
MAX_RATE_LIMIT = doctor.MAX_RATE_LIMIT

#: 并行解析数默认值与允许区间（HTTP 由限速串行化，故它不提高吞吐上限）。
DEFAULT_WORKERS = 3
MIN_WORKERS = 1
MAX_WORKERS = 8

#: 进度条方块宽度（不含方括号）。
BAR_WIDTH = 20

#: CLI 默认导出目录（gui 用 ~/.zhihu_downloader/output，见规格 §3）。
DEFAULT_OUTPUT_DIR = "./output"

#: gui：端口被占时自动 +1 的重试次数（规格 §2.15）。
GUI_PORT_RETRIES = 3
GUI_DEFAULT_HOST = "127.0.0.1"
GUI_DEFAULT_PORT = 3000
#: 开浏览器前的**就绪探测**预算（秒）。R2 #10：v4 用「盲睡 1.5s」糊过「立刻打开会白屏」
#: 这个问题，既慢又不可靠（机器快时白等、机器慢时照样白屏）；现在改成真的去问服务。
GUI_READY_TIMEOUT = 5.0
#: 就绪探测的轮询间隔（秒）。
GUI_READY_INTERVAL = 0.25
#: 单次探测的请求超时（秒）——只打回环地址，半秒足够。
HEALTH_PROBE_TIMEOUT = 0.5
#: I1 server 的健康检查路径：GET 拿到 200 即代表页面可用。
HEALTH_PATH = "/api/health"
#: 探测请求的 UA（与 update.py 同族命名，便于服务端排查）。
_PROBE_USER_AGENT = "zhihu-salt-novel-downloader/gui-probe"
#: 视为"仅本机访问"的回环地址；其余地址启动时打印安全告警。
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

#: 扫码登录：轮询间隔与总超时（秒）。
QR_POLL_INTERVAL = 2.0
QR_LOGIN_TIMEOUT = 300.0

#: ANSI 黄色（retry 行内提示用）；非 TTY 或设了 NO_COLOR 时自动退回纯文本。
_YELLOW = chr(27) + "[33m"
_RESET = chr(27) + "[0m"
#: 各异常类别的"下一步"补充提示：仅在模块层消息里没写指引时才追加（见 explain_failure）。
_NEXT_STEP: dict[type, str] = {
    AuthError: "请先运行 zhihu-downloader login 重新登录，或 login --browser 从浏览器导入 Cookie",
    CheckpointError: "也可删除输出目录下的 .zhihu_state/ 目录后重试",
    ZhihuError: "可稍后重试；反复 403/429 请重新登录并把 --rate-limit 调低",
    ParseError: "页面结构可能已改版，请运行 zhihu-downloader doctor 自检并升级工具",
    UnsupportedUrlError: "支持的是知乎盐选专栏目录页与章节页链接",
    ExportError: "请检查输出目录的磁盘空间与写权限",
}


# ----------------------------------------------------------------------
# 数值钳制
# ----------------------------------------------------------------------
def clamp_rate_limit(value: float | None) -> float:
    """把限速钳制到 [MIN_RATE_LIMIT, MAX_RATE_LIMIT] 请求/秒。

    Args:
        value: 用户传入值；None/非数字/inf/nan 一律回落到默认值。

    Returns:
        钳制后的限速（浮点数）。
    """
    if value is None:
        return DEFAULT_RATE_LIMIT
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RATE_LIMIT
    if not math.isfinite(number):
        return DEFAULT_RATE_LIMIT
    return min(max(number, MIN_RATE_LIMIT), MAX_RATE_LIMIT)


def clamp_workers(value: int | None) -> int:
    """把并发章节数钳制到 [MIN_WORKERS, MAX_WORKERS]（规格 §2.15：默认 3，区间 1-8）。

    Args:
        value: 用户传入值；None 或不可转 int 时回落到默认值。

    Returns:
        钳制后的并发数。
    """
    if value is None:
        return DEFAULT_WORKERS
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WORKERS
    return min(max(number, MIN_WORKERS), MAX_WORKERS)


def resolve_limits(args: argparse.Namespace) -> tuple[float, int]:
    """从参数里取限速与并发并钳制，越界时往 stderr 打一条中文告警。

    Args:
        args: 已解析的参数（可能没有 rate_limit / workers 属性，如 shelf list）。

    Returns:
        (rate_limit, workers)。
    """
    raw_rate = getattr(args, "rate_limit", None)
    raw_workers = getattr(args, "workers", None)
    rate_limit = clamp_rate_limit(raw_rate)
    workers = clamp_workers(raw_workers)
    if raw_rate is not None and _as_float(raw_rate) != rate_limit:
        warn(f"--rate-limit {raw_rate} 超出允许区间 [{MIN_RATE_LIMIT}, {MAX_RATE_LIMIT}]，"
             f"已按 {rate_limit} 请求/秒执行（更快会被反爬拦；限速是吞吐上限，0 也不等于关限速）")
    if raw_workers is not None and _as_int(raw_workers) != workers:
        warn(f"--workers {raw_workers} 超出允许区间 [{MIN_WORKERS}, {MAX_WORKERS}]，"
             f"已按 {workers} 执行（workers 只并行解析，HTTP 由限速串行，调大不提速）")
    return rate_limit, workers


def _as_float(value: Any) -> float:
    """尽力转 float，失败返回 -1.0（只为"是否被钳制"的比较服务）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _as_int(value: Any) -> int:
    """尽力转 int，失败返回 -1（同 _as_float 的用途）。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


# ----------------------------------------------------------------------
# 输出小工具
# ----------------------------------------------------------------------
def echo(message: str = "") -> None:
    """往 stdout 写一行（结果输出，可被管道消费）。

    显式 flush：stdout 被重定向到文件时是块缓冲，而 uvicorn 的日志走 stderr
    不缓冲；不 flush 的话"双击即用"的界面地址会被压在服务日志后面。
    """
    print(message, flush=True)


#: 告警行的统一前缀。**只在 warn() 内部使用**，调用点禁止自己写（见 warn 的契约）。
_WARN_ICON = "⚠️"


def note(message: str) -> None:
    """往 stderr 写一行**不带图标**的文本：错误行与中性通知专用。

    stderr 的三个通道（R2 复核 A 定下的契约，别再新增第四个）：

    * echo() → stdout，可管道消费的结果输出（文件清单、表格）；
    * warn() → stderr，告警，自动带 ⚠️；
    * note() → stderr，中性内容：❌ 错误行、Ctrl+C / 停止服务这类回执。

    Args:
        message: 待输出的一行文本（可自带行首换行，原样保留）。
    """
    print(message, file=sys.stderr)


def warn(message: str) -> None:
    """往 stderr 写一行中文告警：**前缀在这里统一补，调用点一律不写**。

    为什么是无条件加（而不是「已带 ⚠️ 就跳过」）：跳过式实现会让「调用点自己写
    前缀」成为可行写法，新增调用点漏写时静默不一致；无条件补则写错会显示成两个
    ⚠️，一眼可见、当场暴露。中性通知与 ❌ 错误行走 note()。

    Args:
        message: 告警正文（不含前缀）。行首空白（例如 Ctrl+C 前的换行）保留在前缀之前。
    """
    head = message.lstrip()
    lead = message[: len(message) - len(head)]
    if not head:
        print(message, file=sys.stderr)
        return
    print(lead + _WARN_ICON + "  " + head, file=sys.stderr)


def fail(message: str) -> int:
    """往 stderr 写一条错误并给出退出码 1（业务失败：请求/解析/导出等）。"""
    note(f"❌ {message}")
    return 1


def usage_fail(message: str) -> int:
    """往 stderr 写一条用法错误并给出退出码 2（与 argparse 的用法错误口径一致）。"""
    note(f"❌ {message}")
    return 2


def supports_color(stream: TextIO | None = None) -> bool:
    """是否可以上色：目标是 TTY、且没被 NO_COLOR / TERM=dumb 关掉。

    管道与文件重定向里必须输出纯文本，否则 "download ... > files.txt" 会混进转义序列。
    """
    target = stream if stream is not None else sys.stderr
    try:
        if not target.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return os.environ.get("TERM", "") != "dumb"


def paint(text: str, color: str, *, enabled: bool) -> str:
    """按需给文本包上 ANSI 颜色码（enabled=False 时原样返回）。"""
    return color + text + _RESET if enabled else text


def explain_failure(exc: BaseException, *, next_step: str | None = None) -> str:
    """按 errors.py 层级把异常翻成"中文原因 + 下一步"，**绝不把 traceback 甩给用户**。

    模块层的消息本身已带可操作指引（例如 CheckpointError 会写"请删除该文件或加
    --no-resume 重新下载整本"），此时原样透出，不再叠加一句重复提示。

    Args:
        exc: 捕获到的异常。

    Returns:
        单行中文文本（含换行符会被压成空格）。
    """
    if isinstance(exc, SaltError):
        reason = " ".join(str(exc).split()) or type(exc).__name__
        hint = _NEXT_STEP.get(type(exc)) if next_step is None else next_step
        if hint and "请" not in reason and "→" not in reason:
            reason = reason + "。" + hint
        return reason
    detail = " ".join(str(exc).split())
    return f"未预期错误（{type(exc).__name__}）：{detail or '无详细信息'}"


def ensure_utf8_streams() -> None:
    """Windows / 冻结包兜底：强制 stdout、stderr 使用 UTF-8（移植 v4 cli.py:224-231）。

    PyInstaller 冻结的 Windows 程序默认编码可能是 cp1252，中文 help 与进度条方块
    会直接触发 UnicodeEncodeError；errors="replace" 保证任何环境都不可能因为"打印
    一条消息"而让命令失败。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 - 兜底本身失败也不能崩（如流已被关闭）
                pass


# ----------------------------------------------------------------------
# 进度条（规格 §2.15）
# ----------------------------------------------------------------------
def render_progress(event: ProgressEvent, *, width: int = BAR_WIDTH, note: str = "",
                     chapter_label: bool = True) -> str:
    """渲染单行进度文本（不含回车符），供 ProgressPrinter 与测试共用。

    形如：[███░░░░░░░░░░░░░░░░] 12/47 (25%) 第12章：初入江湖  ⚠️ 第 1 次重试……

    Args:
        event: fetcher 发出的进度事件。
        width: 进度条方块数。
        note: 行内附加提示（retry 事件用）。
        chapter_label: 是否把 title 当作"第 N 章"渲染。toc / done 事件的 title
            是**书名**而非章节名，必须传 False，否则会显示成"第47章：书名"。

    Returns:
        单行字符串（不含 CR 与结尾换行）。
    """
    total = max(0, int(event.total or 0))
    current = max(0, int(event.current or 0))
    shown = min(current, total) if total else current
    ratio = (shown / total) if total else 0.0
    filled = min(width, int(width * ratio)) if total else 0
    bar = "█" * filled + "░" * (width - filled)
    percent = int(ratio * 100) if total else 0
    line = f"[{bar}] {shown}/{total} ({percent}%)"
    title = (event.title or "").strip()
    if title:
        line += f" 第{shown}章：{title}" if (chapter_label and shown) else f" {title}"
    if note:
        line += f"  ⚠️ {note}"
    return line


class ProgressPrinter:
    """把 engine.fetcher 的进度事件渲染成 stderr 单行进度条。

    实现要点：

    - 只写 stderr：stdout 留给书名与文件清单，便于 "zhihu-downloader download ... > files.txt"；
    - 线程安全：fetcher 从工作线程回调，这里用锁串行化写入；
    - retry 事件**只做行内提示**：进度条本体已在屏幕上且数值没变时，绝不重画整行
      （重画会让中文标题来回跳动），而是在行尾就地追加一段黄色提示，下一章节完成时
      由整行重画顺带擦除；
    - 擦除残留按**显示宽度**补空格（中文占两列），否则长标题会留下垃圾字符；
    - 上色仅在 TTY 生效：管道/重定向里输出纯文本。
    """

    def __init__(self, stream: TextIO | None = None, *, width: int = BAR_WIDTH,
                 color: bool | None = None) -> None:
        """初始化进度渲染器。

        Args:
            stream: 输出流；None 表示每次动态取 sys.stderr（便于测试捕获）。
            width: 进度条方块数。
            color: 是否上色；None 表示按输出流是否 TTY 自动判断。
        """
        self._stream = stream
        self._width = width
        self._color = color
        self._lock = threading.Lock()
        self._note = ""
        #: 当前已上屏的进度条本体（不含行内提示），用于判断"要不要重画整行"。
        self._bar_line = ""
        #: 当前行占用的显示列数（含已追加的提示），供下次重画时擦除残留。
        self._cols = 0
        self._line_open = False
        #: fetcher 已经通过 error 事件播报过失败原因，调用方据此避免重复打印。
        self.saw_error = False

    @property
    def colored(self) -> bool:
        """本次输出是否上色（None -> 问 TTY）。"""
        return supports_color(self.stream) if self._color is None else bool(self._color)

    # - 作为 progress 回调直接传入 download_book
    def __call__(self, event: ProgressEvent) -> None:
        self.handle(event)

    @property
    def stream(self) -> TextIO:
        """实际输出流（延迟解析，保证能被 pytest 的 capsys 捕获）。"""
        return self._stream if self._stream is not None else sys.stderr

    def handle(self, event: ProgressEvent) -> None:
        """处理一个进度事件（规格 §2.3 的 kind 协议）。"""
        kind = (event.kind or "").strip().lower()
        if kind == "retry":
            self.show_note(event.message or "请求失败，正在重试")
            return
        if kind == "chapter":
            self._draw(event)
            return
        if kind == "toc":
            head = event.title or "正在解析目录"
            self.write_line(f"📖 {head}（{event.message}）" if event.message else f"📖 {head}")
            self._draw(event, chapter_label=False)
            return
        if kind == "export":
            self.write_line("📦 " + (event.message or "正在导出"))
            return
        if kind == "done":
            self._draw(event, chapter_label=False)
            self.finish()
            return
        if kind == "error":
            self.write_line("❌ " + (event.message or "下载失败"))
            self.saw_error = True
            return
        if event.message:
            self.write_line("ℹ️  " + event.message)

    def finish(self) -> None:
        """收尾：确保进度行以换行结束（调用方在 finally 里兜底调用）。"""
        with self._lock:
            if self._line_open:
                self._write_raw(NL)
            self._reset_line()
            self._flush()

    def write_line(self, text: str) -> None:
        """打印一条普通行：先结束当前进度行，避免文字与进度条叠在一起。"""
        with self._lock:
            if self._line_open:
                self._write_raw(NL)
            self._reset_line()
            self._write_raw(text + NL)
            self._flush()

    def show_note(self, note: str) -> None:
        """retry 事件：在当前进度行尾部**就地**追加黄色提示，不重画进度条本体。

        进度条数值在重试期间并没有变化，重画整行会让中文标题来回跳动；因此只在
        行尾追加一段提示。同一章连续重试时提示已存在，才退化为整行重画一次
        （条体文字完全相同，视觉上仍然稳定）。

        Args:
            note: 重试原因（fetcher 已给成中文，形如"第 1 次重试（2s 后）：超时"）。
        """
        with self._lock:
            had_note = bool(self._note)
            self._note = note
            plain = "  ⚠️ " + note
            styled = paint(plain, _YELLOW, enabled=self.colored)
            if not self._line_open:
                # 还没画过进度行（例如第一章就在重试）：单独占一行，不动光标
                self._write_raw(paint("⚠️ " + note, _YELLOW, enabled=self.colored) + NL)
                self._flush()
                return
            if had_note:
                self._paint_line(self._bar_line, note)
            else:
                self._write_raw(styled)
                self._cols += display_width(plain)
            self._flush()

    def _draw(self, event: ProgressEvent, *, chapter_label: bool = True) -> None:
        """整行刷新进度条本体（chapter_label=False 用于 toc / done 这类书名事件）。"""
        bar = render_progress(event, width=self._width, chapter_label=chapter_label)
        with self._lock:
            self._note = ""
            self._paint_line(bar, "")
            self._bar_line = bar
            self._flush()

    def _paint_line(self, bar: str, note: str) -> None:
        """把"条体 + 可选行内提示"整行刷上屏幕，并补空格擦掉上一帧残留。"""
        if self._line_open:
            self._write_raw(CR)
        plain = bar + ("  ⚠️ " + note if note else "")
        styled = bar + (paint("  ⚠️ " + note, _YELLOW, enabled=self.colored) if note else "")
        self._write_raw(styled + " " * max(0, self._cols - display_width(plain)))
        self._cols = display_width(plain)
        self._line_open = True

    def _reset_line(self) -> None:
        """行状态归零（调用方必须持有 self._lock）。"""
        self._note = ""
        self._bar_line = ""
        self._cols = 0
        self._line_open = False

    def _flush(self) -> None:
        """刷新输出流（流已失效时忽略）。调用方必须持有 self._lock。"""
        try:
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def _write_raw(self, text: str) -> None:
        """无锁写入（调用方必须持有 self._lock）。

        输出流本身坏掉（被关闭、被重定向到已失效的句柄）时静默丢弃：
        进度条只是显示层，绝不能因为"刷不出进度"让一次好容易下完的下载报错。
        """
        try:
            self.stream.write(text)
        except (OSError, ValueError):
            pass


# ----------------------------------------------------------------------
# 装配层（单独成函数，便于测试整体替换）
# ----------------------------------------------------------------------
def make_client(
    rate_limit: float | None = None,
    cookie_file: str | Path | None = None,
) -> ZhihuClient:
    """构造知乎客户端（独立函数便于测试替换，不改变任何模块层签名）。"""
    return ZhihuClient(cookie_file=cookie_file, rate_limit=clamp_rate_limit(rate_limit))


def make_shelf() -> Shelf:
    """构造书架（默认路径 ~/.zhihu_downloader/shelf.json）。"""
    return Shelf()


def release_hint(current: str | None = None) -> str:
    """查一次工具新版本并给出一行提示；失败或无新版返回空串（§2.16 静默）。"""
    try:
        return format_release_hint(check_tool_update(current or __version__))
    except Exception:  # noqa: BLE001 - 双保险：升级通道绝不允许影响主流程
        return ""


def display_host(host: str) -> str:
    """给用户/浏览器看的地址：通配监听地址换成 127.0.0.1（0.0.0.0 打不开）。"""
    return GUI_DEFAULT_HOST if host in ("0.0.0.0", "::", "") else host


def is_loopback(host: str) -> bool:
    """是否为仅本机可达的回环地址。"""
    value = (host or "").strip()
    return value in LOOPBACK_HOSTS or value.startswith("127.")


def is_port_free(host: str, port: int) -> bool:
    """探测端口是否空闲（能 bind 即认为空闲）。

    已知取舍（R2 #10）：bind 成功后必须 close 才能交给 uvicorn，中间存在一个理论上的
    抢占窗口（TOCTOU）。这个窗口无法在本层根除（除非把 socket 直接递给 uvicorn），
    而代价可控：抢注发生时 uvicorn 绑定抛 OSError，cmd_gui 给出换端口的中文提示，
    不会崩、不会静默失败。所以这里保持"探测到空闲就用"，不再叠加重试。
    """
    family = socket.AF_INET6 if ":" in (host or "") else socket.AF_INET
    probe = socket.socket(family, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def find_free_port(host: str, port: int, retries: int = GUI_PORT_RETRIES) -> int | None:
    """端口被占时自动 +1 重试（规格 §2.15：最多 3 次）。

    Args:
        host: 监听地址。
        port: 期望端口。
        retries: 失败后的 +1 重试次数。

    Returns:
        第一个空闲端口；连续 retries+1 个都被占用时返回 None。
    """
    for offset in range(retries + 1):
        candidate = port + offset
        if is_port_free(host, candidate):
            return candidate
    return None


def serve_app(app: Any, host: str, port: int) -> None:
    """用 uvicorn 启动服务（独立函数，测试里整体替换）。"""
    import uvicorn  # noqa: PLC0415 - 懒 import：login/download 不该为 Web 依赖买单

    uvicorn.run(app, host=host, port=port, log_level="info")


def http_status(url: str, timeout: float = HEALTH_PROBE_TIMEOUT) -> int:
    """取一次 URL 的 HTTP 状态码；任何异常返回 -1。

    探测失败不等于服务坏了（连接被拒=还没起来，超时=正忙），所以这里不抛错、
    只报状态码，由调用方决定继续等还是放弃。只用于打回环地址上的自有端点，
    不接受任何远端可控的 URL。

    Args:
        url: 完整地址，例如 http://127.0.0.1:3000/api/health。
        timeout: 单次请求超时秒数。

    Returns:
        HTTP 状态码；4xx/5xx 返回其状态码，完全取不到时返回 -1。
    """
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _PROBE_USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = getattr(response, "status", None)
            return int(status if status is not None else response.getcode())
    except urllib.error.HTTPError as exc:  # 4xx/5xx 也是有效信号（别人占了这端口）
        return int(exc.code)
    except Exception:  # noqa: BLE001 - 连接被拒/超时/DNS 失败统一算「还没就绪」
        return -1


def wait_until_ready(
    base_url: str,
    *,
    timeout: float | None = None,
    interval: float = GUI_READY_INTERVAL,
    probe: Callable[[str], int] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """轮询服务的健康检查端点，直到拿到 200（R2 #10：用真探测取代盲睡）。

    与盲睡的区别：服务起来的第一时间就返回（通常远低于预算），服务慢也不会被提前
    放行；预算用完仍不就绪时返回 False，调用方照样去开浏览器——白屏刷新一下就好，
    什么都不开更糟。

    Args:
        base_url: 服务根地址（不含路径），例如 http://127.0.0.1:3000。
        timeout: 总预算秒数；None 取 GUI_READY_TIMEOUT（运行时读取，便于测试改写）。
        interval: 两次探测之间的间隔秒数。
        probe: 状态码探测函数，默认取 http_status（运行时读取，测试注入假端点）。
        clock: 单调时钟，默认 time.monotonic；测试注入假时钟可免真等。
        sleeper: 等待函数，默认 time.sleep。

    Returns:
        True 表示服务已就绪；False 表示预算内未就绪。
    """
    check = probe or http_status
    budget = GUI_READY_TIMEOUT if timeout is None else float(timeout)
    url = base_url.rstrip("/") + HEALTH_PATH
    deadline = clock() + max(0.0, budget)
    while True:
        if check(url) == 200:
            return True
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        sleeper(min(interval, remaining))


def open_browser_later(
    url: str,
    *,
    delay: float = 0.0,
    timeout: float | None = None,
    opener: Callable[[str], Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    probe: Callable[[str], int] | None = None,
) -> threading.Thread:
    """后台线程：先轮询健康检查等服务就绪，再打开浏览器（R2 #10）。

    旧实现是「盲睡 1.5 秒再开」：端口探测通过并不代表 uvicorn 已能应答，用户照样
    可能看到白屏。现在改为真探测就绪，探测超时也不阻塞开浏览器。

    Args:
        url: 实际访问地址（端口可能已 +1）。
        delay: 就绪之后再额外宽限的秒数（默认 0）。保留它只为测试能钉住「线程确实
            等过」，生产路径不再靠它盲睡。
        timeout: 就绪探测预算；None 取 GUI_READY_TIMEOUT。
        opener: 打开函数，默认 webbrowser.open。
        sleeper: 等待函数，默认 time.sleep（注入后可捕获轮询节奏，不用真等）。
        probe: 状态码探测函数，默认 http_status。

    Returns:
        已启动的守护线程句柄。
    """

    def _worker() -> None:
        """探测就绪 ->（可选）额外宽限 -> 开浏览器；任何异常都不允许影响服务。

        打不开浏览器不是错误（无桌面环境下很正常），但**静默**会让用户以为服务没起来，
        所以这里把地址原样再提示一次，用户复制到浏览器即可。
        """
        try:
            if not wait_until_ready(url, timeout=timeout, probe=probe, sleeper=sleeper):
                warn("服务响应偏慢，若浏览器显示白屏请稍后刷新（F5）")
            if delay > 0:
                sleeper(delay)
            opened = bool((opener or webbrowser.open)(url, new=2))
        except Exception:  # noqa: BLE001 - 打不开浏览器不影响服务可用
            warn("自动打开浏览器失败，请手动访问：" + url)
            return
        if not opened:
            warn("自动打开浏览器失败（可能没有图形环境），请手动访问：" + url)

    thread = threading.Thread(target=_worker, name="zhihu-open-browser", daemon=True)
    thread.start()
    return thread


# ----------------------------------------------------------------------
# login
# ----------------------------------------------------------------------
def cmd_login(args: argparse.Namespace) -> int:
    """login 子命令：默认扫码登录，--browser 时从浏览器导入 Cookie。

    Args:
        args: 已解析参数（browser / cookie_file）。

    Returns:
        0 成功；1 失败（消息为中文且含下一步）。
    """
    client = make_client(cookie_file=getattr(args, "cookie_file", None))
    if getattr(args, "browser", False):
        return _login_with_browser(client)
    return _login_with_qrcode(client)


def _login_with_qrcode(
    client: ZhihuClient,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    interval: float = QR_POLL_INTERVAL,
    timeout: float = QR_LOGIN_TIMEOUT,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """扫码登录（移植 v4 cmd_qr_login，改用 auth.qr 三函数）。

    二维码是图片，终端里画 ASCII 码反而看不清，因此存临时文件并打印路径，
    用户点开图片用手机扫；随后按 interval 轮询直到 confirmed / expired / 超时。

    Args:
        client: 知乎客户端（confirmed 时 auth.qr 会自行把 Cookie 落盘）。
        sleeper: 等待函数（测试注入，避免真实 sleep）。
        interval: 轮询间隔秒数。
        timeout: 总等待秒数。
        clock: 计时函数（测试注入）。

    Returns:
        0 登录成功；1 失败。
    """
    try:
        info = qr.start(client)
        token = str(info.get("token") or "")
        image = qr.image(client, token)
    except SaltError as exc:
        return fail(explain_failure(exc, next_step=_LOGIN_NEXT_STEP))

    qr_path = _save_qr_image(image)
    echo("请用知乎 APP 扫码登录：")
    echo(f"   🖼  二维码图片: {qr_path}")
    echo("   ⏳ 等待扫码确认中……（Ctrl+C 取消）")

    deadline = clock() + timeout
    last_status = ""
    while clock() < deadline:
        try:
            result = qr.poll(client, token)
        except SaltError as exc:
            return fail(explain_failure(exc, next_step=_LOGIN_NEXT_STEP))
        status = str(result.get("status") or "")
        if status == "confirmed":
            saved = result.get("saved_to") or client.save_cookies()
            echo(f"✅ 登录成功（user_id={result.get('user_id')}），Cookie 已保存到 {saved}")
            return 0
        if status == "error":
            return fail(f"登录失败：{result.get('error') or '未知错误'}"
                        " → 可重试 zhihu-downloader login，或用 --browser 从浏览器导入")
        if status == "expired":
            return fail("二维码已过期 → 请重新运行 zhihu-downloader login")
        if status == "scanned" and last_status != "scanned":
            echo("   📱 已扫码，请在手机上点确认登录……")
        last_status = status
        sleeper(interval)
    return fail("等待扫码超时（5 分钟）→ 请重新运行 zhihu-downloader login")


#: 登录阶段的"下一步"与默认不同：此时再让用户去跑 login 命令没意义。
_LOGIN_NEXT_STEP = "可稍后重试一次；反复失败请改用浏览器导入：zhihu-downloader login --browser"


def _save_qr_image(image: bytes) -> str:
    """把二维码图片写到临时文件，返回路径字符串（不删除，供用户点开扫）。"""
    with tempfile.NamedTemporaryFile(prefix="zhihu-qr-", suffix=".jpg", delete=False) as handle:
        handle.write(image or b"")
        return handle.name


def _login_with_browser(client: ZhihuClient) -> int:
    """浏览器导入登录（auth.browser）：失败时给中文提示并指回扫码。"""
    echo("🔍 正在从本机浏览器读取知乎 Cookie（Chrome -> Firefox -> Edge）……")
    try:
        found = browser.fetch_zhihu_cookies(save_to=client.cookie_file)
    except SaltError as exc:
        return fail(explain_failure(exc, next_step=_LOGIN_NEXT_STEP))
    except Exception as exc:  # noqa: BLE001 - 浏览器锁库等第三方异常也要变人话
        return fail(f"浏览器 Cookie 导入失败（{type(exc).__name__}: {exc}）"
                    " → 请完全退出浏览器后重试，或改用扫码登录：zhihu-downloader login")
    try:
        client.load_cookies(found)
    except SaltError as exc:  # pragma: no cover - 已落盘的字典不会失败，兜底而已
        return fail(str(exc))
    echo(f"✅ 已导入 {len(found)} 个 Cookie，保存到 {client.cookie_file}（权限 0600）")
    missing = [key for key in cookie_store.KEY_COOKIES if not found.get(key)]
    if missing:
        warn("缺少关键字段 " + "、".join(missing)
             + " → 请在该浏览器里登录 https://www.zhihu.com 后重试；"
             + "缺 d_c0 时无法签名，下载会被 403 拦截")
    return 0


# ----------------------------------------------------------------------
# download
# ----------------------------------------------------------------------
def read_batch_file(path: str | Path) -> list[str]:
    """读取批量下载清单：每行一个 URL，忽略空行与 # 注释，按出现顺序去重。

    Args:
        path: 清单文件路径。

    Returns:
        URL 列表（已去重）。

    Raises:
        SaltError: 文件不存在或不可读（消息含下一步建议）。
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise SaltError(
            f"无法读取批量文件 {file}：{exc} → 请确认文件存在且可读"
            "（格式：每行一个知乎链接，# 开头为注释）"
        ) from exc
    urls: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        url = stripped.split()[0]
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def cmd_download(args: argparse.Namespace) -> int:
    """download 子命令：单本或批量下载 + 进度条 + 文件清单 + 书架登记。

    批量模式（--batch-file）逐本串行下载，**单本失败不中断其余**，最后汇总
    成功/失败与原因；限速与并发按 §2.15 钳制到安全区间。

    Args:
        args: 已解析参数。

    Returns:
        0 全部成功；1 至少一本失败。
    """
    urls: list[str] = []
    if args.url:
        urls.append(str(args.url).strip())
    if getattr(args, "batch_file", None):
        try:
            urls.extend(read_batch_file(args.batch_file))
        except SaltError as exc:
            return usage_fail(str(exc))
    urls = [u for u in urls if u]
    if not urls:
        return usage_fail("请提供 --url <链接>，或用 --batch-file <清单> 指定每行一个链接"
                         "（可运行 zhihu-downloader download --help 看示例）")

    rate_limit, workers = resolve_limits(args)
    client = make_client(rate_limit=rate_limit, cookie_file=getattr(args, "cookie_file", None))
    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    resume = not getattr(args, "no_resume", False)
    fmt = str(args.format or "md")

    results: list[BookResult] = []
    failures: list[tuple[str, str]] = []
    for index, url in enumerate(urls, 1):
        if len(urls) > 1:
            echo(f"📚 [{index}/{len(urls)}] {url}")
        printer = ProgressPrinter()
        # 标准记账通路（与 server 一致）：resolve -> download_book(meta=) ->
        # record_download(chapter_urls=有序)。目录页整轮只抓一次，记账直接复用 meta。
        meta = preresolve(client, url)
        try:
            result = download_book(
                client, url, fmt=fmt, output_dir=output_dir,
                progress=printer, resume=resume, workers=workers, meta=meta,
            )
        except SaltError as exc:  # 模块层可预期错误：中文原因 + 下一步（含 --no-resume 指引）
            _record_failure(url, exc, printer, failures)
            continue
        except Exception as exc:  # noqa: BLE001 - 最后兜底：也只打一行分类后的中文，绝不甩 traceback
            _record_failure(url, exc, printer, failures)
            continue
        printer.finish()
        results.append(result)
        skipped = f"，续传跳过 {result.skipped_existing} 章" if result.skipped_existing else ""
        echo(f"✅ {result.title}（共 {result.chapters} 章{skipped}）")
        for path in result.files:
            echo(f"   📄 {path}")
        _record_to_shelf(result, fmt, meta)

    if len(urls) > 1:
        echo("")
        echo(f"📊 批量汇总：成功 {len(results)} 本 / 失败 {len(failures)} 本（共 {len(urls)} 本）")
        for url, reason in failures:
            echo(f"   ❌ {url} → {reason}")
    return 0 if not failures else 1


def _record_failure(key: str, exc: BaseException, printer: ProgressPrinter,
                    failures: list[tuple[str, str]], *, what: str = "下载失败") -> None:
    """记录一本失败：收尾进度行 + 归类原因 + 打印一行中文（不重复 fetcher 已播报的内容）。

    Args:
        key: 失败对象的标识（URL 或书名）。
        exc: 捕获到的异常。
        printer: 该次下载的进度渲染器。
        failures: 汇总用的失败列表（原地追加）。
    """
    printer.finish()
    reason = explain_failure(exc)
    failures.append((key, reason))
    if not printer.saw_error:  # fetcher 的 error 事件已经播报过原因，不重复刷屏
        note(f"❌ {what}：{key} → {reason}")


def preresolve(client: ZhihuClient, url: str) -> BookMeta | None:
    """预解析目录（标准记账通路第一步）；失败返回 None，交给 download_book 重解析。

    这里不把异常抛出去：预解析只是为记账取一份有序章节表，真正权威的报错由
    download_book(meta=None) 那条路给出，避免同一链接报两次错，也避免客户端
    不可用（或本地 fake 缺属性）时把整轮下载带崩。
    """
    try:
        return resolve_book(client, url)
    except SaltError:
        return None
    except Exception:  # noqa: BLE001 - 预解析是优化，不是下载的前置条件
        return None


def diff_new_chapters(meta: BookMeta, known_urls: list[str]) -> list[ChapterRef]:
    """就地按 meta 求新增章节（语义与 engine.check_new_chapters 一致：保序、过滤空 URL）。

    为什么不直接调 check_new_chapters：它内部会再 resolve 一次目录页，而标准记账通路
    要求整轮只抓一次目录（同一份 meta 还要交给 download_book(meta=) 复用）。
    与 server 的 shelf_update 保持同一实现。
    """
    known = {u for u in known_urls if u}
    return [ch for ch in meta.chapters if ch.url not in known]


def _record_to_shelf(result: BookResult, fmt: str, meta: BookMeta | None = None) -> None:
    """下载成功后登记书架（失败只告警，绝不推翻已成功的下载）。

    有序章节 URL 直接取自标准通路传下来的 meta（BookResult 契约里没有该字段），
    因此这里不再额外请求目录页；meta 为 None（预解析失败）时留空，追更时会补齐。
    """
    chapter_urls = [ch.url for ch in meta.chapters] if meta is not None else None
    chapter_urls = chapter_urls or None
    try:
        book = make_shelf().record_download(result, fmt, chapter_urls=chapter_urls)
        echo(f"   📚 已登记书架：id={book.id}（追更用 zhihu-downloader shelf update --id {book.id}）")
    except SaltError as exc:
        warn(f"文件已导出，但书架登记失败：{exc}")
    except Exception as exc:  # noqa: BLE001 - 磁盘只读等极端情况也不能推翻已成功的下载
        warn("文件已导出，但书架登记失败：" + explain_failure(exc))


# ----------------------------------------------------------------------
# shelf
# ----------------------------------------------------------------------
def display_width(text: str) -> int:
    """终端显示宽度：中日韩全角字符按 2 列计（表格对齐用）。"""
    width = 0
    for char in str(text):
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def _pad(text: str, width: int) -> str:
    """按显示宽度右侧补空格（超宽时截断并保留省略号）。"""
    value = str(text)
    while display_width(value) > width and len(value) > 1:
        value = value[:-1]
    if display_width(value) > width:
        value = ""
    return value + " " * max(0, width - display_width(value))


def render_shelf_table(books: list[ShelfBook]) -> str:
    """把书架条目渲染成中文对齐表格（书名/章节数/更新时间/文件数 + id）。

    Args:
        books: Shelf.list() 的结果。

    Returns:
        多行字符串（含表头与分隔线）。
    """
    headers = ("书名", "章节数", "更新时间", "文件数", "ID")
    rows: list[list[str]] = []
    for book in books:
        rows.append([
            book.title or "(无标题)",
            str(len(book.chapter_urls or [])),
            book.updated_at or book.downloaded_at or "-",
            str(len(book.files or [])),
            book.id,
        ])
    widths = [display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))
    lines = ["  ".join(_pad(h, w) for h, w in zip(headers, widths, strict=True)).rstrip(),
             "  ".join("-" * w for w in widths)]
    for row in rows:
        lines.append("  ".join(_pad(c, w) for c, w in zip(row, widths, strict=True)).rstrip())
    return NL.join(lines)


def cmd_shelf(args: argparse.Namespace) -> int:
    """shelf 子命令：list / remove <id> / update [--id <id> | --all]。

    Args:
        args: 已解析参数。

    Returns:
        0 成功；1 业务失败；2 用法错误。
    """
    action = str(getattr(args, "action", None) or "list")
    shelf = make_shelf()

    if action == "list":
        books = shelf.list()
        if not books:
            echo("📚 书架为空 → 先下载一本：zhihu-downloader download --url <链接>")
            return 0
        echo(f"📚 我的书架（{len(books)} 本）")
        echo(render_shelf_table(books))
        return 0

    if action == "remove":
        book_id = str(getattr(args, "book_id", None) or getattr(args, "id", None) or "").strip()
        if not book_id:
            return usage_fail("remove 需要指定书架 id：zhihu-downloader shelf remove <id>（id 见 shelf list）")
        book = shelf.get(book_id)  # remove 前取 url：prune 按书键（专栏 URL）定位断点桶
        if shelf.remove(book_id):
            echo(f"✅ 已从书架移除 {book_id}（已导出的文件保留在磁盘，不会被删除）")
            # M4 接线（镜像 server DELETE /api/shelf 语义）：成功后显式 prune 断点缓存；
            # 磁盘垃圾不阻塞书架操作，失败只 warn 给人工出路。
            if book is not None and book.url:
                from .engine.checkpoint import CheckpointStore  # noqa: PLC0415 - 懒 import 契约
                from .engine.fetcher import DEFAULT_STATE_SUBDIR  # noqa: PLC0415
                out_dir = str(getattr(args, "output_dir", None) or DEFAULT_OUTPUT_DIR)
                state_dir = Path(out_dir) / DEFAULT_STATE_SUBDIR
                try:
                    CheckpointStore(state_dir, book_key=book.url).prune()
                    echo("   断点缓存已一并清理（" + str(state_dir) + "）")
                except Exception as exc:  # noqa: BLE001 - 只兜 SaltError 不够：prune
                    # 内部是 unlink，只读挂载/EACCES/Windows 文件占用抛的是 OSError，
                    # 会在这次**已成功**的移除后面甩 traceback，反噬主语义。
                    warn(f"已从书架移除，但断点 prune 失败：{exc} → 可手工删 {state_dir}")
            return 0
        return fail(f"书架里没有 id={book_id} 的条目 → 先运行 zhihu-downloader shelf list 查看")

    if action == "update":
        return _shelf_update(shelf, args)

    return fail(f"未知的 shelf 操作：{action}（可用：list / remove / update）")


def _shelf_update(shelf: Shelf, args: argparse.Namespace) -> int:
    """追更：resolve_book -> download_book(meta=) -> shelf.record_download（目录页只抓一次）。

    单本失败不中断其余（与批量下载一致的容错语义），最后汇总。

    Args:
        shelf: 书架实例。
        args: 已解析参数（id / all / format / output_dir / rate_limit / workers）。

    Returns:
        0 全部成功；1 至少一本失败。
    """
    want_all = bool(getattr(args, "all", False))
    only_id = str(getattr(args, "id", None) or "").strip()
    if not want_all and not only_id:
        return usage_fail("请指定 --id <书架id> 或 --all（id 见 zhihu-downloader shelf list）")

    if want_all:
        books = shelf.list()
        if not books:
            echo("📚 书架为空，无需追更 → 先运行 zhihu-downloader download --url <链接>")
            return 0
    else:
        target = shelf.get(only_id)
        if target is None:
            return fail(f"书架里没有 id={only_id} 的条目 → 先运行 zhihu-downloader shelf list 查看")
        books = [target]

    rate_limit, workers = resolve_limits(args)
    client = make_client(rate_limit=rate_limit, cookie_file=getattr(args, "cookie_file", None))
    output_dir = getattr(args, "output_dir", None) or DEFAULT_OUTPUT_DIR

    updated = 0
    latest = 0
    failures: list[tuple[str, str]] = []
    for book in books:
        fmt = str(getattr(args, "format", None) or book.fmt or "md")
        known = list(book.chapter_urls or [])
        # 标准记账通路：目录页整轮只抓这一次，同一份 meta 交给 download_book 复用。
        # 与 server 的 shelf_update 同实现（含 check_new_chapters 的 diff 语义）。
        try:
            meta = resolve_book(client, book.url)
        except Exception as exc:  # noqa: BLE001 - 分类由 explain_failure 负责，这里只保证不中断其余
            reason = explain_failure(exc)
            failures.append((book.title or book.id, reason))
            note(f"❌ 检查更新失败：《{book.title or book.id}》→ {reason}")
            continue
        news = diff_new_chapters(meta, known)
        if not news:
            latest += 1
            echo(f"✅ 《{book.title}》已是最新（{len(known)} 章）")
            continue
        echo(f"🆕 《{book.title}》发现 {len(news)} 章更新，开始下载并整本重导出……")
        printer = ProgressPrinter()
        try:
            result = download_book(
                client, book.url, fmt=fmt, output_dir=output_dir,
                progress=printer, resume=True, workers=workers, meta=meta,
            )
        except Exception as exc:  # noqa: BLE001 - 分类由 explain_failure 负责，单本失败不中断其余
            _record_failure("《" + (book.title or book.id) + "》", exc, printer, failures,
                            what="追更失败")
            continue
        printer.finish()
        try:
            shelf.record_download(result, fmt, chapter_urls=[ch.url for ch in meta.chapters])
        except SaltError as exc:
            warn(f"文件已导出，但书架条目更新失败：{exc}")
        updated += 1
        echo(f"✅ 《{result.title}》追更完成（现共 {result.chapters} 章）")
        for path in result.files:
            echo(f"   📄 {path}")

    echo("")
    echo(f"📊 追更汇总：更新 {updated} 本 / 已最新 {latest} 本 / 失败 {len(failures)} 本")
    for title, reason in failures:
        echo(f"   ❌ {title} → {reason}")
    return 0 if not failures else 1


# ----------------------------------------------------------------------
# doctor
# ----------------------------------------------------------------------
def cmd_doctor(args: argparse.Namespace) -> int:
    """doctor 子命令：渲染 auth.doctor 的诊断清单 + 一行新版本提示。

    退出码语义同 v4：有 error 级检查项 -> 1（汇总行走 stderr，便于脚本判定）；
    只有警告/正常 -> 0。无 Cookie 属首次使用的正常状态，只告警不报错。

    Args:
        args: 已解析参数（no_network / cookie_file / no_update_check）。

    Returns:
        0 健康或仅警告；1 存在错误。
    """
    try:
        results = doctor.run_checks(
            cookie_file=getattr(args, "cookie_file", None),
            network=not bool(getattr(args, "no_network", False)),
        )
    except SaltError as exc:  # pragma: no cover - run_checks 内部已兜异常
        return fail(str(exc))

    echo(doctor.format_checks(results))
    if not bool(getattr(args, "no_update_check", False)):
        hint = release_hint()
        if hint:
            echo(hint)

    summary = doctor.summary_line(results)
    if doctor.has_errors(results):
        warn(summary + "（exit 1）")
        return 1
    echo(summary)
    return 0


# ----------------------------------------------------------------------
# gui
# ----------------------------------------------------------------------
def cmd_gui(args: argparse.Namespace) -> int:
    """gui 子命令：起本地 Web 服务 + 自动开浏览器（§2.15 双击即用的入口）。

    要点：

    - app.server 在**函数内**懒 import，CLI 其余子命令不依赖 Web 层；
    - 端口被占自动 +1 重试 3 次，浏览器打开的是实际端口；
    - 非回环 host 打印安全告警：本服务无账号体系，能连上端口的程序等同本机使用者
      （可发起下载、改删 Cookie、并以本机为跳板访问内网）。S1 的来源校验
      （server.check_origin）只挡浏览器发起的跨站写请求，措辞按它的真实覆盖面写，
      既不写"无鉴权"也不写"只接受本机请求"；理由见下面 warn 处的注释。

    Args:
        args: 已解析参数（host / port / no_browser / no_update_check）。

    Returns:
        0 正常退出（含 Ctrl+C）；1 启动失败。
    """
    host = str(getattr(args, "host", None) or GUI_DEFAULT_HOST)
    port = int(getattr(args, "port", GUI_DEFAULT_PORT) or GUI_DEFAULT_PORT)

    if not bool(getattr(args, "no_update_check", False)):
        hint = release_hint()
        if hint:
            echo(hint)

    if not is_loopback(host):
        # 四条后果照 R2 建议稿写全；并按 S1 **已落地**的 server.check_origin 的真实边界
        # 说明它挡得住什么：只挂 POST/DELETE、Origin 与 Referer 两个头都缺即放行、GET 完全
        # 不设防。所以既不能写"无鉴权"（对浏览器跨站已不成立），也不能写"仅校验请求来自
        # 本机"（对不带来源头的脚本不成立）——两头都是过度承诺，都会随下一次加固失实。
        # 改这段文案之前请先读 check_origin，措辞跟着它的覆盖面走。
        warn("安全告警：监听地址 " + host + " 不是回环地址，局域网内任何设备都能："
             "① 发起下载（花你的知乎配额、写你的硬盘）；② 拉走你已导出的全部文件；"
             "③ 覆盖或清除你的登录 Cookie；④ 借本工具访问你内网里的其它服务（路由器"
             "后台、云主机 metadata、只监听了本机的端口）。本服务无账号体系；写接口只挡"
             "来自浏览器的跨站请求，不带来源头的脚本连接与全部读取接口都不在其内 —— "
             "能连上这个端口的程序，就等同于本机使用者。请只在可信网络这样开；"
             "只想本机用请加 --host 127.0.0.1")

    try:
        from .app.server import create_app  # noqa: PLC0415 - §2.15：函数内懒 import
    except Exception as exc:  # noqa: BLE001 - Web 层缺失/损坏时给出可操作的中文提示
        return fail(f"无法加载 Web 服务模块（{type(exc).__name__}: {exc}）"
                    " → 请重新安装：pip install -U zhihu-salt-novel-downloader；"
                    "或先用命令行下载：zhihu-downloader download --url <链接>")
    try:
        app = create_app()
    except SaltError as exc:
        return fail(explain_failure(exc))
    except Exception as exc:  # noqa: BLE001
        return fail(f"Web 服务初始化失败（{type(exc).__name__}: {exc}）"
                    " → 运行 zhihu-downloader doctor 排查环境")

    actual = find_free_port(host, port)
    if actual is None:
        return fail(f"端口 {port} 到 {port + GUI_PORT_RETRIES} 都被占用"
                    " → 请用 --port 指定一个空闲端口（例如 --port 8080）")
    if actual != port:
        warn(f"端口 {port} 已被占用，自动改用 {actual}")

    url = f"http://{display_host(host)}:{actual}"
    echo("=" * 58)
    echo(f"🚀 知乎盐选小说下载器 v{__version__} —— 本地 Web 界面")
    echo(f"   📚 Web 界面: {url}")
    echo("   ⏹  按 Ctrl+C 停止服务")
    echo("=" * 58)

    if not bool(getattr(args, "no_browser", False)):
        open_browser_later(url)
    try:
        serve_app(app, host, actual)
    except KeyboardInterrupt:
        note(NL + "已停止 Web 服务")
        return 0
    except OSError as exc:
        # 探测空闲却绑定失败 = 上面那段 TOCTOU 窗口被踩中了；给出可操作的下一步。
        return fail(f"端口 {actual} 刚探测可用却绑定失败（可能在这瞬间被其他进程抢占）："
                    f"{exc} → 请换端口重试（例如 --port 8080）")
    return 0


# ----------------------------------------------------------------------
# 参数解析
# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """构造 argparse 解析器（中文 help；子命令清单见规格 §2.15）。"""
    parser = argparse.ArgumentParser(
        prog="zhihu-downloader",
        description="知乎盐选小说下载器 v" + __version__
                    + " —— 扫码登录 / 整本下载 / 断点续传 / EPUB 精排 / 书架追更。"
                    + "不带任何参数直接运行即启动图形界面（双击即用）。",
        epilog="示例：\n"
               "  zhihu-downloader login                     # 扫码登录\n"
               "  zhihu-downloader login --browser           # 从浏览器导入 Cookie\n"
               "  zhihu-downloader download --url <链接> -f epub -o ./output\n"
               "  zhihu-downloader download --batch-file urls.txt --rate-limit 1\n"
               "  zhihu-downloader shelf list                # 看书架\n"
               "  zhihu-downloader shelf update --all        # 全部追更\n"
               "  zhihu-downloader doctor --no-network       # 离线自检\n"
               "\n退出码：0 成功 / 1 业务失败 / 2 用法错误（参数不对）/ 130 用户取消（Ctrl+C）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version",
        version="zhihu-downloader " + __version__,
        help="显示版本号并退出（版本号唯一来源：zhihu_downloader.__version__）",
    )
    sub = parser.add_subparsers(dest="command", metavar="<命令>")

    p_login = sub.add_parser("login", help="登录：扫码（默认）或从浏览器导入 Cookie")
    p_login.add_argument("--browser", action="store_true",
                         help="不扫码，改为从本机浏览器（Chrome/Firefox/Edge）导入知乎 Cookie")
    p_login.add_argument("--cookie-file", default=None, metavar="F",
                         help="Cookie 文件路径（默认 ~/.zhihu_downloader/cookies.json，0600）")

    p_download = sub.add_parser("download", help="下载章节/专栏并导出 txt / md / epub")
    p_download.add_argument("--url", "-u", default=None, metavar="U",
                            help="知乎盐选链接（章节或专栏均可；仅 APP 内阅读的内容会给出替换链接建议）")
    p_download.add_argument("-f", "--format", default="md", choices=list(FORMATS),
                            help="导出格式（默认 md）")
    p_download.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, metavar="DIR",
                            help="输出目录（默认 " + DEFAULT_OUTPUT_DIR + "，断点写在其下 .zhihu_state/）")
    p_download.add_argument("--no-resume", action="store_true",
                            help="忽略断点从头下载（默认自动续传已完成的章节）")
    p_download.add_argument("--rate-limit", type=float, default=DEFAULT_RATE_LIMIT, metavar="R",
                            help=f"每秒请求数上限（默认 {DEFAULT_RATE_LIMIT}，钳制到 {MIN_RATE_LIMIT}~{MAX_RATE_LIMIT}）。"
                                 "限速锁是 session 级、HTTP 串行，整本吞吐上限就由这个值决定")
    p_download.add_argument("--workers", type=int, default=DEFAULT_WORKERS, metavar="N",
                            help=f"并行解析数（默认 {DEFAULT_WORKERS}，钳制到 {MIN_WORKERS}~{MAX_WORKERS}）。"
                                 "只影响解析/渲染的并行度，HTTP 仍被限速串行化，调大不会成倍提速")
    p_download.add_argument("--batch-file", default=None, metavar="F",
                            help="批量清单文件：每行一个 URL（# 开头为注释）；单本失败不中断其余")
    p_download.add_argument("--cookie-file", default=None, metavar="F",
                            help="Cookie 文件路径（默认 ~/.zhihu_downloader/cookies.json）")

    p_shelf = sub.add_parser("shelf", help="书架管理：list / remove <id> / update")
    p_shelf.add_argument("action", nargs="?", default="list",
                         choices=["list", "remove", "update"],
                         help="操作（默认 list）")
    p_shelf.add_argument("book_id", nargs="?", default=None, metavar="ID",
                         help="remove 时的书架 id（见 shelf list）")
    p_shelf.add_argument("--id", default=None, metavar="ID",
                         help="update 时只追更这一本（书架 id 或链接）")
    p_shelf.add_argument("--all", action="store_true", help="update 时追更书架上全部书籍")
    p_shelf.add_argument("-f", "--format", default=None, choices=list(FORMATS),
                         help="追更时的导出格式（默认沿用该书上次格式）")
    p_shelf.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR, metavar="DIR",
                         help="追更导出目录（默认 " + DEFAULT_OUTPUT_DIR + "）")
    p_shelf.add_argument("--rate-limit", type=float, default=DEFAULT_RATE_LIMIT, metavar="R",
                         help=f"每秒请求数上限（默认 {DEFAULT_RATE_LIMIT}，钳制到 "
                              f"{MIN_RATE_LIMIT}~{MAX_RATE_LIMIT}；整本吞吐上限由此决定）")
    p_shelf.add_argument("--workers", type=int, default=DEFAULT_WORKERS, metavar="N",
                         help=f"并行解析数（默认 {DEFAULT_WORKERS}，钳制到 "
                              f"{MIN_WORKERS}~{MAX_WORKERS}；调大不成倍提速）")
    p_shelf.add_argument("--cookie-file", default=None, metavar="F", help="Cookie 文件路径")

    p_doctor = sub.add_parser("doctor", help="环境自检：Cookie / 签名 / 限速 / 网络 / 新版本")
    p_doctor.add_argument("--no-network", action="store_true", help="跳过网络探测（离线环境用）")
    p_doctor.add_argument("--cookie-file", default=None, metavar="F",
                          help="指定 Cookie 文件（默认 ~/.zhihu_downloader/cookies.json）")
    p_doctor.add_argument("--no-update-check", action="store_true",
                          help="跳过新版本检查（离线/CI 环境用）")

    p_gui = sub.add_parser("gui", help="启动本地 Web 界面并自动打开浏览器（无参数时的默认行为）")
    p_gui.add_argument("--host", default=GUI_DEFAULT_HOST, metavar="H",
                       help=f"监听地址（默认 {GUI_DEFAULT_HOST}；非回环地址会打印安全告警）")
    p_gui.add_argument("--port", type=int, default=GUI_DEFAULT_PORT, metavar="P",
                       help=f"监听端口（默认 {GUI_DEFAULT_PORT}，被占用时自动 +1 重试 "
                            f"{GUI_PORT_RETRIES} 次）")
    p_gui.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p_gui.add_argument("--no-update-check", action="store_true", help="跳过新版本检查")

    return parser


_HANDLERS: dict[str, str] = {
    "login": "cmd_login",
    "download": "cmd_download",
    "shelf": "cmd_shelf",
    "doctor": "cmd_doctor",
    "gui": "cmd_gui",
}


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。

    Args:
        argv: 参数列表（不含程序名）；None 时取 sys.argv[1:]。

    Returns:
        进程退出码：0 成功；1 业务失败；2 用法错误；130 用户取消。
    """
    ensure_utf8_streams()
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        # 双击即用（§2.15）：无任何参数等价于 gui；已给子命令时不触发。
        argv = ["gui"]
    args = parser.parse_args(argv)

    name = _HANDLERS.get(str(args.command or ""))
    if name is None:
        parser.print_help(sys.stderr)
        return 2
    handler: Callable[[argparse.Namespace], int] = globals()[name]
    try:
        result = handler(args)
        return 0 if result is None else int(result)  # 处理函数漏写 return 也不能崩
    except KeyboardInterrupt:
        note(NL + "已取消（Ctrl+C）")
        return 130
    except SaltError as exc:  # 漏到最上层的业务错误：同样只给一行中文 + 下一步
        return fail(explain_failure(exc))
    except Exception as exc:  # noqa: BLE001 - 绝不把 traceback 甩到双击即用的窗口上
        return fail(explain_failure(exc) + "；可运行 zhihu-downloader doctor 自检")


if __name__ == "__main__":
    raise SystemExit(main())
