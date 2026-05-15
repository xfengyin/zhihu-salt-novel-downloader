"""知乎盐选小说下载器 - 命令行接口"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click

from zhihu_downloader.core.downloader import AsyncDownloader
from zhihu_downloader.parsers.article_parser import ArticleParser
from zhihu_downloader.parsers.chapter_classifier import ChapterClassifier
from zhihu_downloader.exporters.txt_exporter import TxtExporter
from zhihu_downloader.exporters.md_exporter import MarkdownExporter
from zhihu_downloader.exporters.epub_exporter import EpubExporter
from zhihu_downloader.auth.cookie_manager import CookieManager
from zhihu_downloader.utils.config import Config
from zhihu_downloader.utils.checkpoint import CheckpointManager
from zhihu_downloader.utils.content_cleaner import ContentCleaner


class_colors: dict[str, str] = {
    "normal": "cyan",
    "extra": "yellow",
    "author_note": "magenta",
    "unknown": "white",
}


@click.command()
@click.option("--url", "-u", required=True, help="知乎盐选小说URL")
@click.option("--cookie-file", "-c", type=click.Path(exists=True), help="Cookie JSON文件路径")
@click.option("--token", "-t", help="z_c0 token值")
@click.option("--output-dir", "-o", default="./output", help="输出目录")
@click.option(
    "--format",
    "-f",
    "export_format",
    type=click.Choice(["txt", "md", "epub", "all"]),
    default="md",
    help="导出格式",
)
@click.option("--list-only", is_flag=True, help="仅列出章节，不下载")
@click.option("--max-concurrent", "-n", default=3, help="最大并发数")
@click.option("--rate-limit", "-r", default=2, help="每秒请求数")
@click.option("--config", type=click.Path(exists=True), help="配置文件路径")
@click.option("--no-clean", is_flag=True, help="不清理内容（保留广告水印）")
@click.option("--resume", is_flag=True, help="启用断点续传")
def main(
    url: str,
    cookie_file: Optional[str],
    token: Optional[str],
    output_dir: str,
    export_format: str,
    list_only: bool,
    max_concurrent: int,
    rate_limit: float,
    config: Optional[str],
    no_clean: bool,
    resume: bool,
) -> None:
    """知乎盐选小说下载器 - 支持异步下载与多格式导出"""
    import asyncio

    asyncio.run(
        _async_main(
            url,
            cookie_file,
            token,
            output_dir,
            export_format,
            list_only,
            max_concurrent,
            rate_limit,
            config,
            no_clean,
            resume,
        )
    )


async def _async_main(
    url: str,
    cookie_file: Optional[str],
    token: Optional[str],
    output_dir: str,
    export_format: str,
    list_only: bool,
    max_concurrent: int,
    rate_limit: float,
    config: Optional[str],
    no_clean: bool,
    resume: bool,
) -> None:
    """异步主函数"""

    click.echo("📚 知乎盐选小说下载器")
    click.echo("=" * 50)

    cfg = Config(config) if config else Config()
    cfg.set("max_concurrent", max_concurrent)
    cfg.set("rate_limit", rate_limit)
    cfg.set("output_dir", output_dir)
    cfg.set("clean_content", not no_clean)

    cookie_mgr = CookieManager()
    if cookie_file:
        cookie_mgr.load_from_file(cookie_file)
    elif token:
        cookie_mgr.set_token(token)
    else:
        click.echo("⚠️  未提供认证信息，仅能访问公开内容")

    cookies = cookie_mgr.get_cookies()

    downloader = AsyncDownloader(
        max_concurrent=max_concurrent,
        rate_limit=rate_limit,
        cookies=cookies,
    )

    try:
        click.echo(f"\n🔍 正在获取内容: {url}")

        html = await downloader.fetch(url)
        parser = ArticleParser()
        article_info = parser.parse_article_info(html)

        click.echo(f"\n📖 《{article_info.title}》")
        click.echo(f"   作者: {article_info.author}")
        click.echo(f"   章节数: {article_info.chapter_count}")

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

        exporters: dict[str, TxtExporter | MarkdownExporter | EpubExporter] = {
            "txt": TxtExporter(output_path),
            "md": MarkdownExporter(output_path),
            "epub": EpubExporter(output_path),
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
