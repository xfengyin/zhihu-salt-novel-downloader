"""知乎扫码登录（web 端二维码流程）。

从 v4 simple/client.py 的 login_qr_start / login_qr_image / login_qr_poll 三个方法
抽出为**模块级函数**，便于 CLI 与 Web server 共用，也便于单测在 requests.Session
边界打桩。

本模块只依赖鸭子类型客户端（见 QrLoginClient），**不 import engine/client.py**
（并行开发约定：E1-E5 互不 import 对方新代码，只依赖 types/errors/signature）。

流程（参考 DecryptLogin zhihuScanqr）：

1. POST /udid                                        -> 设备指纹 x-udid
2. POST /api/v3/account/api/login/qrcode             -> 二维码 token
3. GET  .../qrcode/{token}/image                     -> 二维码图片字节
4. GET  .../qrcode/{token}/scan_info                 -> 扫码状态轮询

HTTP 一律走**一次性 requests.Session()**（R1 审查 M6）：requests.Session
官方非线程安全，server 双标签页并发 start/poll 共用 client.session 会在连接池
与 Cookie jar 上互踩；扫码是低 QPS 流程，每次公开调用新建、用完即关，顺带保证
扫码流量不携带既有登录态。

登录确认（status == "confirmed"）后：Cookie 经客户端**公开方法**
client.load_cookies 合并进会话（内部加锁、负责 domain 绑定；不再直接
client.session.cookies.update——裸 update 注入的 Cookie domain 为空，重定向到
外部域即泄露 z_c0，见 R2#P0-1），并统一经 auth.cookies.save 落盘
（0600 + 原子写）。

安全说明（R2 审计 #7）：

* poll() 的返回值**不含 Cookie 明文，也不含任何远端响应原文**——字段全部规范化
  （status 固定枚举、user_id 仅接受标量、error 仅取 message/code/name 且截断），
  可直接透传给 Web API；
* 所有错误消息只携带 `type(data).__name__`，绝不 `repr()` 远端 payload：结构漂移
  时 payload 可能携带 Cookie，而 server 会把 AuthError 文本回显进 API detail。
* token 强制 `^[A-Za-z0-9_-]{1,64}$`，不合规直接 AuthError（防路径注入与回显）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import requests

from ..errors import AuthError
from . import cookies

__all__ = [
    "DEFAULT_TIMEOUT",
    "IMAGE_URL",
    "QRCODE_URL",
    "SCAN_INFO_URL",
    "STATUS_CONFIRMED",
    "STATUS_ERROR",
    "STATUS_EXPIRED",
    "STATUS_SCANNED",
    "STATUS_WAITING",
    "UDID_URL",
    "QrLoginClient",
    "image",
    "poll",
    "qr_headers",
    "start",
]

# ----------------------------------------------------------------------
# 端点常量
# ----------------------------------------------------------------------

UDID_URL = "https://www.zhihu.com/udid"
QRCODE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode"
IMAGE_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/image"
SCAN_INFO_URL = "https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/scan_info"

#: 客户端未提供 timeout 属性时的兜底超时（秒）
DEFAULT_TIMEOUT = 20.0

#: poll 返回的五种状态（status 字段的固定枚举，绝不透传远端原文）
STATUS_WAITING = "waiting"      # 二维码未被扫描（远端 status == 0）
STATUS_SCANNED = "scanned"      # 已扫码，等待用户在 APP 内确认（远端 status == 1）
STATUS_CONFIRMED = "confirmed"  # 登录成功（Cookie 已落盘）
STATUS_ERROR = "error"          # 服务端返回错误 / 未知状态（结构漂移）
STATUS_EXPIRED = "expired"      # 二维码过期（远端 status == 2）

#: 知乎扫码接口已知的数字状态码 -> 规范化状态；其余值一律归 error（不带原文）。
_STATUS_BY_CODE: dict[int, str] = {
    0: STATUS_WAITING,
    1: STATUS_SCANNED,
    2: STATUS_EXPIRED,
}

#: 合法 token 形态：URL 安全字符、1~64 位（知乎 token 为字母数字串）。
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: error / user_id 字段进入返回值前的最大长度（防超长 payload 借道回显）。
_MAX_FIELD_LEN = 200


@runtime_checkable
class QrLoginClient(Protocol):
    """扫码登录所需的最小客户端接口（engine.client.ZhihuClient 天然满足）。

    注意（R1 审查 M6）：HTTP 不经过本接口的 session——qr 内部一律使用一次性
    requests.Session()；session 属性只是客户端整体形态的一部分，登录结果经
    load_cookies 公开方法回写（其内部负责加锁与 Cookie domain 绑定）。
    """

    session: requests.Session
    timeout: float
    cookie_file: Path

    def get_cookies(self) -> dict[str, str]: ...

    def load_cookies(self, source: str | Path | dict[str, str]) -> None: ...


def qr_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """构造扫码登录请求头（Origin/Referer 固定为 web 端登录页来源）。

    Args:
        extra: 需要追加/覆盖的请求头，例如 {"x-udid": "..."}。

    Returns:
        新的请求头字典（不修改传入的 extra）。
    """
    headers: dict[str, str] = {
        "Origin": "https://www.zhihu.com",
        "Referer": "https://www.zhihu.com/signup?next=%2F",
        "Accept": "application/json, text/plain, */*",
    }
    if extra:
        headers.update(extra)
    return headers


def _new_session() -> requests.Session:
    """一次性扫码 Session 工厂（R1 审查 M6；测试在此打桩）。

    独立于 client.session：requests.Session 非线程安全，双标签页并发扫码
    共用同一 Session 即竞态。低 QPS 场景下每次公开调用新建、with 用完即关。
    """
    return requests.Session()


def _timeout(client: QrLoginClient) -> float:
    """取客户端超时；缺失或非法时回落到 DEFAULT_TIMEOUT。"""
    value = getattr(client, "timeout", None)
    if value is None:
        return DEFAULT_TIMEOUT
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - 防御性分支
        return DEFAULT_TIMEOUT


def _validate_token(token: str) -> str:
    """校验二维码 token 形态（R2 审计 #7）。

    token 会被拼进 IMAGE_URL / SCAN_INFO_URL 的 URL 路径；远端结构漂移时
    可能返回超长串、含路径分隔符或控制字符的值。不合规直接拒绝，
    错误消息只描述长度与类型，**不回显 token 内容**。

    Args:
        token: 待校验的 token 字符串。

    Returns:
        去除首尾空白后的合法 token。

    Raises:
        AuthError: 为空或不符合 ^[A-Za-z0-9_-]{1,64}$。
    """
    cleaned = (token or "").strip()
    if not cleaned:
        raise AuthError("二维码 token 为空：请先调用 qr.start(client) 获取 token")
    if not _TOKEN_RE.fullmatch(cleaned):
        raise AuthError(
            f"二维码 token 不合法（长度 {len(cleaned)}，仅接受 1~64 位字母/数字/下划线/连字符）。"
            "知乎登录接口可能已变更，请重新运行 zhihu-downloader login，"
            "或改用 zhihu-downloader login --browser 导入浏览器 Cookie"
        )
    return cleaned


def _fetch_udid(session: requests.Session, timeout: float) -> str:
    """获取设备指纹 x-udid（扫码接口要求携带；走一次性 session，R1 M6）。"""
    try:
        resp = session.post(UDID_URL, headers=qr_headers(), timeout=timeout)
        udid = (resp.text or "").strip()
    except requests.RequestException as e:
        raise AuthError(
            f"获取登录设备标识（x-udid）失败：{e}。请检查网络后重新运行 zhihu-downloader login"
        ) from e
    if not udid:
        raise AuthError(
            "获取登录设备标识（x-udid）失败：知乎返回空内容。请稍后重试，"
            "或用 zhihu-downloader login --browser 从浏览器导入 Cookie"
        )
    return udid


def start(client: QrLoginClient) -> dict[str, Any]:
    """发起扫码登录，取回二维码 token 与图片地址。

    Args:
        client: 鸭子类型客户端（timeout/cookie_file 按需；HTTP 不经过其 session）。

    Returns:
        {"token": str, "image_url": str}；知乎若返回过期秒数则附带 expire_seconds。

    Raises:
        AuthError: 网络失败、响应异常或没有拿到 token（消息为中文且含下一步建议）。
    """
    timeout = _timeout(client)
    with _new_session() as session:  # 一次性 Session（R1 M6），双标签页并发互不干扰
        udid = _fetch_udid(session, timeout)
        try:
            resp = session.post(
                QRCODE_URL,
                headers=qr_headers({"x-udid": udid}),
                timeout=timeout,
            )
            data: Any = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise AuthError(
                f"获取登录二维码失败：{e}。请检查网络后重新运行 zhihu-downloader login"
            ) from e

    if not isinstance(data, dict):
        # 只报类型名：payload 可能携带敏感内容，绝不 repr 回显（R2 审计 #7）。
        raise AuthError(
            f"获取登录二维码失败：响应格式异常（类型为 {type(data).__name__}，期望 JSON 对象）。"
            "知乎登录接口可能已变更，请稍后重试，"
            "或改用 zhihu-downloader login --browser 导入浏览器 Cookie"
        )

    raw_token = data.get("token")
    # 只接受标量 token；dict/list 可能借字段携带 Cookie 等敏感 payload，
    # 既不能 str() 进 URL，更不能回显进错误消息。
    token = (
        str(raw_token).strip()
        if isinstance(raw_token, (str, int)) and not isinstance(raw_token, bool)
        else ""
    )
    if not token:
        raise AuthError(
            "获取登录二维码失败：响应中没有 token。知乎登录接口可能已变更，"
            "请稍后重试，或改用 zhihu-downloader login --browser 导入浏览器 Cookie"
        )
    token = _validate_token(token)

    result: dict[str, Any] = {"token": token, "image_url": IMAGE_URL.format(token=token)}
    expire = data.get("expires_in") or data.get("expire_seconds") or data.get("expire_in")
    if expire is not None:
        result["expire_seconds"] = expire
    return result


def image(client: QrLoginClient, token: str) -> bytes:
    """下载二维码图片字节（JPEG），供 CLI 存盘或 Web 前端 img 展示。

    Args:
        client: 鸭子类型客户端。
        token: start() 返回的二维码 token。

    Returns:
        图片二进制内容。

    Raises:
        AuthError: token 为空、请求失败或响应内容为空。
    """
    token = _validate_token(token)
    with _new_session() as session:  # 一次性 Session（R1 M6）
        try:
            resp = session.get(
                IMAGE_URL.format(token=token),
                headers=qr_headers(),
                timeout=_timeout(client),
            )
            resp.raise_for_status()
            content = resp.content or b""
        except requests.RequestException as e:
            raise AuthError(
                f"下载二维码图片失败：{e}。请重新运行 zhihu-downloader login 获取新的二维码"
            ) from e
    if not content:
        raise AuthError("下载二维码图片失败：响应内容为空。请重新运行 zhihu-downloader login")
    return bytes(content)


def _scalar_text(value: Any) -> str:
    """把标量安全转成短文本；非字符串/整数（dict/list/对象）一律归空。

    远端结构漂移时，error/user_id 等字段可能整体变成携带 Cookie 的对象，
    str()/repr 会把 payload 带进返回值与 API 响应（R2 审计 #7）。
    """
    if isinstance(value, str):
        return value.strip()[:_MAX_FIELD_LEN]
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)[:_MAX_FIELD_LEN]
    return ""


def _normalize_error(data: dict[str, Any]) -> str | None:
    """把响应里的 error 字段规范化为可读字符串（无错误返回 None）。

    只接受字符串（或字符串型 message/code/name）；其余结构返回通用文案，
    绝不把远端 payload 原文/ repr 带出去。
    """
    error = data.get("error")
    if not error:
        return None
    if isinstance(error, dict):
        for key in ("message", "code", "name"):
            message = _scalar_text(error.get(key))
            if message:
                return message
        return "服务端返回错误（未提供可读说明）"
    message = _scalar_text(error)
    return message or "服务端返回错误（格式异常）"


def _extract_cookie(data: dict[str, Any]) -> dict[str, str]:
    """从响应中提取 Cookie（兼容 dict 与 "k=v; k2=v2" 字符串两种形态）。"""
    cookie = data.get("cookie")
    if isinstance(cookie, dict):
        return {str(k): str(v) for k, v in cookie.items() if k and v}
    if isinstance(cookie, str):
        return cookies.parse_cookie_string(cookie)
    return {}


def _current_cookies(client: QrLoginClient) -> dict[str, str]:
    """安全读取客户端当前 Cookie（缺失/异常时视为空）。"""
    getter = getattr(client, "get_cookies", None)
    if not callable(getter):
        return {}
    try:
        return dict(getter() or {})
    except (TypeError, ValueError):  # pragma: no cover - 防御性分支
        return {}


def _apply_login_cookies(client: QrLoginClient, new_cookies: dict[str, str]) -> Path:
    """把登录返回的 Cookie 同步进会话并落盘（R1 审查 M6 重写）。

    内存态**只经客户端公开方法** client.load_cookies 合并（ZhihuClient 实现在
    其内部锁保护下更新 self._cookies 并以 domain=".zhihu.com" 绑定进 session
    jar）；磁盘态统一经 auth.cookies.save 原子写盘并置 0600。

    不再直接 client.session.cookies.update(...)，两个原因：
      1. M6：requests.Session 非线程安全，双标签页并发登录会在 jar 上互踩；
      2. R2#P0-1：裸 update(dict) 注入的 Cookie domain 为空，requests 会对任意
         主机发送——链路一旦被重定向到外部域，z_c0 直接泄露。

    客户端未提供 load_cookies（协议要求存在，防御性兜底）或同步抛错时，仅跳过
    内存合并，不丢弃已拿到的登录结果——磁盘上有，客户端下次 load 即可恢复。

    Args:
        client: 鸭子类型客户端。
        new_cookies: 本次登录拿到的 Cookie。

    Returns:
        实际写入的文件路径。
    """
    merged = _current_cookies(client)
    merged.update(new_cookies)

    loader = getattr(client, "load_cookies", None)
    if callable(loader):
        try:
            loader(dict(new_cookies))
        except Exception:  # noqa: BLE001 - 客户端内部状态同步失败不应丢掉登录结果
            pass

    return cookies.save(merged, getattr(client, "cookie_file", None))


def poll(client: QrLoginClient, token: str) -> dict[str, Any]:
    """轮询一次扫码状态。

    Args:
        client: 鸭子类型客户端。
        token: start() 返回的二维码 token。

    Returns:
        {"status": waiting|scanned|confirmed|error|expired,
         "user_id": str|None, "error": str|None, "saved_to": str|None}。

        四个字段全部规范化：status 恒为上面的固定枚举；user_id 仅接受标量
        （str/int）并截断；error 仅取可读 message/code/name；不再回传
        raw_status 等任何远端原文字段（R2 审计 #7：结构漂移时原文可能携带 Cookie）。

        status == "confirmed" 时 Cookie 已经 client.load_cookies（加锁、绑定
        domain）合并进会话，并经
        auth.cookies.save 以 0600 落盘，saved_to 为落盘路径；
        返回值**不包含 Cookie 值**，可安全透传给前端。

    Raises:
        AuthError: token 非法、网络失败或响应格式异常（消息只含类型名，不含 payload）。
    """
    token = _validate_token(token)
    with _new_session() as session:  # 一次性 Session（R1 M6）
        try:
            resp = session.get(
                SCAN_INFO_URL.format(token=token),
                headers=qr_headers(),
                timeout=_timeout(client),
            )
            data: Any = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise AuthError(
                f"轮询扫码状态失败：{e}。若持续失败请重新运行 zhihu-downloader login"
            ) from e

    if not isinstance(data, dict):
        # 只报类型名：list/str 等漂移响应可能整体就是敏感 payload，绝不 repr。
        raise AuthError(
            f"轮询扫码状态返回异常：响应不是 JSON 对象（类型为 {type(data).__name__}）。"
            "请重新运行 zhihu-downloader login"
        )

    result: dict[str, Any] = {
        "status": STATUS_WAITING,
        "user_id": None,
        "error": None,
        "saved_to": None,
    }

    error = _normalize_error(data)
    if error:
        result["status"] = STATUS_ERROR
        result["error"] = error
        return result

    user_id = _scalar_text(data.get("user_id"))
    if user_id:
        new_cookies = _extract_cookie(data)
        if new_cookies:
            result["saved_to"] = str(_apply_login_cookies(client, new_cookies))
        result["status"] = STATUS_CONFIRMED
        result["user_id"] = user_id
        return result

    raw_status: Any = data.get("status")
    if isinstance(raw_status, bool):  # bool 是 int 子类，True==1 会误判 scanned
        raw_status = None
    mapped = _STATUS_BY_CODE.get(raw_status) if isinstance(raw_status, int) else None
    if mapped:
        result["status"] = mapped
    else:
        # 未知状态（含非数字/缺失/结构漂移）：归 error，只报类型名，不带原文。
        result["status"] = STATUS_ERROR
        result["error"] = (
            f"未知的扫码状态（响应字段类型为 {type(raw_status).__name__}）。"
            "知乎登录接口可能已变更，请重新运行 zhihu-downloader login"
        )
    return result
