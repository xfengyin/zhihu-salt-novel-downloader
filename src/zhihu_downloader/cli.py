"""知乎盐选小说下载器 - 命令行接口

职责单一：仅负责参数解析、认证装配与进度事件打印。
业务编排统一下沉到 services 层，CLI 与 API 共享同一套 Service。
"""

from __future__ import annotations

import asyncio
import sys

import click
import uvicorn

from zhihu_downloader.auth.browser_cookie import BrowserCookieFetcher
from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.services.download_service import DownloadService
from zhihu_downloader.services.events import ProgressEvent
from zhihu_downloader.services.shelf_service import ShelfService
from zhihu_downloader.utils.config import Config


@click.group(help="知乎盐选小说下载器 - 支持批量下载、书架管理、多格式导出")
def cli() -> None:
    """CLI 入口"""
    pass


@cli.command(name="download", help="下载小说")
@click.option("--url", "-u", help="知乎盐选小说URL")
@click.option("--batch-file", "-b", type=click.Path(exists=True), help="批量下载URL列表文件")
@click.option("--cookie-file", "-c", type=click.Path(exists=True), help="Cookie JSON文件路径")
@click.option("--auto-cookie", is_flag=True, help="自动从浏览器读取Cookie")
@click.option("--token", "-t", help="z_c0 token值")
@click.option("--output-dir", "-o", default="./output", help="输出目录")
@click.option(
    "--format",
    "-f",
    "export_format",
    type=click.Choice(["txt", "md", "epub", "mobi", "all"]),
    default="md",
    help="导出格式",
)
@click.option("--list-only", is_flag=True, help="仅列出章节，不下载")
@click.option("--max-concurrent", "-n", default=3, help="最大并发数")
@click.option("--rate-limit", "-r", default=2, help="每秒请求数")
@click.option("--config", type=click.Path(exists=True), help="配置文件路径")
@click.option("--no-clean", is_flag=True, help="不清理内容（保留广告水印）")
@click.option("--resume", is_flag=True, help="启用断点续传")
@click.option("--update-check", is_flag=True, help="检查章节更新")
def download_command(
    url: str | None,
    batch_file: str | None,
    cookie_file: str | None,
    auto_cookie: bool,
    token: str | None,
    output_dir: str,
    export_format: str,
    list_only: bool,
    max_concurrent: int,
    rate_limit: float,
    config: str | None,
    no_clean: bool,
    resume: bool,
    update_check: bool,
) -> None:
    """下载小说命令"""
    if not url and not batch_file:
        click.echo("❌ 请提供 --url 或 --batch-file 参数")
        sys.exit(1)

    urls: list[str] = []
    if url:
        urls.append(url)
    if batch_file:
        urls.extend(_read_batch_file(batch_file))

    asyncio.run(
        _run_download(
            urls=urls,
            cookie_file=cookie_file,
            auto_cookie=auto_cookie,
            token=token,
            output_dir=output_dir,
            export_format=export_format,
            list_only=list_only,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            config_path=config,
            no_clean=no_clean,
            resume=resume,
            update_check=update_check,
        )
    )


@cli.command(name="serve", help="启动 HTTP API 服务（供前端 / 桌面端调用）")
@click.option("--host", "-h", default="0.0.0.0", help="监听地址")
@click.option("--port", "-p", default=3000, type=int, help="监听端口")
@click.option("--reload", is_flag=True, help="开发模式：热重载")
@click.option("--workers", default=1, type=int, help="工作进程数")
def serve_command(
    host: str,
    port: int,
    reload: bool,
    workers: int,
) -> None:
    """启动 FastAPI 服务"""
    click.echo(f"🚀 启动 HTTP API 服务: http://{host}:{port}")
    click.echo(f"   API 文档: http://{host}:{port}/docs")
    click.echo(f"   OpenAPI: http://{host}:{port}/openapi.json")
    click.echo("   按 Ctrl+C 停止服务")
    uvicorn.run(
        "zhihu_downloader.api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        factory=True,
        log_level="info",
    )


@cli.command(name="shelf", help="书架管理")
@click.option("--list", "-l", "list_books", is_flag=True, help="列出书架中的书籍")
@click.option("--add", help="添加书籍到书架")
@click.option("--remove", help="从书架移除书籍")
@click.option("--update-all", is_flag=True, help="更新书架中所有书籍")
@click.option("--clean", is_flag=True, help="清理书架缓存")
def shelf_command(
    list_books: bool,
    add: str | None,
    remove: str | None,
    update_all: bool,
    clean: bool,
) -> None:
    """书架管理命令"""
    shelf_service = ShelfService()

    if list_books:
        _print_shelf(shelf_service)
    elif add:
        result = shelf_service.add_book(add)
        click.echo(f"{'✅' if result['success'] else '❌'} {result['message']}")
    elif remove:
        result = shelf_service.remove_book(remove)
        click.echo(f"{'✅' if result['success'] else '❌'} {result['message']}")
    elif update_all:
        asyncio.run(_run_update_shelf(shelf_service))
    elif clean:
        result = shelf_service.clean_cache()
        click.echo(f"{'✅' if result['success'] else '❌'} {result['message']}")
    else:
        click.echo("❌ 请提供操作参数 (-l, --add, --remove, --update-all, --clean)")


# ---------------------------------------------------------------------------
# 下载流程装配
# ---------------------------------------------------------------------------


async def _run_download(
    urls: list[str],
    cookie_file: str | None,
    auto_cookie: bool,
    token: str | None,
    output_dir: str,
    export_format: str,
    list_only: bool,
    max_concurrent: int,
    rate_limit: float,
    config_path: str | None,
    no_clean: bool,
    resume: bool,
    update_check: bool,
) -> None:
    """装配认证与配置，驱动 DownloadService 并打印进度"""
    click.echo("📚 知乎盐选小说下载器")
    click.echo("=" * 50)

    cfg = Config(config_path) if config_path else Config()
    # 修复原 cli 的 config 层级错位 bug：统一使用点号 key
    cfg.set("download.max_concurrent", max_concurrent)
    cfg.set("download.rate_limit", rate_limit)
    cfg.set("output.output_dir", output_dir)
    cfg.set("content.clean_content", not no_clean)

    cookie_mgr = _build_cookie_manager(cookie_file, auto_cookie, token)

    service = DownloadService(config=cfg)
    async for event in service.download(
        urls,
        cookie_manager=cookie_mgr,
        output_dir=output_dir,
        export_format=export_format,
        list_only=list_only,
        clean_content=not no_clean,
        resume=resume,
        update_check=update_check,
    ):
        _print_event(event)


async def _run_update_shelf(shelf_service: ShelfService) -> None:
    """驱动书架更新流程"""
    cookie_mgr = _build_cookie_manager(None, True, None)
    download_service = DownloadService()
    async for event in download_service.update_shelf(
        cookie_manager=cookie_mgr,
    ):
        _print_event(event)


# ---------------------------------------------------------------------------
# 认证装配
# ---------------------------------------------------------------------------


def _build_cookie_manager(
    cookie_file: str | None,
    auto_cookie: bool,
    token: str | None,
) -> CookieManager:
    """根据参数装配 CookieManager"""
    cookie_mgr = CookieManager()

    if auto_cookie:
        click.echo("🔍 正在尝试从浏览器读取Cookie...")
        try:
            cookies = BrowserCookieFetcher.fetch_zhihu_cookies()
            if cookies:
                cookie_mgr.load_from_dict(cookies)
                click.echo("✅ Cookie读取成功")
            else:
                click.echo("⚠️  未找到浏览器Cookie，请手动提供")
        except Exception as e:
            click.echo(f"⚠️  Cookie读取失败: {e}")

    if cookie_file:
        cookie_mgr.load_from_file(cookie_file)
    elif token:
        cookie_mgr.set_token(token)
    elif not auto_cookie:
        click.echo("⚠️  未提供认证信息，仅能访问公开内容")

    return cookie_mgr


# ---------------------------------------------------------------------------
# 进度打印
# ---------------------------------------------------------------------------


def _print_event(event: ProgressEvent) -> None:
    """将 ProgressEvent 打印到终端"""
    if event.type == "info":
        click.echo(f"ℹ️  {event.message}")
    elif event.type == "progress":
        click.echo(f"  [{event.downloaded}/{event.total}] {event.current} ✓")
    elif event.type == "export":
        click.echo(f"📦 {event.message}")
    elif event.type == "complete":
        click.echo(f"🎉 {event.message}")
        for f in event.output_files:
            click.echo(f"   📄 {f}")
    elif event.type == "error":
        click.echo(f"❌ {event.message}")


def _print_shelf(shelf_service: ShelfService) -> None:
    """打印书架列表"""
    books = shelf_service.list_books()
    if not books:
        click.echo("📚 书架为空")
        return

    click.echo("📚 我的书架:")
    click.echo("-" * 50)
    for book in books:
        status = "✓" if book.get("completed") else "○"
        click.echo(f"  {status} {book.get('title', '未知标题')}")
        click.echo(f"     作者: {book.get('author', '未知作者')}")
        click.echo(f"     章节: {book.get('chapter_count', 0)}")
        if book.get("last_update"):
            click.echo(f"     更新: {book.get('last_update')}")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _read_batch_file(path: str) -> list[str]:
    """读取批量下载文件，过滤空行与注释"""
    urls: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


if __name__ == "__main__":
    cli()
