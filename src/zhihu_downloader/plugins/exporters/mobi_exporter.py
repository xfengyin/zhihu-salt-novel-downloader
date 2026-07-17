"""MOBI导出器插件"""

from __future__ import annotations

from pathlib import Path

import pluggy

from zhihu_downloader.exporters.mobi_exporter import MobiExporter
from zhihu_downloader.parsers.article_parser import ArticleInfo
from zhihu_downloader.plugins.protocol import ExporterPlugin

hookimpl = pluggy.HookimplMarker("zhihu_downloader")


class MobiExporterPlugin(ExporterPlugin):
    """MOBI导出器插件"""

    @property
    def format(self) -> str:
        return "mobi"

    @property
    def ext(self) -> str:
        return ".mobi"

    @property
    def mime(self) -> str:
        return "application/x-mobipocket-ebook"

    def export(self, book: ArticleInfo, output_dir: Path) -> Path:
        exporter = MobiExporter(output_dir)
        return exporter.export(book)


@hookimpl
def zsd_register_exporter() -> list[type[ExporterPlugin]]:
    """注册导出器插件"""
    return [MobiExporterPlugin]
