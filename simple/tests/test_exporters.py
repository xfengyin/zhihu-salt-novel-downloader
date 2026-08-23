"""exporters 测试 - txt / md / epub 三种格式与文件名安全化。"""

from pathlib import Path

import pytest

from zhihu_downloader.exporters import (
    export,
    export_md,
    export_txt,
    safe_filename,
)

ARTICLES = [
    {
        "title": "第一章 开始",
        "content": "这是第一段。\n这是第二段。",
        "url": "https://www.zhihu.com/market/paid_column/1/section/2",
    },
    {
        "title": "第二章 继续",
        "content": "这是第二章内容。",
        "url": "https://www.zhihu.com/market/paid_column/1/section/3",
    },
]


class TestSafeFilename:
    def test_strip_illegal_chars(self) -> None:
        assert safe_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_empty_fallback(self) -> None:
        assert safe_filename("///") == "zhihu"


class TestExportTxt:
    def test_single_file(self, tmp_path: Path) -> None:
        path = export_txt("我的书", ARTICLES, tmp_path)
        text = Path(path).read_text(encoding="utf-8")
        assert path.endswith(".txt")
        assert "第一章 开始" in text
        assert "这是第一段" in text


class TestExportMd:
    def test_includes_source_link(self, tmp_path: Path) -> None:
        path = export_md("我的书", ARTICLES, tmp_path)
        text = Path(path).read_text(encoding="utf-8")
        assert path.endswith(".md")
        assert "# 第一章 开始" in text
        assert "https://www.zhihu.com/market/paid_column/1/section/2" in text


class TestExportEpub:
    def test_epub_file(self, tmp_path: Path) -> None:
        path = export("我的书", ARTICLES, "epub", tmp_path)
        assert len(path) == 1
        assert path[0].endswith(".epub")
        assert Path(path[0]).exists()
        assert Path(path[0]).stat().st_size > 0


class TestExportDispatch:
    def test_dispatch_and_unknown_format(self, tmp_path: Path) -> None:
        assert len(export("t", ARTICLES, "txt", tmp_path)) == 1
        assert len(export("t", ARTICLES, "md", tmp_path)) == 1
        with pytest.raises(Exception):
            export("t", ARTICLES, "docx", tmp_path)
