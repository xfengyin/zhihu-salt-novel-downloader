"""工具自身升级检查（架构规格书 §2.16：抗失效通道）。

产品承诺（市场调研驱动）：竞品普遍"失效即死"，本工具把"当天可修复"变成硬承诺——
doctor / gui 启动时问一次 GitHub Releases 最新版，有新版就提示用户升级。

硬性约束（§2.16）：

* 只用标准库 urllib.request，不新增任何运行时依赖；
* 10 秒超时：升级检查最多拖慢主流程 10 秒；
* 任何异常静默返回 None：无网络、GitHub 限流、JSON 结构变更、代理异常……
  一律不打扰用户，更不崩主流程；
* semver 归一化比较："v5.1.0" > "5.0.0"（去 v 前缀、逐段数字比较、忽略
  "-rc1" 之类预发布后缀），绝不用字符串比较（否则 "5.10.0" < "5.9.0"）。

版本号唯一来源仍是 zhihu_downloader.__version__（§0 铁律 4）；本模块只负责
"和线上最新版比一比"，不保存、不写盘。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

__all__ = [
    "RELEASES_API_URL",
    "RELEASE_URL_PREFIX",
    "REQUEST_TIMEOUT",
    "check_tool_update",
    "compare_versions",
    "format_release_hint",
    "is_newer",
    "normalize_version",
    "parse_version",
    "safe_release_url",
    "safe_version_label",
    "sanitize_console_text",
]

#: GitHub Releases 最新版的只读查询接口（规格 §2.16 指定地址）。
RELEASES_API_URL = (
    "https://api.github.com/repos/xfengyin/zhihu-salt-novel-downloader/releases/latest"
)

#: 单次请求超时秒数（§2.16：10s，超过即放弃，不阻塞主流程）。
REQUEST_TIMEOUT = 10.0

#: 带身份的 UA：GitHub API 要求非默认 UA，同时便于排查命中率。
_USER_AGENT = "zhihu-salt-novel-downloader/update-check"

#: 预发布/构建后缀分隔符（5.1.0-rc1、5.1.0+build2 都只取数字核心）。
_SUFFIX_RE = re.compile(r"[-+].*$")
#: 纯数字段（re.ASCII：不能让 "１２３" 这类全角数字混过校验后在 int() 处炸）。
_NUMERIC_RE = re.compile(r"^\d+$", re.ASCII)

#: 单个版本段允许的最大位数（R2 #9a）。CPython 对 int(str) 有 4300 位上限，
#: 超长数字串会抛 ValueError —— 本模块承诺"任何异常静默"，所以在解析前就设上限，
#: 而不是靠 sys.set_int_max_str_digits() 去改全局状态。
MAX_VERSION_DIGITS = 12

#: 可信发布页前缀（R2 #9b）。远端 html_url 必须以此为前缀，否则整个丢弃：
#: 只提示本仓库的 releases 页，避免被改包/中间人换成钓鱼域名。
RELEASE_URL_PREFIX = (
    "https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/"
)

#: 同一前缀的"路径部分"写法，用于 urlsplit 之后的二次核对。
_RELEASE_PATH = "/xfengyin/zhihu-salt-novel-downloader/releases/"

#: 控制台文本最大长度（R2 #9b：远端字段长度不可信，防刷屏/防终端缓冲区打爆）。
MAX_HINT_TEXT = 200

#: 必须剔除的控制字符：C0（含 ESC=\x1b —— OSC 8 伪造可点击链接、OSC 52 写剪贴板
#: 都从它起步；含 \n/\r，防伪造多行输出）、DEL、C1（\x80-\x9f 里也有 CSI）。
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: 可显示的版本 tag 形状：可选 v 前缀 + 最多 4 段数字 + 可选预发布/构建后缀。
#: 只有长这样的远端字符串才允许出现在提示里（R2 #9b 加固）。
_VERSION_SHAPE_RE = re.compile(r"^v?\d+(?:\.\d+){0,3}(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?$")

#: 版本号显示文本的最大长度（正常版本不超过 20，这里给足余量又能挡住长串）。
MAX_VERSION_TEXT = 40


# ----------------------------------------------------------------------
# semver 比较（纯函数、零副作用，供测试钉死）
# ----------------------------------------------------------------------
def normalize_version(version: Any) -> str:
    """归一化版本字符串：去空白、去 v/V 前缀、去 "-rc1"/"+build" 后缀。

    Args:
        version: 任意输入（None / 非字符串按空串处理，绝不抛异常）。

    Returns:
        形如 "5.1.0" 的字符串；无法归一化时返回 ""。
    """
    text = str(version or "").strip()
    if text[:1] in ("v", "V"):
        text = text[1:].strip()
    return _SUFFIX_RE.sub("", text)


def parse_version(version: Any) -> tuple[int, ...]:
    """把版本字符串解析成数字元组，非法输入返回空元组。

    非数字段（如 "5.0.x" 里的 x）按 0 处理，保证比较不炸；长度不等的补零由
    compare_versions() 负责，因此 "5.1" 与 "5.1.0" 视为相等。

    Args:
        version: 任意输入。

    Returns:
        数字元组；完全没有数字（如 ""、"abc"）时返回 ()。
    """
    core = normalize_version(version)
    if not core or not any(ch.isdigit() for ch in core):
        return ()  # 完全无数字（如 "abc"）视为非法版本
    parts: list[int] = []
    for raw in core.split("."):
        parts.append(_parse_segment(raw))
    return tuple(parts)


def _parse_segment(token: str) -> int:
    """把单个版本段转成 int，任何意外都退化为 0（R2 #9a）。

    超长数字串（如 "1" * 5000）会让 int() 抛 ValueError（Exceeds the limit
    (4300 digits)），一旦冒出去就违反"任何异常静默返回 None"的 §2.16 契约；
    这里先按位数拒绝，再用 try 兜住其余可能（例如未来实现的位数上限变化）。
    """
    value = token.strip()
    if not value or len(value) > MAX_VERSION_DIGITS or not _NUMERIC_RE.match(value):
        return 0
    try:
        return int(value)
    except ValueError:  # pragma: no cover - 理论上已被位数与正则挡死
        return 0


def compare_versions(left: Any, right: Any) -> int:
    """比较两个版本号：left 较新返回 1，相等返回 0，left 较旧返回 -1。

    任一侧缺少数字核心时返回 0（视为相等）——宁可不提示，也不给错误提示。

    Args:
        left: 左侧版本号（可带 v 前缀 / 预发布后缀）。
        right: 右侧版本号。

    Returns:
        1 / 0 / -1。
    """
    a = parse_version(left)
    b = parse_version(right)
    if not a or not b:
        return 0
    size = max(len(a), len(b))
    a_padded = a + (0,) * (size - len(a))
    b_padded = b + (0,) * (size - len(b))
    if a_padded > b_padded:
        return 1
    if a_padded < b_padded:
        return -1
    return 0


def is_newer(latest: Any, current: Any) -> bool:
    """latest 是否比 current 更新（is_newer("v5.1.0", "5.0.0") 为 True）。

    Args:
        latest: 远端最新版（GitHub tag）。
        current: 本地版本号。

    Returns:
        需要升级返回 True；相等、更旧、或版本串无法解析都返回 False。
    """
    return compare_versions(latest, current) > 0


# ----------------------------------------------------------------------
# 远端文本消毒（R2 #9b：GitHub 响应是不可信输入，会被原样打印到控制台）
# ----------------------------------------------------------------------
def sanitize_console_text(value: Any, *, limit: int = MAX_HINT_TEXT) -> str:
    """把不可信远端文本压成可安全打印的单行短文本。

    做两件事：

    * 剔除全部控制字符（C0 / DEL / C1）。ESC 起步的 OSC 8 能在终端里伪造一条
      可点击链接（显示文字与真实目标可以完全不同），OSC 52 能写系统剪贴板，
      BEL 能让终端响铃，CR/LF 能伪造出多行输出 —— 这些都不该由远端决定；
    * 截断到 limit 个字符，避免超长字段刷爆终端与用户的屏幕。

    Args:
        value: 任意输入（None / 不可字符串化对象一律按字符串化处理，绝不抛异常）。
        limit: 最多保留的字符数。

    Returns:
        清洗后的文本（可能为空串）。
    """
    try:
        text = str(value if value is not None else "")
    except Exception:  # noqa: BLE001 - 远端塞了个 __str__ 抛错的对象也不能崩
        return ""
    return _CONTROL_RE.sub("", text).strip()[:limit]


def safe_version_label(value: Any) -> str:
    """只允许"版本号形状"的远端文本被显示，其余退化为空串（R2 #9b 加固）。

    为什么不止步于剔除控制字符：tag_name 是**完全由远端决定**的一段文本，会被
    拼进我们自己的提示行。洗掉 ESC 只保证它不能驱动终端，仍允许远端把提示后面
    的文案改成任意内容（例如冒充官方说明、塞进一个可复制的假域名）。版本号本来
    就该长成一个固定的样子，所以按形状白名单收口：不匹配就不提示，宁缺毋滥。

    Args:
        value: 远端 tag_name / name 原始值。

    Returns:
        形如 "v5.1.0" / "5.1.0-rc1" 的版本字符串；不是版本号形状则返回空串。
    """
    text = sanitize_console_text(value, limit=MAX_VERSION_TEXT)
    if not text or not _VERSION_SHAPE_RE.match(text):
        return ""
    return text


def safe_release_url(value: Any) -> str:
    """校验远端 html_url：只接受本仓库 releases 页，其余一律丢弃（R2 #9b）。

    这里对 URL **不做修复、只做取舍**：原文里只要出现控制字符就直接丢弃
    （把 ESC/CR 删掉再拼回去，等于替攻击者把载荷洗成可用形态）；随后用
    urlsplit 核对权威部分，确保 scheme=https、host 恰为 github.com，再看路径前缀。
    只靠 startswith 是不够的："https://github.com@evil.com/..." 这类 userinfo 写法
    的真实主机是 evil.com，必须由 urlsplit 拆出来判。反过来，".../tag/v1.evil.com"
    这种把域名挂在路径尾巴上的写法看着可疑，但权威部分仍是 github.com，点开的只是
    GitHub 的 404 页，不属于跳转风险，无需为此牺牲正常链接。

    Args:
        value: 远端返回的 html_url 原始值。

    Returns:
        合法的发布页 URL；非 https、非本站、非 releases 路径、含控制字符或超长
        都返回空串（调用方据此只显示版本号，不显示链接）。
    """
    try:
        raw = str(value if value is not None else "").strip()
    except Exception:  # noqa: BLE001 - __str__ 抛错也当作没有链接
        return ""
    if not raw or len(raw) > MAX_HINT_TEXT * 2 or _CONTROL_RE.search(raw):
        return ""
    if not raw.startswith(RELEASE_URL_PREFIX):
        return ""  # 前缀已含尾部斜杠，".../releases.evil.com/" 这类拼接钓鱼过不了
    try:
        parts = urlsplit(raw)
        if parts.scheme != "https" or (parts.hostname or "").lower() != "github.com":
            return ""
        if parts.port not in (None, 443):
            return ""
        if not parts.path.startswith(_RELEASE_PATH):
            return ""
    except ValueError:  # 端口畸形等坏 URL
        return ""
    return raw


# ----------------------------------------------------------------------
# 唯一的网络入口
# ----------------------------------------------------------------------
def _fetch_release() -> dict[str, Any] | None:
    """GET releases/latest 并返回 JSON 对象；任何异常返回 None。

    Returns:
        接口返回的 dict；请求失败、超时、非 JSON、顶层不是对象时返回 None。
    """
    try:
        request = Request(  # noqa: S310 - 固定 https 常量地址，不拼接用户输入
            RELEASES_API_URL,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/vnd.github+json"},
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310
            body = response.read()
        payload = json.loads(bytes(body).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - §2.16 静默：升级检查绝不允许影响主流程
        return None
    return payload if isinstance(payload, dict) else None


def check_tool_update(current: str) -> dict[str, Any] | None:
    """检查是否有更新版本（规格 §2.16 的唯一公开入口）。

    Args:
        current: 当前版本号，通常是 zhihu_downloader.__version__。

    Returns:
        {"latest": "v5.1.0", "url": "<release 页>", "has_update": bool}；
        网络失败 / 超时 / 响应异常时返回 None（调用方据此什么都不显示）。
    """
    payload = _fetch_release()
    if payload is None:
        return None

    try:
        # tag_name 优先，缺失或形状不合法时退回 name（GitHub 某些响应只有标题）。
        tag = payload.get("tag_name")
        name = payload.get("name")
        latest = safe_version_label(tag) or safe_version_label(name)
        url = safe_release_url(payload.get("html_url"))
    except Exception:  # noqa: BLE001 - 结构变更也不能崩
        return None
    if not latest:
        return None  # 版本号形状不对 = 远端在乱写，§2.16：安静地什么都不提示

    return {"latest": latest, "url": url, "has_update": is_newer(latest, current)}


def format_release_hint(info: dict[str, Any] | None) -> str:
    """把 check_tool_update() 的结果渲染成一行中文提示。

    Args:
        info: check_tool_update 的返回值（可为 None）。

    Returns:
        有新版时返回一行提示文本；无新版 / 检查失败返回空串（调用方据此不打印）。
    """
    if not info or not info.get("has_update"):
        return ""
    # 双保险：即便调用方塞进来的是脏值，也不允许任意远端文本进入终端输出。
    latest = safe_version_label(info.get("latest")) or "新版本"
    url = safe_release_url(info.get("url"))
    if url:
        return f"⬆️ 发现新版本 {latest}（升级即可修复已知失效：{url}）"
    return f"⬆️ 发现新版本 {latest}（请到发布页下载最新版）"
