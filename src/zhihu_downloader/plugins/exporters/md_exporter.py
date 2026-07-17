"""Markdown导出器插件"""

from __future__ import annotations

from pathlib import Path

import pluggy

from zhihu_downloader.exporters.md_exporter import MarkdownExporter
from zhihu_downloader.parsers.article_parser import ArticleInfo
from zhihu_downloader.plugins.protocol import ExporterPlugin

hookimpl = pluggy.HookimplMarker("zhihu_downloader")


class MdExporterPlugin(ExporterPlugin):
    """Markdown导出器插件"""

    @property
    def format(self) -> str:
        return "md"

    @property
    def ext(self) -> str:
        return ".md"

    @property
    def mime(self) -> str:
        return "text/markdown"

    def export(self, book: ArticleInfo, output_dir: Path) -> Path:
        exporter = MarkdownExporter(output_dir)
        return exporter.export(book)


@hookimpl
def zsd_register_exporter() -> list[type[ExporterPlugin]]:
    """注册导出器插件"""
    return [MdExporterPlugin]
