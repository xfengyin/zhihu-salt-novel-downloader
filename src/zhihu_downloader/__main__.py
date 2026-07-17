"""知乎盐选小说下载器 - PyInstaller 入口

PyInstaller 需要一个明确的入口脚本，
这里简单地调用 cli.cli() 以确保所有子命令都被打包。

Windows 控制台默认可能是 cp1252/cp936 编码，
强制 stdout/stderr 使用 UTF-8 以正确显示中文帮助信息。
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

if __name__ == "__main__":
    cli()
