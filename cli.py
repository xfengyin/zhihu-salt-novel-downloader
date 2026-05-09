#!/usr/bin/env python3
"""知乎盐选小说下载器 - 命令行接口"""

import sys
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import logging

import click

from core.downloader import AsyncDownloader
from parsers.article_parser import ArticleParser, Chapter
from parsers.chapter_classifier import ChapterClassifier
from exporters.txt_exporter import TxtExporter
from exporters.md_exporter import MarkdownExporter
from exporters.epub_exporter import EpubExporter
from auth.cookie_manager import CookieManager
from utils.config import Config
from utils.checkpoint import CheckpointManager
from utils.content_cleaner import ContentCleaner
from utils.exceptions import DownloaderError, RateLimitError, AuthenticationError


class_colors = {
    'normal': 'cyan',
    'extra': 'yellow',
    'author_note': 'magenta',
    'unknown': 'white'
}


@click.command()
@click.option('--url', '-u', required=True, help='知乎盐选小说URL')
@click.option('--cookie-file', '-c', type=click.Path(exists=True), help='Cookie JSON文件路径')
@click.option('--token', '-t', help='z_c0 token值')
@click.option('--output-dir', '-o', default='./output', help='输出目录')
@click.option('--format', '-f', 'export_format', type=click.Choice(['txt', 'md', 'epub', 'all']),
              default='md', help='导出格式')
@click.option('--list-only', is_flag=True, help='仅列出章节，不下载')
@click.option('--max-concurrent', '-n', default=3, help='最大并发数')
@click.option('--rate-limit', '-r', default=2, help='每秒请求数')
@click.option('--config', type=click.Path(exists=True), help='配置文件路径')
@click.option('--no-clean', is_flag=True, help='不清理内容（保留广告水印）')
@click.option('--resume', is_flag=True, help='启用断点续传')
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
    resume: bool
):
    """知乎盐选小说下载器 - 支持异步下载与多格式导出"""
    asyncio.run(_async_main(
        url, cookie_file, token, output_dir, export_format,
        list_only, max_concurrent, rate_limit, config, no_clean, resume
    ))


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
    resume: bool
):
    """异步主函数 - 支持真正的并发下载"""

    click.echo("📚 知乎盐选小说下载器")
    click.echo("=" * 50)

    cfg = Config(config) if config else Config()
    cfg.set('max_concurrent', max_concurrent)
    cfg.set('rate_limit', rate_limit)
    cfg.set('output_dir', output_dir)
    cfg.set('clean_content', not no_clean)

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
        max_retries=cfg.get('download.max_retries', 3),
        retry_delay=cfg.get('download.retry_delay', 1.0),
        timeout=cfg.get('download.timeout', 30)
    )

    try:
        click.echo(f"\n🔍 正在获取内容: {url}")

        html = await downloader.fetch(url)
        parser = ArticleParser()
        article_info = parser.parse_article_info(html)

        click.echo(f"\n📖 《{article_info['title']}》")
        click.echo(f"   作者: {article_info.get('author', '未知')}")
        click.echo(f"   章节数: {len(article_info.get('chapters', []))}")

        if list_only:
            _print_chapters(article_info['chapters'])
            return

        checkpoint_mgr = CheckpointManager(output_dir, article_info['title'])
        downloaded_ids: set = set()

        if resume:
            checkpoint_file = checkpoint_mgr.get_checkpoint_file()
            if checkpoint_file.exists():
                downloaded_ids = checkpoint_mgr.load_checkpoint()
                click.echo(f"\n📍 断点续传: 已下载 {len(downloaded_ids)} 章节")

        chapters_to_download = [
            ch for ch in article_info['chapters']
            if (getattr(ch, 'id', None) or str(ch.get('id', ''))) not in downloaded_ids
        ]

        if not chapters_to_download:
            click.echo("\n✅ 所有章节已下载完成！")
        else:
            click.echo(f"\n📥 开始下载 {len(chapters_to_download)} 个章节（并发数: {max_concurrent}）...")

            cleaner = ContentCleaner() if cfg.get('clean_content') else None
            classifier = ChapterClassifier()

            semaphore = asyncio.Semaphore(max_concurrent)

            async def download_chapter(chapter: Chapter, index: int, total: int) -> Tuple[Chapter, Optional[str]]:
                async with semaphore:
                    chapter_url = getattr(chapter, 'url', None) or chapter.get('url', '')
                    chapter_title = getattr(chapter, 'title', None) or chapter.get('title', '未知章节')
                    chapter_id = getattr(chapter, 'id', None) or chapter.get('id', '')

                    click.echo(f"  [{index}/{total}] {chapter_title}...", nl=False)

                    try:
                        chapter_html = await downloader.fetch_with_retry(chapter_url)
                        chapter_content = parser.parse_chapter_content(chapter_html)

                        if cleaner:
                            chapter_content = cleaner.clean(chapter_content)

                        chapter_type = classifier.classify(chapter_title)
                        chapter_type_str = chapter_type if isinstance(chapter_type, str) else 'normal'

                        if hasattr(chapter, 'type'):
                            chapter.type = chapter_type_str
                        else:
                            chapter['type'] = chapter_type_str

                        if hasattr(chapter, 'content'):
                            chapter.content = chapter_content
                        else:
                            chapter['content'] = chapter_content

                        click.echo(" ✓")
                        return (chapter, None)

                    except RateLimitError as e:
                        click.echo(f" ⚠️ 速率限制 ({e})")
                        return (chapter, str(e))
                    except AuthenticationError as e:
                        click.echo(f" 🔐 认证失败 ({e})")
                        return (chapter, str(e))
                    except Exception as e:
                        click.echo(f" ✗ ({e})")
                        return (chapter, str(e))

            tasks = [
                download_chapter(ch, i, len(chapters_to_download))
                for i, ch in enumerate(chapters_to_download, 1)
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logging.error(f"下载任务异常: {result}")
                    continue

                chapter, error = result
                chapter_id = getattr(chapter, 'id', None) or chapter.get('id', '')

                if chapter_id:
                    downloaded_ids.add(chapter_id)
                    if resume:
                        checkpoint_mgr.save_checkpoint(downloaded_ids)

            success_count = sum(1 for _, err in results if err is None and not isinstance(err, Exception))
            fail_count = len(chapters_to_download) - success_count

            click.echo(f"\n✅ 下载完成！成功: {success_count}, 失败: {fail_count}")

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        exporters = {
            'txt': TxtExporter(output_path),
            'md': MarkdownExporter(output_path),
            'epub': EpubExporter(output_path)
        }

        if export_format == 'all':
            for fmt, exporter in exporters.items():
                click.echo(f"\n📦 导出 {fmt.upper()}...", nl=False)
                exporter.export(article_info)
                click.echo(" ✓")
        else:
            click.echo(f"\n📦 导出 {export_format.upper()}...", nl=False)
            exporters[export_format].export(article_info)
            click.echo(" ✓")

        click.echo(f"\n🎉 完成！文件保存在: {output_path.absolute()}")

        cache_stats = downloader.get_cache_stats()
        if cache_stats.get('total_requests', 0) > 0:
            click.echo(f"\n📊 缓存统计: {cache_stats}")

    finally:
        await downloader.close()


def _print_chapters(chapters: List) -> None:
    """打印章节列表"""
    click.echo("\n📑 章节列表:")
    click.echo("-" * 50)

    classifier = ChapterClassifier()

    for ch in chapters:
        title = getattr(ch, 'title', None) or ch.get('title', '未知章节')
        ch_type = classifier.classify(title)
        type_label = {
            'normal': '正文',
            'extra': '番外',
            'author_note': '作者说',
            'unknown': '其他'
        }.get(ch_type, '其他')

        click.echo(f"  [{type_label}] {title}")


if __name__ == '__main__':
    main()
