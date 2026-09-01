"""FastAPI Web 服务（规格书 §2.14）——本地单用户 GUI 后端。

v5 重构教训与安全承诺（逐条落实，均有对应测试见 tests/test_server.py）：

- 工厂模式：唯一入口 create_app，模块底部没有 'app = create_app()'
  （v4 教训：import 即实例化，测试与打包全被拖下水）。uvicorn 用工厂方式启动：
  'uvicorn zhihu_downloader.app.server:create_app --factory --host 127.0.0.1'；
- 每任务独立客户端：下载/追更任务一律 client.copy_with() 派生新 ZhihuClient
  （各自持有独立 requests.Session），杜绝 v4 的跨任务 session 竞态；
- SSRF 防护（R2#P0-2 收紧）：POST /api/download 服务端校验——原始串含反斜杠
  或 @ 一律硬拒（解析差分 PoC：「http://127.0.0.1:9501 + 反斜杠 +
  @www.zhihu.com」在 urlparse 的 hostname 眼里是知乎域、urllib3 实际连
  127.0.0.1）；scheme 必须 http/https；host 再用 urllib3.util.parse_url
  （与真正发请求的栈同解析器）提取，必须严格等于 zhihu.com 或以
  .zhihu.com 结尾；仿冒域（zhihu.com.evil.co）、协议注入、userinfo 注入、
  IP 直连等一律 400 中文错误。引擎侧 client.fetch 每跳（含首跳）请求后
  还会复校验响应最终 URL（见 engine/client.py）；
- CSRF-lite（R2#P0-3）：本地服务零鉴权，但浏览器可从任意站点向本机端口发
  「简单请求」（不触发 CORS 预检）。所有 POST/DELETE /api/* 挂 check_origin
  依赖：带 Origin 或 Referer 头时，其 host 必须是 127.0.0.1 / localhost /
  ::1（端口不限，GUI 端口会自动 +1），否则 403 中文；无 Origin/Referer
  （curl/CLI/测试）放行；GET 是无副作用的读接口（Cookie 只回布尔）不查；
- 攻击面收敛（R2#P0-3）：docs / redoc / openapi.json 全部关闭；所有响应带
  安全头（CSP default-src 'none'，img-src 放行知乎域供二维码直连；
  X-Content-Type-Options: nosniff；X-Frame-Options: DENY），未显式声明
  Cache-Control 的响应（静态资源、Cookie 状态页等）补 no-store 防缓存；
- 写接口速率粗限：同 URL 未终态任务 400 之外，未终态任务总数 ≥
  MAX_CONCURRENT_TASKS×4 时 429 中文（R2#P0-3）；
- 书架追更入口显式过闸（R2#6）：POST /api/shelf/{id}/update 对磁盘来的
  book.url 先过 is_zhihu_url、book.fmt 先过 FORMATS 白名单，才允许
  resolve_book 发请求（不依赖 detect() 兜底）；数据异常 400 中文并提示
  "数据异常请清理书架"，GET /api/shelf 读侧对异常条目加 data_anomaly 标记
  而非 500；
- 文件下载防穿越：GET /api/files/{task_id}/{filename} 只在任务成功时登记的
  文件名白名单里做精确查表，绝不拼接用户传入的路径；
- Cookie 永不回传：GET /api/cookies 只返回布尔（has_cookie/z_c0/zse_ck/d_c0）；
- 任务表 LRU：OrderedDict + Lock，上限 TASK_LIMIT（50），只淘汰已终态任务并记日志；
- 下载执行：ThreadPoolExecutor(max_workers=2) 在 create_app 内懒创建，
  任务内章节并发由 fetcher workers（默认 3）控制。

SSE 协议：每事件一行 'data: ' + ProgressEvent.to_dict() 的 JSON + 空行；
任务终态且本连接游标追平事件日志后补发 'data: [DONE]' 并关流。
M3（R1 审查）广播模型：Task 持事件日志（deque，上限 EVENT_LOG_MAX，超出丢
最旧）+ 每连接独立游标，先重放历史再跟读增量——双标签页/刷新重连各见全量，
不再 destructive get 分食；日志截断时游标跳过缺口，绝不挂死。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from urllib3.util import parse_url as _urllib3_parse_url

from .. import __version__
from ..auth import cookies as cookie_store
from ..auth import doctor, qr
from ..engine.checkpoint import CheckpointStore
from ..engine.client import ZhihuClient
from ..engine.fetcher import DEFAULT_STATE_SUBDIR, download_book, resolve_book
from ..errors import CheckpointError, SaltError
from ..export import FORMATS
from ..shelf.shelf import Shelf
from ..types import BookMeta, ProgressEvent

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "EVENT_LOG_MAX",
    "MAX_CONCURRENT_TASKS",
    "ACTIVE_TASK_QUEUE_FACTOR",
    "TASK_LIMIT",
    "Task",
    "TaskStore",
    "check_origin",
    "create_app",
    "is_zhihu_url",
    "serve",
]

#: 任务表上限（规格书 §2.14：LRU 上限 50，只淘汰已终态任务）。
TASK_LIMIT = 50

#: 同时执行的下载任务数（规格书 §2.14：ThreadPoolExecutor(max_workers=2)）。
MAX_CONCURRENT_TASKS = 2

#: 未终态任务总数的软上限系数（R2#P0-3 速率粗限：
#: 未终态任务数 ≥ MAX_CONCURRENT_TASKS × 本系数时，写接口一律 429 中文）。
ACTIVE_TASK_QUEUE_FACTOR = 4

#: 单任务内章节并发数（fetcher workers 默认值）。
DEFAULT_TASK_WORKERS = 3

#: GUI 默认输出目录（规格书 §3 用户状态布局）。
DEFAULT_OUTPUT_DIR = Path.home() / ".zhihu_downloader" / "output"

#: 静态 UI 目录（与 server.py 同级的 static/；PyInstaller datas 场景同路径成立）。
STATIC_DIR = Path(__file__).parent / "static"

#: SSE 生成器轮询事件日志的间隔（秒）：兼顾 [DONE] 收尾延迟与空转开销。
SSE_POLL_SECONDS = 0.2

#: M3（R1 审查）：每任务 SSE 事件日志上限（条）。超出丢最旧；连接游标重放
#: 时跳过缺口继续跟读（进度事件幂等、终态事件必在尾部，丢最旧不影响正确性）。
EVENT_LOG_MAX = 500

#: 服务端接受的限速区间——与 doctor/CLI 同一单源（D1 发现 20 与红线①"合理区间 0.5~5"
#: 双承诺冲突：GUI 不得成为绕开平台友好承诺的后门；下限 0.5 同时消灭"0=不限速"通道）。
MAX_RATE_LIMIT = doctor.MAX_RATE_LIMIT  # 5.0，单源在 doctor
MIN_RATE_LIMIT = doctor.MIN_RATE_LIMIT  # 0.5，对齐 CLI 钳制

#: 任务工作子目录（output_dir 之下，按书键 sha1(url)[:16] 分桶）。
#: 跨书并发缓存竞态引擎已在追加轮修复（内存优先导出 + 唯一 tmp 名 + clear
#: 引用感知）；server 保留每本书独立工作目录作为纵深防御：不同任务天然隔离，
#: 成功后把导出文件挪回 output_dir 根并整目录清理，失败保留断点
#: （目录按 URL 稳定，同 URL 断点续传跨重启可用）。
TASK_RUN_SUBDIR = ".zhihu_tasks"

#: SSE 行分隔符。用 chr(10) 而不是字面转义，避免源码里出现反斜杠序列。
_NL = chr(10)

#: 反斜杠字面量。同理用 chr(92)（与 engine/client.py 的写法约定一致）：
#: 它既是 R2#P0-2 解析差分载荷的特征字符，也是路径分隔符检查所需。
_BS = chr(92)

#: R2#P0-3：写请求 Origin/Referer 允许的主机集合（端口不限——GUI 端口自动 +1）。
_ALLOWED_ORIGIN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: R2#P0-3：全站 CSP。img-src 放行知乎域：扫码登录的二维码 image_url 指向
#: https://www.zhihu.com（见 auth/qr.py 的 IMAGE_URL），前端 <img> 直连加载
#: （app.js renderQr），直连失败才回退本机代理端点（'self'）；data: 留给
#: 内联图片兜底。其余一律同源：脚本/样式只有 static/ 下的本地文件，无内联。
_CSP_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "img-src 'self' data: https://www.zhihu.com https://*.zhihu.com; "
    "style-src 'self'; "
    "connect-src 'self'"
)


# ----------------------------------------------------------------------
# 安全校验
# ----------------------------------------------------------------------

def is_zhihu_url(url: str) -> bool:
    """URL 是否严格属于知乎域（SSRF 防护的唯一放行判据，R2#P0-2 收紧）。

    三道闸门，缺一不可：

    1. 原始串硬拒反斜杠与 @：urlparse 与 urllib3 对
       「http://127.0.0.1:9501 + 反斜杠 + @www.zhihu.com/...」的解析存在
       差分——urlparse().hostname 是 www.zhihu.com（闸门放行），urllib3
       实际连的却是 127.0.0.1:9501。知乎正规链接不需要这两个字符出现在
       authority，索性整串硬拒，杜绝差分绕过；userinfo 注入
       （http://zhihu.com@evil.com）也一并挡掉。
    2. scheme 必须 http/https：javascript:、file: 等协议注入拒绝。
    3. host 用 urllib3.util.parse_url 提取——与真正发请求的栈同解析器，
       闸门判断和实际连接目标不再有两套语义；host 为 None 或解析抛异常
       一律拒绝。仿冒域（zhihu.com.evil.co）、IP 直连、空 host 拒绝。

    Args:
        url: 用户提交的链接。

    Returns:
        属于知乎域返回 True，否则 False。
    """
    raw = str(url)
    # 闸门 1：反斜杠 / @ 硬拒（解析差分 + userinfo 注入双载荷特征）。
    if _BS in raw or "@" in raw:
        return False
    # 闸门 2：scheme 白名单（urlparse 只用于取 scheme，不再信它的 hostname）。
    try:
        scheme = (urlparse(raw).scheme or "").lower()
    except ValueError:  # 极端畸形 URL（如非法 IPv6 字面量）
        return False
    if scheme not in ("http", "https"):
        return False
    # 闸门 3：urllib3 同栈解析取 host。
    try:
        host = (_urllib3_parse_url(raw).host or "").lower()
    except Exception:  # LocationParseError 等：无法可靠解析 = 不放行
        return False
    if not host:
        return False
    return host == "zhihu.com" or host.endswith(".zhihu.com")


def _origin_host_allowed(value: str) -> bool:
    """Origin/Referer 头的值是否指向本机回环（端口不限，scheme 必须 http/https）。"""
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return False
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in _ALLOWED_ORIGIN_HOSTS


def check_origin(request: Request) -> None:
    """FastAPI 依赖：写接口（POST/DELETE /api/*）的 Origin/Referer 校验（R2#P0-3）。

    背景：本服务零鉴权、纯本机使用，但任何网页上的 JS 都能向
    http://127.0.0.1:<port> 发起「简单请求」（form POST 不触发 CORS 预检），
    借用户本机身份发起下载任务、导入 Cookie、发起扫码登录。CSRF-lite 缓解：

    - 请求带 Origin 或 Referer 头时，其 host 必须 ∈ {127.0.0.1, localhost,
      ::1}（端口不限——GUI 端口被占会自动 +1），否则 403 中文；
    - 两个头都没有（curl / CLI / 离线测试客户端）放行——跨站表单请求在
      现代浏览器必然带 Origin，缺失只可能是本机非浏览器调用；
    - GET 不挂本依赖：读接口无副作用、不回传 Cookie 值，无需拦截。
    """
    if request.method not in ("POST", "DELETE"):
        return
    source = request.headers.get("origin") or request.headers.get("referer")
    if source is None:
        return
    if not _origin_host_allowed(source):
        raise HTTPException(
            status_code=403,
            detail="跨站请求已拒绝：本服务只接受来自本机（127.0.0.1 / localhost / ::1）"
                   "的写操作。若你正从其它站点打开本页面，请改用本机地址访问。")


def _task_run_dir(output_dir: Path, url: str) -> Path:
    """按书键给任务分配稳定且互不重叠的工作目录（断点续传与隔离两全）。"""
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return Path(output_dir) / TASK_RUN_SUBDIR / key


def _user_error_message(exc: SaltError, resume: bool) -> str:
    """任务失败消息映射（E1 对接契约）：中文消息原样透传。

    CheckpointError 且用户开了续传时，按引擎约定在末尾追加"或关闭续传重试"——
    引擎消息给的是 --no-resume CLI 指引，GUI 用户能操作的是取消勾选"续传"。
    """
    message = str(exc)
    if resume and isinstance(exc, CheckpointError):
        message += "或关闭续传重试。"
    return message


def _relocate_outputs(files: list[str], output_dir: Path,
                      task_id: str = "") -> list[str]:
    """把任务工作目录里的导出文件移动到 output_dir 根。

    m3（R1 审查）：两本不同书 safe_filename 相同时，旧「同名覆盖」会让后者
    删掉前者产物（双方 files 登记同一路径）。现在目标已存在且属于别的任务
    → 文件名追加 "-<task_id 前 6 位>" 防撞，登记实际落盘名；同一任务重跑
    （同 id 撞自己）仍保留覆盖语义（追更整本重导出要替换旧产物）。

    Returns:
        移动后的最终路径；个别文件移动失败时保留原路径（记录日志不抛，
        调用方据此判断工作目录是否还有残留，见 m2）。
    """
    moved: list[str] = []
    for raw in files:
        src = Path(raw)
        dest = Path(output_dir) / src.name
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and not dest.samefile(src):
                if task_id:
                    dest = dest.with_name(
                        dest.stem + "-" + task_id[:6] + dest.suffix)
                    logger.info("导出目标名已被占用（并发同名书），防撞改名：%s",
                                dest.name)
                if dest.exists():
                    dest.unlink()  # 同任务重跑撞自己：覆盖（追更重导出语义）
            shutil.move(str(src), str(dest))
            moved.append(str(dest))
        except OSError:
            logger.exception("导出文件移动到 %s 失败，保留原位置：%s", dest, src)
            moved.append(str(src))
    return moved


def _dir_has_files(root: Path) -> bool:
    """root 下是否仍残留任何普通文件（空目录不算；m2 清理判定用）。"""
    try:
        return any(p.is_file() for p in root.rglob("*"))
    except OSError:  # pragma: no cover - 扫描中途目录消失
        return False


def _is_loopback(host: str) -> bool:
    """host 是否回环地址（非回环启动告警判定用，规格 §2.14 安全条目）。"""
    h = (host or "").strip().lower()
    return h in ("localhost", "::1") or h.startswith("127.")


# ----------------------------------------------------------------------
# 任务模型与任务表
# ----------------------------------------------------------------------

@dataclass
class Task:
    """一次下载/追更任务的内存记录。

    线程模型：worker 线程写（进度/终态），HTTP 线程读（详情/SSE/文件表）。
    标量字段一律经 lock 读写；事件走 M3 广播模型——event_log（deque，上限
    EVENT_LOG_MAX）+ event_seq 绝对序号同锁追加，每个 SSE 连接持独立游标
    重放后跟读，多连接互不分食。
    """

    id: str
    kind: str  # download | shelf_update
    url: str
    fmt: str
    status: str = "pending"  # pending | running | done | error
    title: str = ""
    chapter: str = ""
    current: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    #: 白名单文件名表：导出文件 basename -> 绝对路径（防穿越的唯一事实源）。
    files: dict[str, str] = field(default_factory=dict)
    #: M3：事件日志与绝对序号（同 lock 保护）；deque 超限丢最旧，
    #: 游标=绝对序号，重放时以 base=event_seq-len(log) 换算窗口内下标。
    event_log: deque[ProgressEvent] = field(
        default_factory=lambda: deque(maxlen=EVENT_LOG_MAX))
    event_seq: int = 0
    finished: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    #: 本任务专属的 ZhihuClient（copy_with 派生，绝不与其他任务/base 共享 session）。
    client: Any = field(default=None, repr=False)
    #: 预解析目录（标准记账通路：resolve_book → download_book(meta=) → record_download）。
    meta: BookMeta | None = None
    saw_error_event: bool = False

    def snapshot(self) -> dict[str, Any]:
        """线程安全的详情快照（GET /api/tasks/{id} 与列表共用）。"""
        with self.lock:
            return {
                "task_id": self.id,
                "id": self.id,
                "kind": self.kind,
                "url": self.url,
                "format": self.fmt,
                "status": self.status,
                "title": self.title,
                "error": self.error,
                "message": self.message,
                "created_at": self.created_at,
                "progress": {
                    "current": self.current,
                    "total": self.total,
                    "title": self.chapter,
                },
                "files": list(self.files.values()),
            }


class TaskStore:
    """任务表：OrderedDict + Lock；超上限只淘汰最旧的已终态任务并记日志。"""

    def __init__(self, limit: int = TASK_LIMIT) -> None:
        self.limit = limit
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, task: Task) -> Task:
        """登记新任务，必要时淘汰最旧的已终态任务。"""
        with self._lock:
            self._tasks[task.id] = task
            self._evict_locked()
        return task

    def _evict_locked(self) -> None:
        """按插入顺序（最旧优先）淘汰终态任务；全在运行则暂不淘汰。"""
        while len(self._tasks) > self.limit:
            victim_id = next(
                (tid for tid, t in self._tasks.items() if t.finished.is_set()), None)
            if victim_id is None:
                logger.warning(
                    "任务表已超过上限 %d，但全部任务仍在运行，暂不淘汰", self.limit)
                return
            victim = self._tasks.pop(victim_id)
            logger.info(
                "任务表超过上限 %d，已淘汰最旧的终态任务 id=%s status=%s url=%s",
                self.limit, victim_id, victim.status, victim.url)

    def get(self, task_id: str) -> Task | None:
        """按 id 查任务；不存在（含已被淘汰）返回 None。"""
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        """全部任务，新→旧排序。"""
        with self._lock:
            return list(reversed(self._tasks.values()))

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)


class _ServerState:
    """挂在 app.state.zhihu 上的应用级可变状态（测试与 CLI 可复用）。"""

    def __init__(self, client: Any, output_dir: Path, shelf: Shelf) -> None:
        self.client = client
        self.output_dir = output_dir
        self.shelf = shelf
        self.tasks = TaskStore(TASK_LIMIT)
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    def executor(self) -> ThreadPoolExecutor:
        """懒创建下载执行线程池（max_workers=2，规格 §2.14）。"""
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=MAX_CONCURRENT_TASKS,
                    thread_name_prefix="zhihu-task")
            return self._executor

    def shutdown(self) -> None:
        """应用退出时关闭线程池（不等待在跑任务；worker 自身有 finally 收尾）。"""
        with self._executor_lock:
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=False)
                self._executor = None


# ----------------------------------------------------------------------
# 请求体模型
# ----------------------------------------------------------------------

class DownloadRequest(BaseModel):
    """POST /api/download 请求体（UI 会额外带 rate_limit，一并接收并钳制）。"""

    url: str = ""
    format: str = "md"
    resume: bool = True
    rate_limit: float | None = None
    workers: int | None = None


class CookieImportRequest(BaseModel):
    """POST /api/cookies/import 请求体。"""

    raw: str = ""


# ----------------------------------------------------------------------
# Cookie 辅助（只回布尔，绝不回传值）
# ----------------------------------------------------------------------

def _cookie_file_of(client: Any) -> Path:
    """客户端绑定的 Cookie 文件路径（鸭子类型兜底到默认路径）。"""
    path = getattr(client, "cookie_file", None)
    return Path(path) if path else cookie_store.DEFAULT_COOKIE_FILE


def _cookie_flags(path: Path) -> dict[str, bool]:
    """读取 Cookie 并归约为布尔摘要（解析失败视为未登录，不抛）。"""
    data: dict[str, str] = {}
    try:
        if path.exists():
            data = cookie_store.load(path)
    except SaltError:
        data = {}
    return {
        "has_cookie": bool(data),
        "z_c0": bool(data.get("z_c0")),
        "zse_ck": bool(data.get("zse_ck")),
        "d_c0": bool(data.get("d_c0")),
    }


def _clear_client_cookies(client: Any) -> None:
    """尽力清空客户端内存 Cookie。

    登出必须同时清内存：copy_with() 会把 base client 的内存 Cookie 带进派生
    实例，不清的话「登出」之后新任务仍会带着旧登录态出门。
    """
    try:
        lock = getattr(client, "_lock", None)
        cookies = getattr(client, "_cookies", None)
        if lock is not None and cookies is not None:
            with lock:
                cookies.clear()
        elif isinstance(cookies, dict):
            cookies.clear()
        jar = getattr(getattr(client, "session", None), "cookies", None)
        if jar is not None and hasattr(jar, "clear"):
            jar.clear()
    except Exception:  # pragma: no cover - 防御：鸭子类型客户端缺属性
        logger.debug("清空客户端内存 Cookie 失败（已忽略）", exc_info=True)


# ----------------------------------------------------------------------
# 应用工厂（规格书 §2.14）
# ----------------------------------------------------------------------

def create_app(
    client: ZhihuClient | None = None,
    output_dir: str | Path | None = None,
    shelf: Shelf | None = None,
) -> FastAPI:
    """构造 FastAPI 应用（工厂模式：import 本模块不产生任何实例/副作用）。

    Args:
        client: 基础 ZhihuClient；None 时新建默认实例。每个下载任务都会
            copy_with 派生独立实例，绝不共享 session。
        output_dir: 导出目录；None 时用 ~/.zhihu_downloader/output（规格 §3）。
        shelf: 书架实例；None 时用默认 ~/.zhihu_downloader/shelf.json。

    Returns:
        配置好全部路由与静态挂载的 FastAPI 应用。
    """
    base_client = client if client is not None else ZhihuClient()
    state = _ServerState(
        client=base_client,
        output_dir=Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR,
        shelf=shelf if shelf is not None else Shelf(),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        state.shutdown()

    # R2#P0-3：docs / redoc / openapi.json 全部关闭——本机小工具不需要公开
    # 路由清单，少一个信息泄露面（GET /docs 与 /openapi.json 一律 404）。
    app = FastAPI(
        title="知乎盐选小说下载器",
        version=__version__,
        description="本地 Web GUI 后端（规格书 §2.14）。默认只应监听 127.0.0.1。",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.zhihu = state

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        """R2#P0-3：全部响应（含 4xx/5xx 与静态资源）统一加安全头。

        - CSP：default-src 'none' 起步白名单化（见 _CSP_POLICY 注释）；
        - nosniff：禁 MIME 嗅探；X-Frame-Options: DENY：禁一切内嵌框架；
        - Cache-Control：仅对「未显式声明」的响应补 no-store（静态资源与
          Cookie 状态页防缓存）；SSE 端点自带 no-cache 语义，保持不动。
        """
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = _CSP_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(SaltError)
    async def _handle_salt_error(request: Request, exc: SaltError) -> JSONResponse:
        """业务异常统一转 400 + 中文 detail（UI 的 api() 读 data.detail）。"""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # ------------------------------------------------------------------
    # 任务派生与执行
    # ------------------------------------------------------------------

    _start_lock = threading.Lock()  # 「查重 URL → 入表」的原子性

    def make_task_client(rate_limit: float | None) -> Any:
        """为单个任务派生独立客户端（v4 竞态教训：绝不共享 session）。"""
        copy_with = getattr(state.client, "copy_with", None)
        if callable(copy_with):
            try:
                return copy_with(rate_limit=rate_limit)
            except TypeError:  # pragma: no cover - 鸭子类型客户端不支持该参数
                return copy_with()
        keep = getattr(state.client, "rate_limit", 2.0)  # pragma: no cover
        return ZhihuClient(  # pragma: no cover
            cookie_file=getattr(state.client, "cookie_file", None),
            rate_limit=keep if rate_limit is None else rate_limit,
        )

    def make_progress_sink(task: Task) -> Callable[[ProgressEvent], None]:
        """把 fetcher 进度回调接到任务快照 + SSE 事件日志（M3 广播）。"""

        def on_progress(ev: ProgressEvent) -> None:
            with task.lock:
                task.current = ev.current
                task.total = ev.total
                if ev.title:
                    task.chapter = ev.title
                if ev.kind == "toc" and ev.title:
                    task.title = ev.title
                if ev.message:
                    task.message = ev.message
                if ev.kind == "error":
                    task.saw_error_event = True
                # M3：同锁追加日志（SSE 读侧同锁取快照），无破坏性消费
                task.event_log.append(ev)
                task.event_seq += 1

        return on_progress

    def fail_task(task: Task, on_progress: Callable[[ProgressEvent], None],
                  message: str) -> None:
        """置任务为失败终态；fetcher 没发过 error 事件时补发一个（SSE 必有收尾）。"""
        with task.lock:
            task.status = "error"
            task.error = message
            saw = task.saw_error_event
            current, total = task.current, task.total
        if not saw:
            on_progress(ProgressEvent(kind="error", current=current, total=total,
                                      message=message))

    def run_download(task: Task, resume: bool, workers: int) -> None:
        """worker 线程主体：download_book → 登记文件白名单 → shelf.record_download。

        标准记账通路（E1 追加轮定稿，规格 §2.3）：
            meta = resolve_book(client, url)
            → download_book(..., meta=meta)          # 目录页不再重抓
            → shelf.record_download(result, fmt, chapter_urls=[ch.url for ch in meta.chapters])

        Args:
            task: 任务记录（含专属 client 与可选预解析 meta，追更由端点传入）。
            resume: 是否断点续传。
            workers: 任务内章节并发数。
        """
        client = task.client
        on_progress = make_progress_sink(task)
        with task.lock:
            task.status = "running"
        run_dir = _task_run_dir(state.output_dir, task.url)
        try:
            meta = task.meta
            if meta is None:
                try:
                    meta = resolve_book(client, task.url)
                except SaltError:
                    # 预解析失败不阻断下载：download_book(meta=None) 会重解析并给出权威错误。
                    meta = None
            run_dir.mkdir(parents=True, exist_ok=True)
            result = download_book(
                client, task.url, fmt=task.fmt, output_dir=run_dir,
                progress=on_progress, resume=resume, workers=workers,
                meta=meta)
            result.files = _relocate_outputs(result.files, state.output_dir,
                                             task.id)
            with task.lock:
                task.status = "done"
                task.title = result.title or task.title
                task.files = {Path(p).name: str(p) for p in result.files}
                task.message = "完成：" + str(len(result.files)) + " 个文件"
            # m2（R1 审查）：只有工作目录确实空了才删。relocate 部分失败时
            # 产物仍留在 run_dir 内、且 R1-M4 成功后保留断点 state+bodies——
            # 任一情形下有文件就必须保留现场，否则 done 任务的 files 指向
            # 已删路径，/api/files 直接 404。清理入口：书架移除 prune（M4）。
            if _dir_has_files(run_dir):
                logger.info("工作目录仍有保留价值（断点/移动残留），不清理：%s",
                            run_dir)
            else:
                shutil.rmtree(run_dir, ignore_errors=True)
            try:
                chapter_urls = [ch.url for ch in meta.chapters] if meta else None
                # m3 定向清理（主审裁决）：「追更替换旧版」——仅 shelf_update
                # 成功路径，record_download 覆盖登记之前先抓该书旧 files 清单，
                # 登记成功后逐个删除旧产物（路径全部来自书架登记白名单，
                # 不猜路径）；删除失败只中文 warning，绝不影响追更结果。
                # 同 URL 非追更重下（kind=download）不走此路：维持 m3 改名
                # 不覆盖、新旧共存。
                stale_files: list[str] = []
                if task.kind == "shelf_update":
                    prior = state.shelf.get(task.url)
                    if prior is not None:
                        stale_files = [str(p) for p in prior.files]
                state.shelf.record_download(result, task.fmt,
                                            chapter_urls=chapter_urls)
                fresh = set(result.files)
                for stale in stale_files:
                    if stale in fresh:
                        continue  # 新版恰好落在同一路径：不能误删
                    try:
                        Path(stale).unlink(missing_ok=True)
                    except OSError:
                        logger.warning("追更成功，但旧版文件删除失败（仍在，"
                                       "可手动清理）：%s", stale)
            except SaltError:
                # 下载已成功，书架登记失败只记日志，不把任务翻成失败。
                logger.exception("下载成功但书架登记失败（不影响已导出文件）")
        except SaltError as exc:
            fail_task(task, on_progress, _user_error_message(exc, resume))
        except Exception as exc:  # noqa: BLE001 - worker 兜底：绝不静默死亡
            logger.exception("任务 %s 执行异常", task.id)
            fail_task(task, on_progress, "任务异常终止：" + str(exc))
        finally:
            task.finished.set()

    def start_download_task(url: str, fmt: str, resume: bool,
                            rate_limit: float | None, workers: int, kind: str,
                            meta: BookMeta | None = None) -> Task:
        """建任务 → 派生专属 client → 入表 → 提交线程池。

        同一 URL 已有未终态任务时直接 400：重复提交既浪费带宽，两任务还会
        共享按书分桶的工作目录（引擎并发竞态已由 E1 修复，此处为 server 侧
        纵深防御 + 双击去重）。未终态任务总数 ≥ MAX_CONCURRENT_TASKS×4 时
        429 中文（R2#P0-3 速率粗限：LRU 只淘汰终态任务，不设总量闸的话，
        被诱导的页面可反复提交让任务表与线程池队列无界增长）。
        """
        with _start_lock:
            active_tasks = [t for t in state.tasks.list() if not t.finished.is_set()]
            queue_cap = MAX_CONCURRENT_TASKS * ACTIVE_TASK_QUEUE_FACTOR
            if len(active_tasks) >= queue_cap:
                raise HTTPException(
                    status_code=429,
                    detail="进行中的任务过多（已达 " + str(queue_cap) +
                           " 个上限），请等待部分任务完成后再发起。")
            for active in active_tasks:
                if active.url == url:
                    raise HTTPException(
                        status_code=400,
                        detail="该链接已有任务正在进行中（任务 " + active.id +
                               "），请等待其完成后再发起。")
            task = Task(id=uuid.uuid4().hex[:12], kind=kind, url=url, fmt=fmt)
            task.client = make_task_client(rate_limit)
            task.meta = meta
            state.tasks.add(task)
        state.executor().submit(run_download, task, resume, workers)
        return task

    def require_task(task_id: str) -> Task:
        """查任务，不存在/已淘汰 → 404（中文）。"""
        task = state.tasks.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="任务不存在或已被清理（仅保留最近 " + str(state.tasks.limit) +
                       " 条任务），请重新发起下载")
        return task

    # ------------------------------------------------------------------
    # 健康与版本（§2.14：version 单源 __version__）
    # ------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        """存活探测 + 版本单源。"""
        return {"ok": True, "version": __version__}

    # ------------------------------------------------------------------
    # Cookie（只回布尔，绝不回传值）
    # ------------------------------------------------------------------

    @app.get("/api/cookies")
    def cookies_status() -> dict[str, bool]:
        """Cookie 状态布尔摘要：{has_cookie, z_c0, zse_ck, d_c0}，不含任何值。"""
        return _cookie_flags(_cookie_file_of(state.client))

    @app.post("/api/cookies/import", dependencies=[Depends(check_origin)])
    def cookies_import(payload: CookieImportRequest) -> dict[str, Any]:
        """导入原始 Cookie 文本（JSON / Netscape / name=value），0600 落盘。"""
        parsed = cookie_store.parse_content(payload.raw)  # 失败抛 AuthError → 400 中文
        path = cookie_store.save(parsed, _cookie_file_of(state.client))
        loader = getattr(state.client, "load_cookies", None)
        if callable(loader):
            try:
                loader(path)
            except SaltError:
                logger.warning("Cookie 已落盘但加载进客户端失败（后续任务重读文件）")
        return {"ok": True, "saved_to": str(path), **_cookie_flags(path)}

    @app.delete("/api/cookies", dependencies=[Depends(check_origin)])
    def cookies_logout() -> dict[str, bool]:
        """登出：删除 Cookie 文件并清空客户端内存 Cookie。"""
        removed = cookie_store.logout(_cookie_file_of(state.client))
        _clear_client_cookies(state.client)
        return {"ok": True, "removed": removed}

    # ------------------------------------------------------------------
    # 扫码登录（委托 auth.qr，传应用客户端实例）
    # ------------------------------------------------------------------

    @app.post("/api/qrcode", dependencies=[Depends(check_origin)])
    def qrcode_start() -> dict[str, Any]:
        """发起扫码登录：{token, image_url}。"""
        return qr.start(state.client)

    @app.get("/api/qrcode/{token}/image")
    def qrcode_image(token: str) -> Response:
        """二维码图片代理（前端直连知乎失败时回退到本端点）。"""
        data = qr.image(state.client, token)
        return Response(content=data, media_type="image/jpeg")

    @app.get("/api/qrcode/{token}/status")
    def qrcode_status(token: str) -> dict[str, Any]:
        """轮询扫码状态（qr.poll 返回值不含 Cookie 明文，可安全透传）。"""
        return qr.poll(state.client, token)

    # ------------------------------------------------------------------
    # 下载任务 + SSE + 文件
    # ------------------------------------------------------------------

    @app.post("/api/download", dependencies=[Depends(check_origin)])
    def start_download(payload: DownloadRequest) -> dict[str, Any]:
        """创建下载任务（异步执行）。SSRF/格式校验在提交前同步完成。"""
        url = (payload.url or "").strip()
        if not url:
            raise HTTPException(
                status_code=400,
                detail="请先填写知乎链接（例如 https://www.zhihu.com/market/paid_column/…）")
        if not is_zhihu_url(url):
            raise HTTPException(
                status_code=400,
                detail="仅支持知乎链接（zhihu.com 及其子域）。出于安全考虑，"
                       "该地址不属于知乎域，已拒绝。")
        fmt = (payload.format or "md").strip().lower()
        if fmt not in FORMATS:
            raise HTTPException(
                status_code=400,
                detail="不支持的导出格式「" + str(payload.format) + "」，请改用 "
                       + " / ".join(FORMATS) + " 之一")
        rate = payload.rate_limit
        if rate is not None:
            rate = max(MIN_RATE_LIMIT, min(MAX_RATE_LIMIT, float(rate)))
        workers = DEFAULT_TASK_WORKERS
        if payload.workers is not None:
            workers = max(1, min(8, int(payload.workers)))
        task = start_download_task(url, fmt, bool(payload.resume), rate,
                                   workers, kind="download")
        return {"task_id": task.id, "status": task.status}

    @app.get("/api/tasks")
    def tasks_list() -> list:
        """任务摘要列表（新→旧；表内最多 TASK_LIMIT 条）。"""
        return [t.snapshot() for t in state.tasks.list()]

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str) -> dict[str, Any]:
        """任务详情（含 progress {current,total,title} 与 files 列表）。"""
        return require_task(task_id).snapshot()

    @app.get("/api/tasks/{task_id}/events")
    def task_events(task_id: str) -> StreamingResponse:
        """SSE 进度流（M3 广播模型）：独立游标重放+跟读，终态且追平后 [DONE]。

        每条连接从游标 0 起：先重放事件日志（超上限被丢弃的最旧事件跳过），
        再轮询跟读增量；[DONE] 由「任务终态且游标追平日志」推出，而非
        「队列被谁抽干」——两条连接（双标签页/刷新重连）都拿到全量事件。
        """
        task = require_task(task_id)

        def stream() -> Iterator[str]:
            cursor = 0
            while True:
                with task.lock:
                    total = task.event_seq
                    log = list(task.event_log)
                    base = total - len(log)  # 日志仍保留的最旧事件绝对下标
                    if cursor < base:
                        cursor = base        # 截断缺口：跳过已丢弃区间
                    pending = log[cursor - base:]
                    cursor = total
                    finished = task.finished.is_set()
                for ev in pending:
                    yield ("data: " + json.dumps(ev.to_dict(), ensure_ascii=False)
                           + _NL + _NL)
                if finished and not pending:
                    break
                if not pending:
                    time.sleep(SSE_POLL_SECONDS)
            yield "data: [DONE]" + _NL + _NL

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # 反代禁用缓冲（本地默认无代理，防御性带上）
                "X-Accel-Buffering": "no",
            },
        )

    # ------------------------------------------------------------------
    # 文件下载（防穿越：只认任务登记的 basename 白名单）
    # ------------------------------------------------------------------

    @app.get("/api/files/{task_id}/{filename}")
    def download_file(task_id: str, filename: str) -> FileResponse:
        """按任务登记的文件名白名单提供导出文件。

        安全：filename 必须精确命中 task.files 的键（下载成功时登记的
        basename）。查表取值，绝不把用户输入拼进路径，../ 注入天然 404。
        """
        task = require_task(task_id)
        # 纵深防御：URL 解码后带任何路径分隔符的名字一定不在白名单里，提前拒绝
        if "/" in filename or chr(92) in filename:
            raise HTTPException(status_code=404, detail="文件不存在或已被清理，请重新下载")
        path = task.files.get(filename)
        if not path or not Path(path).is_file():
            raise HTTPException(status_code=404, detail="文件不存在或已被清理，请重新下载")
        return FileResponse(path, filename=filename)

    # ------------------------------------------------------------------
    # 书架（§2.14）
    # ------------------------------------------------------------------

    @app.get("/api/shelf")
    def shelf_list() -> list:
        """书架列表（ShelfBook.to_dict() 数组，按 updated_at 新→旧）。

        R2#6：读侧宽容——列表纯展示、零网络副作用，条目链接非知乎域时不 500
        也不静默丢弃，只加 data_anomaly 标记供前端提示清理书架；拦截发生在
        唯一的网络消费入口 shelf_update（写侧严拦）。
        """
        entries = [b.to_dict() for b in state.shelf.list()]
        for entry in entries:
            if not is_zhihu_url(str(entry.get("url") or "")):
                entry["data_anomaly"] = "数据异常请清理书架"
        return entries

    @app.post("/api/shelf/{book_id}/update", dependencies=[Depends(check_origin)])
    def shelf_update(book_id: str) -> dict[str, Any]:
        """追更：check_new_chapters → 有新章则整本重导出（后台任务）→ 更新条目。

        无新章节时同步返回 {updated: false, message}；有新章节时立即返回
        {updated: true, task_id}，进度走 /api/tasks/{task_id}/events（SSE）。

        R2#6：book.url/book.fmt 来自磁盘上的 shelf.json——外部可改写的数据，
        本端点是唯一把「外部 url 带上网络栈」的入口，必须显式过
        is_zhihu_url + FORMATS 白名单：resolve_book 的首跳请求先于域复校验
        发出（反斜杠差分载荷会真连内网端口），不能指望 detect() 的 unknown
        兜底或 start_download_task 里的总闸。数据异常一律 400 中文并提示
        清理书架，绝不让请求发出、也绝不 500。
        """
        book = state.shelf.get(book_id)
        if book is None:
            raise HTTPException(
                status_code=404,
                detail="书架里没有这本书（id=" + book_id + "），请刷新书架后重试")
        url = str(book.url or "")
        if not is_zhihu_url(url):
            raise HTTPException(
                status_code=400,
                detail="书架数据异常请清理书架：该条目链接不属于知乎域或无法安全解析"
                       "（shelf.json 可能被外部改写），已拦截追更请求。"
                       "请移除该条目后用知乎链接重新下载。")
        fmt = (str(book.fmt or "")).strip().lower()
        if fmt not in FORMATS:
            raise HTTPException(
                status_code=400,
                detail="书架数据异常请清理书架：该条目导出格式「" + str(book.fmt) +
                       "」不受支持（可选：" + " / ".join(FORMATS) + "）。")
        checker = make_task_client(None)
        # 标准记账通路：目录页只抓一次——按 §2.3 check_new_chapters 的定义
        # （resolve 后 diff：保持目录顺序、过滤空 known）就地求 diff，
        # 同一份 meta 交给下载任务经 download_book(meta=) 复用，不再重抓目录。
        meta = resolve_book(checker, url)
        known = {u for u in book.chapter_urls if u}
        news = [ch for ch in meta.chapters if ch.url not in known]
        if not news:
            return {"updated": False,
                    "message": "《" + book.title + "》暂无新章节，已是最新"}
        task = start_download_task(url, fmt, True, None, DEFAULT_TASK_WORKERS,
                                   kind="shelf_update", meta=meta)
        return {"updated": True, "task_id": task.id, "new_chapters": len(news)}

    @app.delete("/api/shelf/{book_id}", dependencies=[Depends(check_origin)])
    def shelf_remove(book_id: str) -> dict[str, Any]:
        """移除书架条目（不删已导出的文件）。

        R1-M4 接线：断点改为「成功后保留」，书架移除就是唯一的显式清理入口
        ——移除成功后对该书 CheckpointStore.prune()（state+bodies 一并删，
        幂等）。prune 失败只记日志：条目已移除是主语义，残留断点无害且
        resume 侧对缺失正文可自愈，绝不把 200 翻成 500。
        """
        book = state.shelf.get(book_id)
        removed = state.shelf.remove(book_id)
        if not removed:
            raise HTTPException(
                status_code=404,
                detail="书架里没有这本书（id=" + book_id + "），无需移除")
        if book is not None and book.url:
            try:
                store = CheckpointStore(
                    _task_run_dir(state.output_dir, book.url)
                    / DEFAULT_STATE_SUBDIR,
                    book_key=book.url)
                store.prune()
            except SaltError:
                logger.warning("书架条目已移除，但断点 prune 失败（残留可重删）：%s",
                               book.url)
        return {"ok": True, "removed": True}

    # ------------------------------------------------------------------
    # 静态 UI（兜底路由：先注册上面的 API，再挂 "/"）
    # ------------------------------------------------------------------

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True),
                  name="static")

    return app


# ----------------------------------------------------------------------
# uvicorn 入口（工厂模式；CLI 的 gui 子命令亦可用它）
# ----------------------------------------------------------------------

def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """以工厂模式启动 uvicorn（规格 §2.14：默认只监听回环）。

    Args:
        host: 监听地址；非回环时先打印安全告警。
        port: 监听端口。
    """
    import uvicorn

    if not _is_loopback(host):
        print("⚠️  警告：服务正监听在 " + host + ":" + str(port) +
              "（非回环地址）。局域网内任何能访问该端口的设备都能操作你的下载任务、" +
              "读取导出文件，请确认网络环境可信！")
    uvicorn.run("zhihu_downloader.app.server:create_app",
                factory=True, host=host, port=port, log_level="info")
