"""线程安全的知乎 HTTP 客户端（限速 + 签名 + 指数退避重试 + 受控重定向）。

设计要点（见 docs/ARCHITECTURE_SPEC.md §2.1）：

- 同步内核：基于 requests.Session，不引入 asyncio，易读、易 mock、易维护；
- 线程安全：一把 threading.Lock 同时保护 (a) 限速计时（时间槽预约）与
  (b) session 请求，因此可安全交给 ThreadPoolExecutor 并发使用；
- 限速：rate_limit 语义是「每秒请求数」，0 / None / 负数表示不限速。
  多线程下先预约下一个可用时间槽再休眠，保证整体节奏不超过平台友好值；
- 重定向（R2#P0-1）：requests 默认 allow_redirects=True 会把 z_c0/d_c0 等
  登录 Cookie 原样带到任意跳转目标域。这里改为 allow_redirects=False +
  手写跳循环（上限 MAX_REDIRECT_HOPS）：每一跳的 Location（urljoin 解析
  相对跳转）与响应最终 URL 都必须通过 _is_zhihu_target 双解析器校验，
  不合规立即抛中文 ZhihuError。签名头（x-zse-96 等）同样只在知乎域 URL
  上生成、随校验通过的请求发出，天然不会发往外部域；
- Cookie 注入（R2#P0-1 兜底）：load_cookies 逐条 session.cookies.set(
  name, value, domain=".zhihu.com")（前导点写法同时覆盖裸域与全部子域），
  杜绝 update(dict) 产生的「空 domain 会话 Cookie 对任意主机都发送」；
- 重试：网络错误与 429/5xx 走指数退避（1/2/4s…）；403 属反爬拦截，
  重试只会加重风控，立即抛中文错误；404 与其它 4xx 同理不重试；
  网络错误的用户可见消息只保留异常类型名（R2#P0-2：连接池 repr 含内网
  host:port，不得成为 GUI 的端口探测 oracle）；
- Cookie：读写一律委托 zhihu_downloader.auth.cookies（落盘 0600、原子写）。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from urllib3.util import parse_url as _urllib3_parse_url

from .. import __version__
from ..auth import cookies as cookie_store
from ..errors import SaltError, ZhihuError
from ..signature import XZSE_93_VERSION, generate_zhihu_sign

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_USER_AGENT",
    "MAX_REDIRECT_HOPS",
    "RETRY_BASE_DELAY",
    "RETRYABLE_STATUS",
    "ZhihuClient",
]

#: 现代桌面 Chrome UA（v5 起替换 v4 的 Chrome/86），保留可识别的产品后缀。
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 zhihu-salt/{__version__}"
)

#: 指数退避基础秒数：第 1/2/3 次重试分别等待 1/2/4 秒。
RETRY_BASE_DELAY = 1.0

#: 需要重试的 HTTP 状态码（限流与服务端异常）。
RETRYABLE_STATUS: tuple[int, ...] = (429, 500, 502, 503, 504)

#: 手动跟随重定向的最大跳数（R2#P0-1：跳数与去向都由我们控制）。
MAX_REDIRECT_HOPS = 5

#: 视为重定向的 HTTP 状态码（与 requests 的自动跟随集合一致）。
REDIRECT_STATUSES: tuple[int, ...] = (301, 302, 303, 307, 308)

#: 反斜杠字面量。用 chr(92) 而不是转义序列，避免源码里出现反斜杠字符
#: （与 app/server.py 的 _NL / 路径分隔符检查同一写法约定）。
_BS = chr(92)

#: 跨域重定向被拦截时的中文错误（Cookie/签名保护，R2#P0-1）。
_OFFSITE_REDIRECT_MESSAGE = (
    "登录凭证受保护：该链接被重定向到非知乎地址，已中止请求"
    "（Cookie 与签名头不会发往外部域），请确认链接来源可信后重试。"
)

#: 重试回调签名：on_retry(url, 第几次重试, 退避秒数, 中文原因)。
OnRetryHook = Callable[[str, int, float, str], None]


def _host_in_zhihu(host: str) -> bool:
    """host 是否严格等于 zhihu.com 或为其子域（空串一律 False）。"""
    return bool(host) and (host == "zhihu.com" or host.endswith(".zhihu.com"))


def _is_zhihu_target(url: str) -> bool:
    """URL 能否作为携带 Cookie/签名头的请求目标（R2#P0-1/P0-2 核心闸门）。

    双解析器一致才放行，专治解析差分绕过（PoC 见 tests/test_client.py：
    「http://127.0.0.1:9501 + 反斜杠 + @www.zhihu.com/」在 urlparse 的
    hostname 眼里是 www.zhihu.com，urllib3 实际却连 127.0.0.1:9501）：

    1. urllib.parse.urlparse：scheme 必须 http/https；netloc 不得含反斜杠
       或 @（userinfo 注入 / 反斜杠差分载荷）；
    2. urllib3.util.parse_url：与 requests 真正发请求所用的同一解析器，
       host 必须同为知乎域，authority 同样硬拒反斜杠/@。

    任一解析器抛错、任一 host 为空、或两者结论不一致 → False。
    """
    try:
        parsed = urlparse(url)
    except ValueError:  # 极端畸形 URL（如非法 IPv6 字面量）
        return False
    if (parsed.scheme or "").lower() not in ("http", "https"):
        return False
    if _BS in parsed.netloc or "@" in parsed.netloc:
        return False
    host_a = (parsed.hostname or "").lower()
    try:
        loc = _urllib3_parse_url(url)
    except Exception:  # LocationParseError 等：一律视为不可信目标
        return False
    authority = loc.authority or ""
    if _BS in authority or "@" in authority:
        return False
    host_b = (loc.host or "").lower()
    return _host_in_zhihu(host_a) and _host_in_zhihu(host_b)


def _redirect_location(response: Any) -> str:
    """取响应 Location 头（requests 的 CaseInsensitiveDict 与测试字典兼容）。"""
    headers = getattr(response, "headers", None) or {}
    try:
        location = headers.get("Location") or headers.get("location")
    except AttributeError:  # pragma: no cover - 非映射型 headers 视为缺失
        return ""
    return str(location or "").strip()


class _RetryableStatus(Exception):
    """内部信号：429/5xx 可重试状态。只在 fetch 内部流转，绝不外抛。"""


class ZhihuClient:
    """知乎客户端（同步、线程安全）。

    Attributes:
        session: 底层 requests.Session；测试可在构造后直接替换为假对象
            （只需实现 get(url, headers=..., timeout=...)；allow_redirects
            关键字不认识时会自动退回普通调用）。
        on_retry: 可选重试回调，供上层（fetcher）发 retry 进度事件。
    """

    def __init__(
        self,
        cookie_file: str | Path | None = None,
        timeout: float = 20.0,
        rate_limit: float = 2.0,
        retries: int = 3,
    ) -> None:
        """构造客户端。

        Args:
            cookie_file: Cookie 文件路径；为 None 时使用
                auth.cookies.DEFAULT_COOKIE_FILE，且文件存在时自动加载。
            timeout: 单次请求超时（秒）。
            rate_limit: 每秒请求数上限（2 即约每 0.5s 一次）；0/None/负数为不限速。
            retries: 失败后的重试次数（不含首次请求），退避 1/2/4s。
        """
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.retries = max(0, int(retries))
        self.cookie_file = Path(cookie_file) if cookie_file else cookie_store.DEFAULT_COOKIE_FILE
        self.on_retry: OnRetryHook | None = None

        # 一把锁同时保护限速计时与 session 请求（见模块 docstring）。
        self._lock = threading.Lock()
        # None 表示「还没有发过请求」：首个请求不必等一个完整间隔。
        self._last_request_at: float | None = None
        self._cookies: dict[str, str] = {}

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )

        if self.cookie_file.exists():
            try:
                self.load_cookies(self.cookie_file)
            except SaltError as exc:
                # Cookie 文件坏了不该让所有命令（含 doctor）直接崩：
                # 降级为未登录状态并告警，用户按提示重新登录即可。
                logger.warning("Cookie 文件加载失败：%s（可运行 zhihu-downloader login 重新登录）", exc)

    # ------------------------------------------------------------------
    # 派生实例
    # ------------------------------------------------------------------

    def copy_with(
        self,
        rate_limit: float | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> ZhihuClient:
        """复制一个只改请求节奏参数的新客户端（不原地修改本实例）。

        新实例共享同一个 Cookie 文件路径并带上已加载的 Cookie，因此一次登录后
        派生的低速率客户端仍可用，且 save_cookies() 会写回同一处。

        Args:
            rate_limit: 新客户端每秒请求数；None 表示沿用当前值。
            timeout: 新客户端超时秒数；None 表示沿用当前值。
            retries: 新客户端重试次数；None 表示沿用当前值。

        Returns:
            新的 ZhihuClient 实例。
        """
        clone = ZhihuClient(
            cookie_file=self.cookie_file,
            timeout=self.timeout if timeout is None else timeout,
            rate_limit=self.rate_limit if rate_limit is None else rate_limit,
            retries=self.retries if retries is None else retries,
        )
        clone.load_cookies(self.get_cookies())
        return clone

    # ------------------------------------------------------------------
    # Cookie 管理（全部委托 auth.cookies）
    # ------------------------------------------------------------------

    def get_cookies(self) -> dict[str, str]:
        """返回当前 Cookie 字典的副本（修改副本不影响客户端）。"""
        with self._lock:
            return dict(self._cookies)

    def save_cookies(self, cookie_file: str | Path | None = None) -> Path:
        """把当前 Cookie 保存到文件（委托 auth.cookies.save，权限 0600）。

        Args:
            cookie_file: 目标路径；None 时使用 self.cookie_file。

        Returns:
            实际写入的路径。
        """
        target = Path(cookie_file) if cookie_file else self.cookie_file
        return cookie_store.save(self.get_cookies(), target)

    def load_cookies(self, source: str | Path | dict[str, str]) -> None:
        """加载 Cookie 并合并进当前会话（委托 auth.cookies.load）。

        R2#P0-1：注入 session 时逐条绑定 domain=".zhihu.com"（前导点写法
        同时覆盖裸域 zhihu.com 与全部子域）。若改用 cookies.update(dict)，
        注入的 Cookie domain 为空，requests 会把它对任意主机都发送——
        一旦链路被重定向到外部域，z_c0 就跟着泄露。

        Args:
            source: Cookie 字典，或 JSON / Netscape / name=value 文件路径。

        Raises:
            AuthError: 文件不存在或内容无法解析（中文可读消息）。
        """
        loaded = cookie_store.load(source)
        with self._lock:
            self._cookies.update(loaded)
            jar = self.session.cookies
            if hasattr(jar, "set"):
                for name, value in loaded.items():
                    jar.set(name, value, domain=".zhihu.com")
            else:  # pragma: no cover - 测试替身只实现 update() 的兜底
                jar.update(loaded)

    def has_valid_signing_cookie(self) -> bool:
        """是否具备生成 x-zse-96 签名所需的 d_c0。"""
        with self._lock:
            return bool(self._cookies.get("d_c0"))

    # ------------------------------------------------------------------
    # 签名
    # ------------------------------------------------------------------

    def signed_headers(self, url: str) -> dict[str, str]:
        """为知乎系 URL 生成签名请求头（复用 signature.generate_zhihu_sign）。

        R2#P0-1：签名头与 Cookie 同属登录凭证，只允许发往知乎域——本方法
        用 _is_zhihu_target 把关（scheme/反斜杠/@/双解析器一致全过才签），
        非知乎目标返回空字典；fetch 跳循环里每跳都只对通过域校验的 URL
        调用本方法，签名头天然不会随重定向漂到外部域。

        Args:
            url: 目标 URL。

        Returns:
            含 x-zse-96 / x-zst-81 / x-zse-93 的字典；非知乎域名或缺少 d_c0
            时返回空字典。
        """
        if not _is_zhihu_target(url):
            return {}
        cookies = self.get_cookies()
        if not cookies.get("d_c0"):
            return {}
        sign = generate_zhihu_sign(url, cookies)
        if not sign:
            return {}
        return {
            "x-zse-96": sign["x-zse-96"],
            "x-zst-81": sign["x-zst-81"],
            "x-zse-93": XZSE_93_VERSION,
        }

    @staticmethod
    def _is_zhihu_url(url: str) -> bool:
        """URL 是否属于知乎系域名（旧入口保留，实现收紧为 _is_zhihu_target）。"""
        return _is_zhihu_target(url)

    # ------------------------------------------------------------------
    # 限速与请求
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        """按 rate_limit（请求/秒）在连续请求之间限速，线程安全。

        多线程下先「预约」下一个可用时间槽，再在锁外休眠，因此既不会两个线程
        挤在同一时刻发请求，也不会因持锁休眠而互相阻塞。
        """
        limit = self.rate_limit
        if not limit or limit <= 0:
            return
        interval = 1.0 / float(limit)
        wait = 0.0
        with self._lock:
            now = time.monotonic()
            last = self._last_request_at
            if last is None:
                self._last_request_at = now
            else:
                candidate = last + interval
                if candidate > now:
                    wait = candidate - now
                    self._last_request_at = candidate
                else:
                    self._last_request_at = now
        if wait > 0:
            time.sleep(wait)

    def _session_get(self, url: str, headers: dict[str, str] | None) -> Any:
        """发一次不自动跟随重定向的 GET（R2#P0-1：跳转必须过我们的域闸门）。

        测试替身的 session.get 可能不认识 allow_redirects 关键字参数
        （参数绑定阶段抛 TypeError，函数体尚未执行、不会记录调用）：退回
        普通调用即可——真实 requests.Session 永远支持该参数。
        """
        try:
            return self.session.get(
                url, headers=headers or None, timeout=self.timeout, allow_redirects=False
            )
        except TypeError:  # pragma: no cover - 鸭子类型测试替身兜底
            return self.session.get(url, headers=headers or None, timeout=self.timeout)

    def _fetch_chain(self, url: str) -> str:
        """从 url 出发完成一轮 GET，含手写重定向跳循环。

        每一跳：只对知乎域生成签名头 → 限速 → allow_redirects=False 请求 →
        复校验响应最终 URL（R2#P0-2：防解析器差分残余）→ 3xx 则解析
        Location（urljoin 支持相对跳转）并校验下一跳，不合规立即中止。

        Returns:
            200 响应文本。

        Raises:
            ZhihuError: 重定向到非知乎地址 / 跳数超限 / 缺 Location /
                403 / 404 / 其它不可重试 HTTP 错误。
            _RetryableStatus: 429/5xx，由 fetch 外层退避重试。
            requests.RequestException: 网络层错误，由 fetch 外层退避重试。
        """
        current = url
        for _hop in range(MAX_REDIRECT_HOPS + 1):
            headers = self.signed_headers(current)
            self._throttle()
            with self._lock:
                response = self._session_get(current, headers)
            # 请求后复校验最终落点：即使连接层解析与闸门存在残余差分，
            # 凭证也只可能停在知乎域；不合规一律中止（不读 body）。
            final_url = str(getattr(response, "url", "") or current)
            if not _is_zhihu_target(final_url):
                raise ZhihuError(_OFFSITE_REDIRECT_MESSAGE)
            status = int(getattr(response, "status_code", 0) or 0)
            if status in REDIRECT_STATUSES:
                location = _redirect_location(response)
                if not location:
                    raise ZhihuError(
                        f"重定向响应（HTTP {status}）缺少 Location 头，无法继续：{current}"
                    )
                # urljoin 以最终落点为基准解析相对跳转（"/api/v4/…"、"../x" 等）。
                current = urljoin(final_url, location)
                if not _is_zhihu_target(current):
                    raise ZhihuError(_OFFSITE_REDIRECT_MESSAGE)
                continue
            if status == 200:
                return str(response.text)
            if status == 403:
                raise ZhihuError("请求被知乎反爬拦截（HTTP 403），请重新登录或更新 Cookie 后重试")
            if status == 404:
                raise ZhihuError(f"内容不存在（HTTP 404），请确认链接是否正确或已被删除：{current}")
            if status in RETRYABLE_STATUS or 500 <= status < 600:
                tail = "（访问过于频繁）" if status == 429 else "（知乎服务端异常）"
                raise _RetryableStatus(f"HTTP {status}{tail}")
            raise ZhihuError(f"请求失败（HTTP {status}）：{current}")

        raise ZhihuError(
            "登录凭证受保护：该链接重定向次数超过 " + str(MAX_REDIRECT_HOPS) +
            " 跳，已中止请求（防止跳转环与凭证漂流）。"
        )

    def fetch(self, url: str) -> str:
        """GET 页面文本：限速 → 受控重定向跳循环 → 失败按指数退避重试。

        Args:
            url: 目标 URL（知乎域链接；重定向只允许停留在知乎域内）。

        Returns:
            响应文本（HTML 或 JSON 字符串）。

        Raises:
            ZhihuError: 重定向到非知乎地址、跳数超限、HTTP 403（反爬拦截，
                立即抛出不重试）、HTTP 404、其它不可重试的 HTTP 错误，
                或重试耗尽（消息含最后一次失败原因；网络错误只保留异常
                类型名，不回显连接池里的 host:port）。
        """
        attempts = self.retries + 1
        last_reason = ""
        for attempt in range(1, attempts + 1):
            try:
                return self._fetch_chain(url)
            except _RetryableStatus as exc:
                last_reason = str(exc)
            except requests.RequestException as exc:
                # R2#P0-2：exc 的连接池 repr 含内网 host:port（如
                # HTTPSConnectionPool(host='127.0.0.1', port=9501)），
                # 原样透传会让 GUI 变成端口探测 oracle——只留异常类型名。
                last_reason = "网络连接失败（目标不可达：" + type(exc).__name__ + "）"

            if attempt < attempts:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                self._notify_retry(url, attempt, delay, last_reason)
                logger.warning(
                    "请求失败 %s（%s），%.0fs 后重试（第 %d/%d 次）",
                    url, last_reason, delay, attempt, self.retries,
                )
                time.sleep(delay)

        raise ZhihuError(
            f"请求失败 {url}：已重试 {self.retries} 次仍未成功，最后原因：{last_reason}。"
            "请检查网络，或先运行 zhihu-downloader doctor 排查 Cookie 与签名。"
        )

    def _notify_retry(self, url: str, attempt: int, delay: float, reason: str) -> None:
        """触发可选的 on_retry 回调；回调内部异常不得影响重试主流程。"""
        hook = self.on_retry
        if hook is None:
            return
        try:
            hook(url, attempt, delay, reason)
        except Exception:  # pragma: no cover - 防御：进度回调不应打断下载
            logger.exception("on_retry 回调异常（已忽略）url=%s", url)
