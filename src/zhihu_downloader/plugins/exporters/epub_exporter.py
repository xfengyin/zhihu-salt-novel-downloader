"""EPUB导出器插件"""

from __future__ import annotations

from pathlib import Path

import pluggy

from zhihu_downloader.exporters.epub_exporter import EpubExporter
from zhihu_downloader.parsers.article_parser import ArticleInfo
from zhihu_downloader.plugins.protocol import ExporterPlugin

hookimpl = pluggy.HookimplMarker("zhihu_downloader")


class EpubExporterPlugin(ExporterPlugin):
    """EPUB导出器插件"""

    @property
    def format(self) -> str:
        return "epub"

    @property
    def ext(self) -> str:
        return ".epub"

    @property
    def mime(self) -> str:
        return "application/epub+zip"

    def export(self, book: ArticleInfo, output_dir: Path) -> Path:
        exporter = EpubExporter(output_dir)
        return exporter.export(book)


@hookimpl
def zsd_register_exporter() -> list[type[ExporterPlugin]]:
    """注册导出器插件"""
    return [EpubExporterPlugin]
