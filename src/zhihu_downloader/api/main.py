"""FastAPI 服务启动入口

支持 `python -m zhihu_downloader.api.main` 直接启动，
也支持 `uv run python -m zhihu_downloader.api.main`。
免去手敲 uvicorn 长命令。
"""

from __future__ import annotations

import uvicorn

from zhihu_downloader.api.app import create_app

# 模块级 app 实例，兼容 `uvicorn zhihu_downloader.api.main:app` 写法
app = create_app()


def main() -> None:
    """启动 FastAPI 服务，默认 0.0.0.0:8000，开启热重载"""
    uvicorn.run(
        "zhihu_downloader.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
