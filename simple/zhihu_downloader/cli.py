"""命令行入口：qr-login / download / web / doctor 四个命令。"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

import requests

from . import __version__
from .client import DEFAULT_COOKIE_FILE, ZhihuClient, ZhihuError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zhihu-downloader",
        description="知乎盐选小说下载器（极简 v4）",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"zhihu-downloader {__version__}",
        help="显示版本号并退出",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("qr-login", help="扫码登录并保存 Cookie")

    p_download = sub.add_parser("download", help="下载盐选章节/专栏")
    p_download.add_argument("--url", required=True, help="盐选章节或专栏 URL")
    p_download.add_argument("--cookie-file", default=None, help="Cookie 文件路径")
    p_download.add_argument("--token", default=None, help="z_c0 token（优先级高于 cookie-file）")
    p_download.add_argument("--output-dir", default=".", help="输出目录")
    p_download.add_argument("--format", default="md", choices=["txt", "md", "epub"])
    p_download.add_argument(
        "--rate-limit",
        type=float,
        default=2.0,
        help="每秒最多请求数（默认 2，最小 0.5），下载时对全部请求生效",
    )

    p_doctor = sub.add_parser("doctor", help="诊断环境/版本/Cookie/限速/网络")
    p_doctor.add_argument(
        "--cookie-file",
        default=None,
        help="自定义 Cookie 文件路径（默认 ~/.zhihu_downloader/cookies.json）",
    )
    p_doctor.add_argument(
        "--rate-limit",
        type=float,
        default=None,
        help="检查指定的限速值（默认 2 请求/秒）",
    )
    p_doctor.add_argument("--no-network", action="store_true", help="跳过网络探测")
    p_doctor.add_argument("--network-timeout", type=float, default=8.0, help="网络探测超时秒数（默认 8）")

    p_web = sub.add_parser("web", help="启动 Web API")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=3000)
    return parser


def cmd_qr_login(client: ZhihuClient) -> int:
    """扫码登录：保存二维码到临时文件并轮询，成功后保存 Cookie。"""
    try:
        info = client.login_qr_start()
        token = info["token"]
    except ZhihuError as e:
        print(f"登录失败: {e}", file=sys.stderr)
        return 1

    image = client.login_qr_image(token)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(image)
        qr_path = f.name

    print(f"请用知乎 APP 扫码登录，二维码图片路径: {qr_path}")
    print("等待扫码确认中...")

    try:
        while True:
            result = client.login_qr_poll(token)
            status = result["status"]
            if status == "confirmed":
                saved = client.save_cookies()
                print(f"登录成功 user_id={result['user_id']}，Cookie 已保存到 {saved}")
                return 0
            if status == "error":
                print(f"登录失败: {result.get('error')}", file=sys.stderr)
                return 1
            if status == "expired":
                print("二维码已过期，请重新运行 qr-login", file=sys.stderr)
                return 1
            time.sleep(2)
    except ZhihuError as e:
        print(f"登录失败: {e}", file=sys.stderr)
        return 1


def cmd_download(client: ZhihuClient, args: argparse.Namespace) -> int:
    if args.cookie_file:
        client.load_cookies(args.cookie_file)
    if args.token:
        client.load_cookies({"z_c0": args.token})

    # 限速下限保护：最小 0.5 请求/秒（间隔不超过 2s）
    rate_limit = max(args.rate_limit, 0.5)

    try:
        result = client.download(
            args.url,
            fmt=args.format,
            output_dir=args.output_dir,
            rate_limit=rate_limit,
        )
    except ZhihuError as e:
        print(f"下载失败: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - 解析/导出错误统一提示
        print(f"下载失败: {e}", file=sys.stderr)
        return 1

    print(f"标题: {result['title']}")
    for f in result["files"]:
        print(f"已导出: {f}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """诊断命令：检查 Python/系统、版本、Cookie、限速、网络。

    输出 ✅ 健康 / ⚠️ 警告 / ❌ 错误 清单；返回非 0 表示存在错误。
    无 Cookie 只告警不报错（首次使用属正常状态）。
    """
    results: list[tuple[str, str, str]] = []  # (level, 检查项, 说明)
    icons = {"ok": "✅", "warn": "⚠️", "error": "❌", "info": "ℹ️"}

    results.append(("info", "版本", f"zhihu-downloader {__version__}"))

    # Python / 系统
    py_ver = sys.version.split()[0]
    sys_desc = f"Python {py_ver}，{platform.system()} {platform.release()}"
    if sys.version_info < (3, 10):
        results.append(("error", "Python/系统", f"{sys_desc}（需要 >= 3.10）"))
    else:
        results.append(("ok", "Python/系统", sys_desc))

    # Cookie 文件
    cookie_file = Path(args.cookie_file) if args.cookie_file else DEFAULT_COOKIE_FILE
    if not cookie_file.exists():
        results.append(("warn", "Cookie", f"Cookie 文件不存在: {cookie_file}（请先运行 qr-login）"))
    else:
        try:
            data = json.loads(cookie_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("内容不是 JSON 对象")
        except (OSError, ValueError, json.JSONDecodeError) as e:
            results.append(("error", "Cookie", f"Cookie 文件无法解析: {cookie_file}（{e}）"))
        else:
            missing = [k for k in ("z_c0", "zse_ck") if k not in data]
            if missing:
                results.append(
                    ("warn", "Cookie", f"Cookie 缺少关键字段: {', '.join(missing)}（建议重新 qr-login）")
                )
            else:
                results.append(("ok", "Cookie", f"Cookie 有效（含 z_c0/zse_ck）: {cookie_file}"))

    # 限速设置
    rate_limit = args.rate_limit if getattr(args, "rate_limit", None) is not None else 2.0
    if rate_limit <= 0:
        results.append(("warn", "限速", "限速未启用（rate_limit<=0），建议保持默认 2 请求/秒"))
    elif rate_limit < 0.5:
        results.append(("warn", "限速", f"rate_limit={rate_limit} 低于最小建议 0.5，可能触发反爬"))
    elif rate_limit > 5:
        results.append(("warn", "限速", f"rate_limit={rate_limit} 偏高（>5），请勿用于规避平台限制"))
    else:
        results.append(("ok", "限速", f"rate_limit={rate_limit} 请求/秒（默认 2，合理）"))

    # 网络探测（可选）
    if args.no_network:
        results.append(("info", "网络", "已跳过网络探测（--no-network）"))
    else:
        try:
            resp = requests.get(
                "https://www.zhihu.com",
                timeout=args.network_timeout,
                headers={"User-Agent": "Mozilla/5.0 (doctor)"},
            )
            if resp.status_code == 200:
                results.append(("ok", "网络", "www.zhihu.com 可达（HTTP 200）"))
            else:
                results.append(("warn", "网络", f"www.zhihu.com 返回 HTTP {resp.status_code}"))
        except requests.RequestException as e:
            results.append(("warn", "网络", f"网络探测失败: {e}（离线环境不影响其它检查）"))

    for level, name, msg in results:
        print(f"{icons[level]} [{name}] {msg}")

    errors = sum(1 for lv, _, _ in results if lv == "error")
    warns = sum(1 for lv, _, _ in results if lv == "warn")
    if errors:
        print(f"\n诊断完成：{errors} 个错误、{warns} 个警告 → 请修复后重试（exit {1 if errors else 0}）", file=sys.stderr)
    else:
        print(f"\n诊断完成：{warns} 个警告，无错误。")
    return 1 if errors else 0


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    from .webapp import create_app

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    # PyInstaller 冻结的 Windows 程序默认 stdout 可能是 cp1252，
    # 中文 help 会触发 UnicodeEncodeError；这里强制 UTF-8 输出。
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "qr-login":
        return cmd_qr_login(ZhihuClient())
    if args.command == "download":
        return cmd_download(ZhihuClient(), args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "web":
        return cmd_web(args)
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
