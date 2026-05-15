"""知乎盐选小说下载器 - 命令行接口"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional, List, Any

import click

from zhihu_downloader.core.downloader import AsyncDownloader
from zhihu_downloader.parsers.article_parser import ArticleParser, ArticleInfo
from zhihu_downloader.parsers.chapter_classifier import ChapterClassifier
from zhihu_downloader.exporters.txt_exporter import TxtExporter
from zhihu_downloader.exporters.md_exporter import MarkdownExporter
from zhihu_downloader.exporters.epub_exporter import EpubExporter
from zhihu_downloader.exporters.mobi_exporter import MobiExporter
from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.auth.browser_cookie import BrowserCookieFetcher
from zhihu_downloader.utils.config import Config
from zhihu_downloader.utils.checkpoint import CheckpointManager
from zhihu_downloader.utils.content_cleaner import ContentCleaner
from zhihu_downloader.shelf.shelf_manager import ShelfManager


class_colors: dict[str, str] = {
    "normal": "cyan",
    "extra": "yellow",
    "author_note": "magenta",
    "unknown": "white",
}


@click.group(help="知乎盐选小说下载器 - 支持批量下载、书架管理、多格式导出")
def cli() -> None:
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
    url: Optional[str],
    batch_file: Optional[str],
    cookie_file: Optional[str],
    auto_cookie: bool,
    token: Optional[str],
    output_dir: str,
    export_format: str,
    list_only: bool,
    max_concurrent: int,
    rate_limit: float,
    config: Optional[str],
    no_clean: bool,
    resume: bool,
    update_check: bool,
) -> None:
    """下载小说命令"""
    if not url and not batch_file:
        click.echo("❌ 请提供 --url 或 --batch-file 参数")
        sys.exit(1)

    urls: List[str] = []
    if url:
        urls.append(url)
    if batch_file:
        with open(batch_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)

    asyncio.run(
        _async_download(
            urls=urls,
            cookie_file=cookie_file,
            auto_cookie=auto_cookie,
            token=token,
            output_dir=output_dir,
            export_format=export_format,
            list_only=list_only,
            max_concurrent=max_concurrent,
            rate_limit=rate_limit,
            config=config,
            no_clean=no_clean,
            resume=resume,
            update_check=update_check,
        )
    )


@cli.command(name="shelf", help="书架管理")
@click.option("--list", "-l", "list_books", is_flag=True, help="列出书架中的书籍")
@click.option("--add", help="添加书籍到书架")
@click.option("--remove", help="从书架移除书籍")
@click.option("--update-all", is_flag=True, help="更新书架中所有书籍")
@click.option("--clean", is_flag=True, help="清理书架缓存")
def shelf_command(
    list_books: bool,
    add: Optional[str],
    remove: Optional[str],
    update_all: bool,
    clean: bool,
) -> None:
    """书架管理命令"""
    shelf = ShelfManager()

    if list_books:
        books = shelf.list_books()
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

    elif add:
        shelf.add_book(add)
        click.echo(f"✅ 已添加到书架: {add}")

    elif remove:
        shelf.remove_book(remove)
        click.echo(f"✅ 已从书架移除: {remove}")

    elif update_all:
        asyncio.run(_async_update_shelf(shelf))

    elif clean:
        shelf.clean_cache()
        click.echo("✅ 已清理书架缓存")

    else:
        click.echo("❌ 请提供操作参数 (-l, --add, --remove, --update-all, --clean)")


async def _async_download(
    urls: List[str],
    cookie_file: Optional[str],
    auto_cookie: bool,
    token: Optional[str],
    output_dir: str,
    export_format: str,
    list_only: bool,
    max_concurrent: int,
    rate_limit: float,
    config: Optional[str],
    no_clean: bool,
    resume: bool,
    update_check: bool,
) -> None:
    """异步下载主函数"""

    click.echo("📚 知乎盐选小说下载器")
    click.echo("=" * 50)

    cfg = Config(config) if config else Config()
    cfg.set("max_concurrent", max_concurrent)
    cfg.set("rate_limit", rate_limit)
    cfg.set("output_dir", output_dir)
    cfg.set("clean_content", not no_clean)

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

    cookies = cookie_mgr.get_cookies()

    downloader = AsyncDownloader(
        max_concurrent=max_concurrent,
        rate_limit=rate_limit,
        cookies=cookies,
    )

    shelf = ShelfManager()

    try:
        for idx, url in enumerate(urls, 1):
            click.echo(f"\n{'='*50}")
            click.echo(f"📖 正在处理 [{idx}/{len(urls)}]: {url}")
            click.echo(f"{'='*50}")

            await _download_single_book(
                url=url,
                downloader=downloader,
                cfg=cfg,
                output_dir=output_dir,
                export_format=export_format,
                list_only=list_only,
                resume=resume,
                update_check=update_check,
                shelf=shelf,
            )

    finally:
        await downloader.close()


async def _download_single_book(
    url: str,
    downloader: AsyncDownloader,
    cfg: Config,
    output_dir: str,
    export_format: str,
    list_only: bool,
    resume: bool,
    update_check: bool,
    shelf: ShelfManager,
) -> None:
    """下载单本书"""
    try:
        click.echo(f"\n🔍 正在获取内容: {url}")

        html = await downloader.fetch(url)
        parser = ArticleParser()
        article_info = parser.parse_article_info(html)

        click.echo(f"\n📖 《{article_info.title}》")
        click.echo(f"   作者: {article_info.author}")
        click.echo(f"   章节数: {article_info.chapter_count}")

        if update_check:
            existing_info = shelf.get_book(url)
            if existing_info:
                existing_chapters = existing_info.get("chapter_count", 0)
                if article_info.chapter_count > existing_chapters:
                    new_count = article_info.chapter_count - existing_chapters
                    click.echo(f"🔄 发现更新！新增 {new_count} 章节")
                else:
                    click.echo("✅ 已是最新版本，无需更新")
                    return

        if list_only:
            _print_chapters(article_info.chapters)
            return

        checkpoint_mgr = CheckpointManager(output_dir, article_info.title)
        downloaded_ids: set[str] = set()

        if resume:
            checkpoint_file = checkpoint_mgr.get_checkpoint_file()
            if checkpoint_file.exists():
                downloaded_ids = checkpoint_mgr.load_checkpoint()
                click.echo(f"\n📍 断点续传: 已下载 {len(downloaded_ids)} 章节")

        chapters_to_download = [
            ch for ch in article_info.chapters
            if ch.id not in downloaded_ids
        ]

        if not chapters_to_download:
            click.echo("\n✅ 所有章节已下载完成！")
        else:
            click.echo(f"\n📥 开始下载 {len(chapters_to_download)} 个章节...")

            cleaner = ContentCleaner() if cfg.get("clean_content") else None
            classifier = ChapterClassifier()

            for i, chapter in enumerate(chapters_to_download, 1):
                chapter_url = chapter.url
                click.echo(f"  [{i}/{len(chapters_to_download)}] {chapter.title}...", nl=False)

                try:
                    chapter_html = await downloader.fetch(chapter_url)
                    chapter_content = parser.parse_chapter_content(chapter_html)

                    if cleaner:
                        chapter_content = cleaner.clean(chapter_content)

                    chapter_type = classifier.classify(chapter.title)
                    chapter.type = chapter_type
                    chapter.content = chapter_content

                    downloaded_ids.add(chapter.id)
                    if resume:
                        checkpoint_mgr.save_checkpoint(downloaded_ids)

                    click.echo(" ✓")

                except Exception as e:
                    click.echo(f" ✗ ({e})")

            click.echo(f"\n✅ 下载完成！共 {len(downloaded_ids)} 章节")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        exporters: dict[str, Any] = {
            "txt": TxtExporter(output_path),
            "md": MarkdownExporter(output_path),
            "epub": EpubExporter(output_path),
            "mobi": MobiExporter(output_path),
        }

        if export_format == "all":
            for fmt, exporter in exporters.items():
                click.echo(f"\n📦 导出 {fmt.upper()}...", nl=False)
                exporter.export(article_info.to_dict())
                click.echo(" ✓")
        else:
            click.echo(f"\n📦 导出 {export_format.upper()}...", nl=False)
            exporters[export_format].export(article_info.to_dict())
            click.echo(" ✓")

        click.echo(f"\n🎉 完成！文件保存在: {output_path.absolute()}")

        shelf.add_book(url, article_info.to_dict())

    except Exception as e:
        click.echo(f"\n❌ 下载失败: {e}")


async def _async_update_shelf(shelf: ShelfManager) -> None:
    """更新书架中所有书籍"""
    books = shelf.list_books()
    if not books:
        click.echo("📚 书架为空")
        return

    click.echo(f"🔄 正在更新书架中的 {len(books)} 本书...")

    cookie_mgr = CookieManager()
    try:
        cookies = BrowserCookieFetcher.fetch_zhihu_cookies()
        if cookies:
            cookie_mgr.load_from_dict(cookies)
    except Exception:
        pass

    downloader = AsyncDownloader(
        max_concurrent=3,
        rate_limit=2.0,
        cookies=cookie_mgr.get_cookies(),
    )

    try:
        for book in books:
            url = book.get("url")
            if not url:
                continue

            click.echo(f"\n📖 检查: {book.get('title', '未知')}")
            try:
                html = await downloader.fetch(url)
                parser = ArticleParser()
                info = parser.parse_article_info(html)

                existing_count = book.get("chapter_count", 0)
                if info.chapter_count > existing_count:
                    new_chapters = info.chapter_count - existing_count
                    click.echo(f"   ⬆️  发现 {new_chapters} 个新章节")
                    await _download_single_book(
                        url=url,
                        downloader=downloader,
                        cfg=Config(),
                        output_dir="./output",
                        export_format="md",
                        list_only=False,
                        resume=True,
                        update_check=False,
                        shelf=shelf,
                    )
                else:
                    click.echo("   ✅ 已是最新")

            except Exception as e:
                click.echo(f"   ❌ 检查失败: {e}")

    finally:
        await downloader.close()


def _print_chapters(chapters: list) -> None:
    """打印章节列表"""
    click.echo("\n📑 章节列表:")
    click.echo("-" * 50)

    classifier = ChapterClassifier()

    for ch in chapters:
        ch_type = classifier.classify(ch.title)
        type_label: dict[str, str] = {
            "normal": "正文",
            "extra": "番外",
            "author_note": "作者说",
            "unknown": "其他",
        }.get(ch_type, "其他")

        click.echo(f"  [{type_label}] {ch.title}")


if __name__ == "__main__":
    cli()
