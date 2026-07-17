"""知乎盐选小说下载器 - PyInstaller 入口

PyInstaller 需要一个明确的入口脚本，
这里简单地调用 cli.cli() 以确保所有子命令都被打包。

Windows 控制台默认可能是 cp1252/cp936 编码，
强制 stdout/stderr 使用 UTF-8 以正确显示中文帮助信息。

双击 exe（无参数）默认启动 serve 服务并打开浏览器，
避免用户误以为"纯命令行程序"。
"""

import sys


def _force_utf8_stdio() -> None:
    """强制标准输出/错误流使用 UTF-8 编码

    Windows 控制台默认使用系统 ANSI 代码页（cp1252/cp936），
    会导致中文输出触发 UnicodeEncodeError。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        # 重新配置编码为 UTF-8
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (TypeError, ValueError):
                pass


# 在导入 click 之前强制 UTF-8
_force_utf8_stdio()

from zhihu_downloader.cli import cli  # noqa: E402


def _is_gui_launch() -> bool:
    """判断是否为「双击启动」场景

    PyInstaller 打包后，双击 exe 时 sys.argv 只含 exe 自身路径。
    此场景下默认启动 serve 服务，让用户直接看到 Web 界面，
    而不是 CLI 帮助菜单。
    """
    # 无任何子命令参数
    if len(sys.argv) != 1:
        return False
    # 排除 -h / --help / --version 等显式参数
    return True


if __name__ == "__main__":
    # 双击启动：默认进入 serve 模式，提供完整 Web UI
    # 安全考虑：双击场景仅监听本机回环地址，避免局域网暴露
    if _is_gui_launch():
        sys.argv = [sys.argv[0], "serve", "--host", "127.0.0.1"]
    cli()
