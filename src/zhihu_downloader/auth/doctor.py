"""环境诊断（doctor）：一条命令看清"装好了没、Cookie 能不能用、签名是否失效"。

规格 §2.7：run_checks() 返回 (level, name, message) 三元组清单，level ∈
{"ok", "warn", "error", "info"}；调用方（CLI / Web）自行渲染与决定退出码。

检查项与排障分层（重点：区分"Cookie 缺失"与"签名失效"两条排障路径）：

* 版本 / Python/系统 —— 运行环境是否满足 >= 3.10；
* Cookie 存在 —— 文件不存在只 warn（首次使用属正常），解析失败 error；
* Cookie 权限 —— POSIX 断言 0600，宽于 0600 则 warn；Windows 无 chmod 语义，
  输出 info 级 NTFS ACL / OneDrive 提示；
* z_c0 / zse_ck —— 登录态与反爬字段，缺失 warn；
* d_c0 —— **签名必需字段**：未登录时 warn，已登录却缺失时 error（下载必然 403）；
* 签名自检 —— 用 d_c0 对固定 URL 生成 x-zse-96 并校验 "2.0_" 前缀：
  - 缺 d_c0 -> info（跳过，指回上一条排障路径：先补 Cookie）；
  - 前缀异常/生成异常 -> error（签名算法失效：升级或反馈 issue，与 Cookie 缺失区分开）；
* 限速 —— rate_limit 是否落在合理区间（0.5~5 请求/秒）；
* 网络探测 —— 可选；测试与离线环境传 network=False 跳过；
* 磁盘占用 —— info 级：state_dir 断点缓存总量（S3 的 CheckpointStore.
  total_bytes 汇总），超 500MB 给"书架移除不再追更的书"的 prune 指引；
  观测失败只记 info，绝不影响 doctor 退出码。
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

import requests

from .. import __version__, signature
from ..engine.checkpoint import CheckpointStore
from ..engine.fetcher import DEFAULT_STATE_SUBDIR
from ..errors import SaltError
from . import cookies

__all__ = [
    "DEFAULT_RATE_LIMIT",
    "DISK_SOFT_LIMIT_BYTES",
    "ICONS",
    "MAX_RATE_LIMIT",
    "MIN_PYTHON",
    "MIN_RATE_LIMIT",
    "NETWORK_PROBE_URL",
    "SIGN_CHECK_URL",
    "SIGN_PREFIX",
    "Check",
    "count_levels",
    "format_checks",
    "has_errors",
    "run_checks",
    "summary_line",
]

#: 单条检查结果：(level, name, message)，level ∈ ok|warn|error|info
Check = tuple[str, str, str]

#: 渲染用图标
ICONS: dict[str, str] = {"ok": "✅", "warn": "⚠️", "error": "❌", "info": "ℹ️"}

#: 支持的最低 Python 版本
MIN_PYTHON: tuple[int, int] = (3, 10)

#: 默认限速（请求/秒），与 ZhihuClient 默认值保持一致
DEFAULT_RATE_LIMIT = 2.0

#: 合理限速区间（请求/秒）：低于 MIN 太慢无意义且通常是笔误，高于 MAX 有反爬与合规风险
MIN_RATE_LIMIT = 0.5
MAX_RATE_LIMIT = 5.0

#: 签名自检用的固定 URL（只用于本地计算，不发请求）
SIGN_CHECK_URL = "https://www.zhihu.com/api/v4/me"

#: x-zse-96 应有的版本前缀
SIGN_PREFIX = "2.0_"

#: 网络探测地址
NETWORK_PROBE_URL = "https://www.zhihu.com"

#: 断点缓存磁盘占用软上限（500MB）：超过只给 info 级 prune 指引，不算错误
DISK_SOFT_LIMIT_BYTES = 500 * 1024 * 1024


# ----------------------------------------------------------------------
# 各项检查
# ----------------------------------------------------------------------

def _check_version() -> Check:
    """版本信息（唯一来源：zhihu_downloader.__version__）。"""
    return ("info", "版本", f"zhihu-downloader {__version__}")


def _check_python() -> Check:
    """Python 与操作系统信息。"""
    py_ver = ".".join(str(x) for x in sys.version_info[:3])
    desc = f"Python {py_ver}，{platform.system()} {platform.release()}"
    if sys.version_info < MIN_PYTHON:
        return ("error", "Python/系统", f"{desc}（本项目需要 Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}）")
    return ("ok", "Python/系统", desc)


def _load_cookie_state(path: Path) -> tuple[str, dict[str, str], str]:
    """读取 Cookie 文件，返回 (状态, 字典, 说明)；状态 ∈ missing|corrupt|ok。"""
    if not path.exists():
        return "missing", {}, f"Cookie 文件不存在: {path}"
    try:
        data = cookies.load(path)
    except SaltError as e:
        return "corrupt", {}, f"Cookie 文件无法解析: {path}（{e}）"
    except OSError as e:  # pragma: no cover - cookies.load 已包装大部分 IO 错误
        return "corrupt", {}, f"Cookie 文件读取失败: {path}（{e}）"
    return "ok", data, ""


def _check_cookie_file(path: Path, state: str, data: dict[str, str], note: str = "") -> list[Check]:
    """Cookie 文件存在性与权限。"""
    if state == "missing":
        return [("warn", "Cookie 存在",
                 f"{path} 不存在（首次使用属正常）。下一步：zhihu-downloader login 扫码登录，"
                 "或 zhihu-downloader login --browser 从浏览器导入")]
    if state == "corrupt":
        return [("error", "Cookie 存在",
                 f"{note or path + ' 无法解析'}。下一步：删除该文件后重新登录"
                 "（zhihu-downloader login），或直接覆盖导入新 Cookie")]
    out: list[Check] = [("ok", "Cookie 存在", f"{path}（共 {len(data)} 个 Cookie）")]
    perm = _check_cookie_mode(path)
    if perm:
        out.append(perm)
    return out


def _os_is_windows() -> bool:
    """是否运行在 Windows（独立函数便于测试打桩；不改全局 os.name）。"""
    return os.name == "nt"


def _check_cookie_mode(path: Path) -> Check | None:
    """Cookie 文件权限检查。

    POSIX：断言 0600（其他用户可读则 warn）。
    Windows（R2 审计 #8）：os.chmod 无 POSIX 语义，保存侧的 0600 只是尽力而为，
    真实边界由 NTFS ACL 决定——输出 info 级提示，引导用户确认目录未同步到
    OneDrive 等云盘（云同步会把 Cookie 明文带上远端）。
    """
    if _os_is_windows():
        return ("info", "Cookie 权限",
                "Windows 依赖 NTFS ACL（os.chmod 无 POSIX 语义，0600 仅为尽力而为）。"
                f"建议确认 Cookie 目录未同步到 OneDrive 等云盘：{path}")
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:  # pragma: no cover - 竞态：文件刚被删除
        return None
    if mode & 0o077:
        return ("warn", "Cookie 权限",
                f"{path} 权限为 {oct(mode)}（其他用户可读，存在泄露风险）。"
                "修复：chmod 600 " + str(path))
    return ("ok", "Cookie 权限", f"{path} 权限 {oct(mode)}（仅本人可读）")


def _check_key(name: str, data: dict[str, str], logged_in: bool, purpose: str) -> Check:
    """通用关键字段检查。"""
    value = data.get(name) or ""
    if value:
        return ("ok", name, f"{name} 已存在（{purpose}，长度 {len(value)}）")
    if not logged_in:
        return ("warn", name, f"缺少 {name}（{purpose}）→ 请先运行 zhihu-downloader login 扫码登录")
    return ("warn", name, f"缺少 {name}（{purpose}）→ 建议重新登录：zhihu-downloader login")


def _check_d_c0(data: dict[str, str], state: str) -> Check:
    """d_c0 是 x-zse-96 签名的必需输入：已登录却缺失属致命错误。"""
    if data.get("d_c0"):
        return ("ok", "d_c0", f"d_c0 已存在（x-zse-96 签名必需，长度 {len(data['d_c0'])}）")
    if state != "ok":
        return ("warn", "d_c0", "缺少 d_c0（x-zse-96 签名必需）→ 请先运行 zhihu-downloader login 扫码登录")
    return ("error", "d_c0",
            "缺少 d_c0：它是 x-zse-96 签名的必需字段，缺失时所有下载都会被知乎反爬拦截（HTTP 403）。"
            "下一步：重新扫码登录 zhihu-downloader login，或用浏览器导入完整 Cookie "
            "zhihu-downloader login --browser")


def _check_signature(data: dict[str, str]) -> Check:
    """签名自检：本地生成 x-zse-96 并校验版本前缀。

    两条排障路径在此分流：
    * 没有 d_c0 —— Cookie 缺失（看 d_c0 检查项，重新登录即可）；
    * 有 d_c0 但前缀不对/生成异常 —— 签名失效（算法与线上不匹配，需升级或反馈）。
    """
    dc0 = data.get("d_c0")
    if not dc0:
        return ("info", "签名自检",
                "已跳过：缺少 d_c0 无法生成 x-zse-96（属 Cookie 缺失，请先按 d_c0 检查项补齐 Cookie）")
    try:
        sign = signature.generate_zhihu_sign(SIGN_CHECK_URL, dict(data))
    except Exception as e:  # noqa: BLE001 - 诊断命令必须把任何异常转成人话
        return ("error", "签名自检",
                f"签名生成异常（{type(e).__name__}: {e}）→ 签名算法可能已失效，"
                "请升级到最新版 zhihu-salt-novel-downloader 后重试")

    zse96 = str((sign or {}).get("x-zse-96") or "")
    if not zse96:
        return ("error", "签名自检",
                "未能生成 x-zse-96（d_c0 存在但签名为空）→ Cookie 中的 d_c0 可能已损坏，"
                "请重新登录获取 Cookie")
    if not zse96.startswith(SIGN_PREFIX):
        return ("error", "签名自检",
                f"x-zse-96 前缀异常（期望 {SIGN_PREFIX}，实际 {zse96[:8]!r}）→ "
                "签名算法与知乎线上版本不匹配（属签名失效，不是 Cookie 问题），"
                "请升级本工具或在 issue 区反馈")
    if not (sign or {}).get("x-zst-81"):
        return ("warn", "签名自检",
                "x-zse-96 正常但缺少 x-zst-81 → 请升级到最新版（签名常量缺失可能被反爬拦截）")
    return ("ok", "签名自检",
            f"x-zse-96 生成正常（前缀 {SIGN_PREFIX}，长度 {len(zse96)}；固定探测 URL）")


def _check_rate_limit(rate_limit: float | None) -> Check:
    """限速合理性（请求/秒）。"""
    if rate_limit is None:
        return ("ok", "限速",
                f"未显式配置，使用默认 {DEFAULT_RATE_LIMIT} 请求/秒（合理）")
    try:
        value = float(rate_limit)
    except (TypeError, ValueError):
        return ("warn", "限速", f"限速值无法解析为数字：{rate_limit!r}（将按默认 {DEFAULT_RATE_LIMIT} 执行）")
    if value <= 0:
        return ("warn", "限速",
                f"rate_limit={value} 已关闭限速 → 容易触发反爬，建议 1~2 请求/秒")
    if value < MIN_RATE_LIMIT:
        return ("warn", "限速",
                f"rate_limit={value} 低于最小建议 {MIN_RATE_LIMIT} 请求/秒（下载会明显变慢）")
    if value > MAX_RATE_LIMIT:
        return ("warn", "限速",
                f"rate_limit={value} 偏高（>{MAX_RATE_LIMIT} 请求/秒）→ 反爬风险上升，"
                "请仅用于本人已购内容的个人备份")
    return ("ok", "限速", f"rate_limit={value} 请求/秒（默认 {DEFAULT_RATE_LIMIT}，合理）")


def _check_network(enabled: bool, timeout: float) -> Check:
    """网络探测（可选；离线环境/测试传 network=False 跳过）。"""
    if not enabled:
        return ("info", "网络", "已跳过网络探测（--no-network）")
    try:
        resp: Any = requests.get(
            NETWORK_PROBE_URL,
            timeout=timeout,
            headers={"User-Agent": f"zhihu-downloader-doctor/{__version__}"},
        )
        status = int(getattr(resp, "status_code", 0))
    except Exception as e:  # noqa: BLE001 - 探测失败只 warn，不影响其它检查
        return ("warn", "网络",
                f"访问 {NETWORK_PROBE_URL} 失败（{type(e).__name__}: {e}）"
                "→ 请检查网络/代理；离线环境下其它检查仍然有效")
    if 200 <= status < 400:
        return ("ok", "网络", f"www.zhihu.com 可达（HTTP {status}）")
    if status in (403, 429):
        return ("warn", "网络",
                f"www.zhihu.com 返回 HTTP {status}（疑似反爬拦截）→ 请更新 Cookie 并降低限速后重试")
    return ("warn", "网络", f"www.zhihu.com 返回 HTTP {status}")


def _default_state_dir() -> Path:
    """默认断点目录：<默认输出目录>/.zhihu_state。

    DEFAULT_OUTPUT_DIR 常量归 app.server（Web 层、fastapi 可选依赖）所有：
    函数内懒 import（§2.15 同款手法），既不让 auth 反向依赖 app，也不让
    纯 CLI 安装为 doctor 强拉 fastapi；Web 层不可用时回落到同一公式的路径。
    """
    try:
        from ..app.server import DEFAULT_OUTPUT_DIR  # noqa: PLC0415 - 懒 import，避免层倒挂
    except Exception:  # noqa: BLE001 - Web 依赖缺失属正常部署形态（只用 CLI）
        return Path.home() / ".zhihu_downloader" / "output" / DEFAULT_STATE_SUBDIR
    return Path(DEFAULT_OUTPUT_DIR) / DEFAULT_STATE_SUBDIR


def _fmt_bytes(total: int) -> str:
    """人话字节数：B 取整，KB/MB 保留一位小数。"""
    if total >= 1024 * 1024:
        return f"{total / 1024 / 1024:.1f} MB"
    if total >= 1024:
        return f"{total / 1024:.1f} KB"
    return f"{total} B"


def _check_disk_usage(state_dir: Path) -> Check:
    """磁盘占用（info 级；S3 接线：CheckpointStore.total_bytes 汇总 state_dir）。

    R1-M4 之后断点成功后保留（支持追更 diff），占用随书架增长——超 500MB 时
    给出 prune 路径：书架移除不再追更的书。纯观测项：目录不存在按 0 计，
    统计失败降级 info，均不影响 doctor 退出码。
    """
    try:
        # book_key 在 total_bytes 里用不到（整目录 rglob），占位即可。
        total = CheckpointStore(Path(state_dir), "__doctor__").total_bytes()
    except Exception as e:  # noqa: BLE001 - 观测项不得升级任何严重度
        return ("info", "磁盘占用",
                f"无法统计断点缓存占用（{type(e).__name__}: {state_dir}），不影响其他诊断")
    human = _fmt_bytes(total)
    if total > DISK_SOFT_LIMIT_BYTES:
        return ("info", "磁盘占用",
                f"断点缓存 {human}（{state_dir}）已超过 "
                f"{DISK_SOFT_LIMIT_BYTES // 1024 // 1024} MB "
                "→ 可在书架移除不再追更的书以 prune 缓存")
    return ("info", "磁盘占用", f"断点缓存 {human}（{state_dir}），磁盘压力良好")


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

def run_checks(
    cookie_file: str | Path | None = None,
    rate_limit: float | None = None,
    network: bool = True,
    network_timeout: float = 8.0,
    state_dir: str | Path | None = None,
) -> list[Check]:
    """跑一遍全部诊断检查。

    Args:
        cookie_file: Cookie 文件路径；None 用 auth.cookies.DEFAULT_COOKIE_FILE。
        rate_limit: 待检查的限速值（请求/秒）；None 表示"未显式配置"（按默认 2 判定）。
        network: 是否做真实网络探测；测试与 --no-network 传 False。
        network_timeout: 网络探测超时秒数。
        state_dir: 断点缓存目录；None 用默认输出目录下的 .zhihu_state。

    Returns:
        (level, name, message) 列表，顺序为：版本、Python/系统、Cookie 存在
        （+ Cookie 权限）、z_c0、zse_ck、d_c0、签名自检、限速、网络、磁盘占用。
        全部消息为中文且含下一步动作。
    """
    path = Path(cookie_file).expanduser() if cookie_file else cookies.DEFAULT_COOKIE_FILE
    state, data, note = _load_cookie_state(path)
    logged_in = state == "ok"

    results: list[Check] = [_check_version(), _check_python()]
    results.extend(_check_cookie_file(path, state, data, note))
    results.append(_check_key("z_c0", data, logged_in, "登录态凭证，盐选内容必需"))
    results.append(_check_key("zse_ck", data, logged_in, "反爬校验字段，缺失可能导致部分接口失败"))
    results.append(_check_d_c0(data, state))
    results.append(_check_signature(data))
    results.append(_check_rate_limit(rate_limit))
    results.append(_check_network(network, network_timeout))
    results.append(_check_disk_usage(Path(state_dir) if state_dir else _default_state_dir()))
    return results


def has_errors(results: list[Check]) -> bool:
    """是否存在 error 级检查项（CLI 据此决定退出码）。"""
    return any(level == "error" for level, _name, _msg in results)


def count_levels(results: list[Check]) -> dict[str, int]:
    """统计各 level 的数量（CLI 汇总行用）。"""
    counts = {"ok": 0, "warn": 0, "error": 0, "info": 0}
    for level, _name, _msg in results:
        counts[level] = counts.get(level, 0) + 1
    return counts


def format_checks(results: list[Check]) -> str:
    """把检查结果渲染为多行文本（每行 "图标 [名称] 说明"）。"""
    return "\n".join(f"{ICONS.get(level, '•')} [{name}] {msg}" for level, name, msg in results)


def summary_line(results: list[Check]) -> str:
    """汇总行：错误数优先，便于 CLI 直接打印。"""
    counts = count_levels(results)
    if counts["error"]:
        return (f"诊断完成：{counts['error']} 个错误、{counts['warn']} 个警告 "
                f"→ 请按上面标红的条目修复后重试")
    return f"诊断完成：{counts['warn']} 个警告，无错误。"
