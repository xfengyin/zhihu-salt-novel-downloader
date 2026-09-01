"""Cookie 管理：加载/保存/解析/登出。

支持三种输入格式：
1. JSON 对象 {"z_c0": "...", "d_c0": "..."}
2. Netscape cookies.txt（7 列，含 #HttpOnly_ 前缀）
3. 原始 Cookie 串 "k=v; k2=v2"

安全：落盘权限 0600（O_CREAT|O_EXCL 创建瞬间生效，无 chmod 竞态窗口），
原子写（pid+tid 唯一 .tmp + os.replace）。
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from ..errors import AuthError

DEFAULT_COOKIE_FILE = Path.home() / ".zhihu_downloader" / "cookies.json"

#: 签名与权限相关的关键 Cookie（doctor 与 UI 展示用）
KEY_COOKIES = ("z_c0", "zse_ck", "d_c0")


def parse_cookie_string(text: str) -> dict[str, str]:
    """解析 "k=v; k2=v2" 形式的原始 Cookie 串。"""
    result: dict[str, str] = {}
    for part in text.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            key, value = key.strip(), value.strip()
            if key and value:
                result[key] = value
    return result


def parse_content(text: str) -> dict[str, str]:
    """自动识别并解析 Cookie 内容（JSON / Netscape / name=value）。"""
    stripped = text.strip()
    if not stripped:
        raise AuthError("Cookie 内容为空")

    # JSON（对象接受；数组/标量明确拒绝，不得落入行解析器）
    if stripped.startswith(("{", "[")):
        try:
            data: Any = json.loads(stripped)
        except json.JSONDecodeError as e:
            raise AuthError(f"Cookie JSON 解析失败: {e}") from e
        if not isinstance(data, dict):
            raise AuthError("Cookie JSON 必须是对象（name -> value）")
        return {str(k): str(v) for k, v in data.items() if k and v}

    # Netscape / 行式
    cookies: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        if line.startswith("#"):
            continue
        parts = line.split("	")
        if len(parts) >= 7:
            # domain flag path secure expiry name value
            if parts[5] and parts[6]:
                cookies[parts[5]] = parts[6]
            continue
        cookies.update(parse_cookie_string(line))
    if not cookies:
        raise AuthError("无法从内容中解析出任何 Cookie（支持 JSON / cookies.txt / 原始串）")
    return cookies


def load(source: str | Path | dict[str, str]) -> dict[str, str]:
    """加载 Cookie：dict 直接返回；路径读文件后解析。"""
    if isinstance(source, dict):
        return dict(source)
    path = Path(source).expanduser()
    if not path.exists():
        raise AuthError(f"Cookie 文件不存在: {path}（可先运行 zhihu-downloader login 扫码登录）")
    try:
        return parse_content(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise AuthError(f"读取 Cookie 文件失败: {path}（{e}）") from e


def _tmp_name(path: Path) -> str:
    """并发安全的临时文件名：带 pid + 线程 id，避免多写者互相覆盖。

    同 engine/checkpoint.py 的 _tmp_name 思路（R1 审查 M1）：固定 tmp 名下，
    线程 A 的 os.replace 会把线程 B 刚创建的同名 tmp 一并"搬走"，B 随后
    裸抛 FileNotFoundError；唯一名让每个写者只可能动自己的文件。
    """
    return f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"


def _open_private(tmp: Path) -> int:
    """以 0600 独占创建临时文件并返回 fd（R2 审计 #8）。

    权限在**创建瞬间**生效（O_CREAT 的 mode 参数），不存在"先以 umask
    落盘、后 chmod"的竞态窗口；O_EXCL 拒绝复用/截断任何已存在文件——
    配合唯一 tmp 名，冲突只剩"同名文件被恶意预置"一种可能，直接让它
    冒泡成 AuthError 也**绝不 unlink 别人的文件**（旧实现的清理重试
    在并发下会删掉另一个线程正在写的 tmp，正是 M1 的炸点之一）。
    mode 只会被 umask 做减法，任何 umask 下结果都不会宽于 0600。
    """
    return os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)


def save(cookies: dict[str, str], path: str | Path | None = None) -> Path:
    """保存 Cookie（0600、原子写、并发安全），返回路径。

    以 pid+tid 唯一名的 .tmp 独占创建写入，fchmod 兜底（个别文件系统忽略
    open mode），再 os.replace 原子替换目标——目标从不存在"全局可读"的
    中间态，任何一步的 OSError 都包装成中文 AuthError（QR 轮询路径经
    server 透传时不得漏裸异常）。Windows 权限语义弱，由 doctor 给 info 提示。

    Raises:
        AuthError: 目录不可建/磁盘满/权限不足等落盘失败（中文，含下一步）。
    """
    target = Path(path) if path else DEFAULT_COOKIE_FILE
    payload = json.dumps(cookies, ensure_ascii=False, indent=2)
    tmp = target.parent / _tmp_name(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = _open_private(tmp)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                try:
                    os.fchmod(handle.fileno(), 0o600)  # 兜底：忽略 open mode 的文件系统
                except (OSError, AttributeError):  # pragma: no cover - FAT/网络盘或 Windows
                    pass
                handle.write(payload)
        except BaseException:
            # 写失败也要清掉**自己的**半成品，不给后续进程留可读的明文残片。
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, target)
    except OSError as e:
        try:
            tmp.unlink(missing_ok=True)  # 唯一名，不可能误伤他人正在写的 tmp
        except OSError:  # 清理失败（如父路径根本不是目录）不得掩盖原始错误
            pass
        raise AuthError(
            f"保存 Cookie 失败：{target}（{type(e).__name__}: {e}）。"
            "请检查磁盘空间与该目录权限后重试；仍失败可重新扫码登录："
            "zhihu-downloader login"
        ) from e
    return target


def logout(path: str | Path | None = None) -> bool:
    """删除 Cookie 文件；返回本次调用是否实际删除（幂等，R1 审查 m5）。

    不再"先 exists 再 unlink"：exists 与 unlink 之间文件被别人删掉时，
    旧实现裸抛 FileNotFoundError（QR/HTTP 路径会变 500）。直接 unlink，
    FileNotFoundError 视作"已经不在了"→ False，语义与返回值契约不变。
    """
    target = Path(path) if path else DEFAULT_COOKIE_FILE
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    return True
