"""命令行入口：qr-login / download / web 三个命令。"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

from .client import ZhihuClient, ZhihuError


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zhihu-downloader",
        description="知乎盐选小说下载器（极简 v4）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("qr-login", help="扫码登录并保存 Cookie")

    p_download = sub.add_parser("download", help="下载盐选章节/专栏")
    p_download.add_argument("--url", required=True, help="盐选章节或专栏 URL")
    p_download.add_argument("--cookie-file", default=None, help="Cookie 文件路径")
    p_download.add_argument("--token", default=None, help="z_c0 token（优先级高于 cookie-file）")
    p_download.add_argument("--output-dir", default=".", help="输出目录")
    p_download.add_argument("--format", default="md", choices=["txt", "md", "epub"])

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

    try:
        result = client.download(args.url, fmt=args.format, output_dir=args.output_dir)
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


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    from .webapp import create_app

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "qr-login":
        return cmd_qr_login(ZhihuClient())
    if args.command == "download":
        return cmd_download(ZhihuClient(), args)
    if args.command == "web":
        return cmd_web(args)
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
