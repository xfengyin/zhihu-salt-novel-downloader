"""export 层测试（规格书 §4）：txt/md 结构、epub 读回、identifier 稳定、文件名安全。

全部离线，零网络：EPUB 内嵌图片用测试自己生成的最小 PNG，不访问任何远端地址。
fixture 直接写在本文件内（团队约定：不创建 tests/conftest.py）。
"""

from __future__ import annotations

import hashlib
import os
import struct
import zipfile
import zlib
from pathlib import Path

import ebooklib
import pytest
from ebooklib import epub

from zhihu_downloader.errors import ExportError
from zhihu_downloader.export import FORMATS, export_book
from zhihu_downloader.export.base import book_identifier, resolve_output_dir, safe_filename
from zhihu_downloader.export.epub import BASE_CSS, build_cover_svg
from zhihu_downloader.export.md import render_block
from zhihu_downloader.types import Article, Block

# ----------------------------------------------------------------------
# fixture / helper（本文件私有）
# ----------------------------------------------------------------------


def make_articles() -> list[Article]:
    """构造覆盖全部 Block 类型与三种 chapter_type 的四章数据。"""
    return [
        Article(
            title="第一章 开始",
            url="https://www.zhihu.com/market/paid_column/1/section/2",
            blocks=[
                Block("h2", text="小节标题"),
                Block("p", text="这是第一段。"),
                Block("p", text="这是第二段。"),
                Block("h3", text="三级小标题"),
                Block("li", text="清单甲"),
                Block("li", text="清单乙"),
                Block("quote", text="引用一句话"),
                Block("img", src="https://picx.zhimg.com/remote.png", alt="远程图片"),
            ],
        ),
        Article(
            title="第二章 继续",
            url="https://www.zhihu.com/market/paid_column/1/section/3",
            blocks=[Block("p", text="第二章正文。")],
        ),
        Article(
            title="彩蛋篇",
            url="https://www.zhihu.com/market/paid_column/1/section/4",
            chapter_type="extra",
            blocks=[Block("p", text="番外正文。")],
        ),
        Article(
            title="创作谈",
            url="https://www.zhihu.com/market/paid_column/1/section/5",
            chapter_type="author_note",
            blocks=[Block("p", text="作者说正文。")],
        ),
    ]


def png_bytes(width: int = 2, height: int = 2, rgba: bytes = b"\x10\x20\x30\xff") -> bytes:
    """生成一个真实可解析的最小 RGBA PNG（纯标准库，零网络）。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + rgba * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture()
def articles() -> list[Article]:
    """标准四章：2 正文章 + 1 番外 + 1 作者说。"""
    return make_articles()


@pytest.fixture()
def local_png(tmp_path: Path) -> Path:
    """落一个本地 PNG 文件，供「图片内嵌」分支使用。"""
    target = tmp_path / "assets" / "pic.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png_bytes())
    return target


def export_one(title: str, articles: list[Article], fmt: str, output_dir: Path) -> Path:
    """导出并返回唯一产物 Path。"""
    files = export_book(title, articles, fmt, output_dir)
    assert isinstance(files, list) and len(files) == 1
    return Path(files[0])


def read_epub(path: Path) -> epub.EpubBook:
    """用 ebooklib 读回导出的 EPUB。"""
    return epub.read_epub(str(path))


def zip_names(path: Path) -> set[str]:
    """列出 EPUB 压缩包内的条目名。"""
    with zipfile.ZipFile(path) as zf:
        return set(zf.namelist())


def chapter_body(book: epub.EpubBook, uid: str) -> str:
    """取某章的 XHTML 文本（读回后 get_content 会重建 head，故只断言 body 内容）。"""
    item = book.get_item_with_id(uid)
    assert item is not None, f"缺少章节 {uid}"
    return item.get_content().decode("utf-8")


# ----------------------------------------------------------------------
# base：safe_filename / resolve_output_dir / book_identifier
# ----------------------------------------------------------------------


class TestSafeFilename:
    """文件名安全化边界（移植 v4 行为）。"""

    def test_illegal_chars_become_underscore(self) -> None:
        assert safe_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_all_illegal_falls_back_to_zhihu(self) -> None:
        """非法字符全灭 → 兜底名 zhihu。"""
        assert safe_filename("///") == "zhihu"
        assert safe_filename(':*?"<>|\\\\') == "zhihu"
        assert safe_filename("") == "zhihu"
        assert safe_filename("   ") == "zhihu"
        assert safe_filename("...") == "zhihu"
        assert safe_filename("\r\n\t") == "zhihu"

    def test_whitespace_and_dots(self) -> None:
        assert safe_filename("a\tb") == "a_b"          # 制表符 → 下划线
        assert safe_filename("a  b") == "a b"          # 连续空白折叠
        assert safe_filename("  spaced  ") == "spaced"
        assert safe_filename("trailing...") == "trailing"
        assert safe_filename("书名  带   空格") == "书名 带 空格"

    def test_truncates_when_too_long(self) -> None:
        """超长截断：默认 80，可自定义。"""
        assert len(safe_filename("长" * 200)) == 80
        assert safe_filename("长" * 200, max_len=10) == "长" * 10
        assert safe_filename("abc", max_len=0) == "zhihu"

    def test_no_trailing_dot_after_truncation(self) -> None:
        assert not safe_filename("x" * 79 + ".y", max_len=80).endswith(".")

    def test_ascii_and_cjk_preserved(self) -> None:
        assert safe_filename("Chapter 1 第一章") == "Chapter 1 第一章"

    def test_windows_reserved_device_names(self) -> None:
        """NTFS 保留名守卫（主审 Windows 审计新增）：CON/NUL/COM1 等加下划线前缀。"""
        assert safe_filename("CON") == "_CON"
        assert safe_filename("nul") == "_nul"          # 不区分大小写
        assert safe_filename("COM1") == "_COM1"
        assert safe_filename("LPT9") == "_LPT9"
        assert safe_filename("CON.epub") == "_CON.epub"  # 看点在首段
        assert safe_filename("CON 1984") == "CON 1984"   # 带扩展名段≠裸保留名
        assert safe_filename("CONX") == "CONX"           # 前缀相似不误伤
        # 截断可能截出保留名：守卫必须在截断之后
        assert safe_filename("CON 1984 全集", max_len=3) == "_CON"

    def test_reserved_guard_keeps_nonempty(self) -> None:
        assert safe_filename("AUX") != "AUX"
        assert safe_filename("PRN").startswith("_")


class TestResolveOutputDir:
    """输出目录解析。"""

    def test_creates_nested_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b"
        got = resolve_output_dir(target)
        assert isinstance(got, Path) and got == target and got.is_dir()

    def test_accepts_str_and_is_idempotent(self, tmp_path: Path) -> None:
        assert resolve_output_dir(str(tmp_path)).is_dir()
        assert resolve_output_dir(str(tmp_path)).is_dir()


class TestBookIdentifier:
    """identifier 必须是 sha1 十六进制且稳定（不用 hash()）。"""

    def test_sha1_of_title_and_first_url(self, articles: list[Article]) -> None:
        expected = hashlib.sha1(f"我的书|{articles[0].url}".encode()).hexdigest()
        assert book_identifier("我的书", articles) == expected
        assert len(expected) == 40 and all(c in "0123456789abcdef" for c in expected)

    def test_empty_articles_does_not_crash(self) -> None:
        assert book_identifier("空书", []) == hashlib.sha1("空书|".encode()).hexdigest()

    def test_different_first_url_changes_id(self, articles: list[Article]) -> None:
        other = make_articles()
        other.reverse()
        assert book_identifier("我的书", articles) != book_identifier("我的书", other)


# ----------------------------------------------------------------------
# txt
# ----------------------------------------------------------------------


class TestTxtExport:
    """txt：plain_text 拍平 + 分章结构。"""

    def test_path_and_name(self, articles: list[Article], tmp_path: Path) -> None:
        path = export_one("我的书", articles, "txt", tmp_path)
        assert path.name == "我的书.txt" and path.exists()

    def test_structure(self, articles: list[Article], tmp_path: Path) -> None:
        text = export_one("我的书", articles, "txt", tmp_path).read_text(encoding="utf-8")
        assert text.startswith("我的书\n")
        assert "第一章 开始" in text and "第二章 继续" in text
        assert "- 清单甲" in text and "- 清单乙" in text      # li 拍平
        assert "> 引用一句话" in text                        # quote 拍平
        assert "小节标题" in text and "三级小标题" in text      # h2/h3 保留文本
        assert "这是第一段。" in text and "这是第二段。" in text  # p 原文
        assert "远程图片" not in text                        # img 块被拍平丢弃
        assert text.count("-" * 40) == len(articles) + 1      # 抬头 1 条 + 每章 1 条

    def test_chapter_type_prefix(self, articles: list[Article], tmp_path: Path) -> None:
        text = export_one("我的书", articles, "txt", tmp_path).read_text(encoding="utf-8")
        assert "【番外】彩蛋篇" in text
        assert "【作者说】创作谈" in text

    def test_empty_article_body_placeholder(self, tmp_path: Path) -> None:
        arts = [Article(title="空章", url="u", blocks=[])]
        text = export_one("t", arts, "txt", tmp_path).read_text(encoding="utf-8")
        assert "（本章无正文）" in text


# ----------------------------------------------------------------------
# md
# ----------------------------------------------------------------------


class TestMdExport:
    """md：保留解析层结构。"""

    def test_path_and_name(self, articles: list[Article], tmp_path: Path) -> None:
        assert export_one("我的书", articles, "md", tmp_path).name == "我的书.md"

    def test_heading_and_source(self, articles: list[Article], tmp_path: Path) -> None:
        text = export_one("我的书", articles, "md", tmp_path).read_text(encoding="utf-8")
        assert "# 第一章 开始" in text
        assert "> 来源：https://www.zhihu.com/market/paid_column/1/section/2" in text

    def test_block_structure(self, articles: list[Article], tmp_path: Path) -> None:
        text = export_one("我的书", articles, "md", tmp_path).read_text(encoding="utf-8")
        assert "## 小节标题" in text                              # h2
        assert "### 三级小标题" in text                            # h3
        assert "- 清单甲\n- 清单乙" in text                         # 连续 li 合并为一个列表
        assert "> 引用一句话" in text                              # quote
        assert "![远程图片](https://picx.zhimg.com/remote.png)" in text  # img
        assert "\n这是第一段。\n" in text                            # p 原文，无 markdown 前缀
        assert "\n这是第二段。\n" in text

    def test_chapter_type_prefix(self, articles: list[Article], tmp_path: Path) -> None:
        text = export_one("我的书", articles, "md", tmp_path).read_text(encoding="utf-8")
        assert "# 【番外】彩蛋篇" in text
        assert "# 【作者说】创作谈" in text

    def test_no_double_marker(self, tmp_path: Path) -> None:
        """标题自带「番外」时不叠加前缀，避免出现「【番外】番外 后记」。"""
        arts = [
            Article(title="番外 后记", url="https://x/1", chapter_type="extra", blocks=[Block("p", text="乙")]),
            Article(title="后记", url="https://x/2", chapter_type="author_note", blocks=[Block("p", text="丙")]),
        ]
        text = export_one("我的书", arts, "md", tmp_path).read_text(encoding="utf-8")
        assert "# 番外 后记" in text and "【番外】番外" not in text
        assert "# 【作者说】后记" in text

    def test_no_source_line_without_url(self, tmp_path: Path) -> None:
        arts = [Article(title="无来源章", url="", blocks=[Block("p", text="正文")])]
        text = export_one("t", arts, "md", tmp_path).read_text(encoding="utf-8")
        assert "> 来源：" not in text and "# 无来源章" in text

    @pytest.mark.parametrize(
        ("block", "expected"),
        [
            (Block("h2", text="甲"), "## 甲"),
            (Block("h3", text="乙"), "### 乙"),
            (Block("li", text="丙"), "- 丙"),
            (Block("quote", text="丁"), "> 丁"),
            (Block("img", src="http://x/y.png", alt="图"), "![图](http://x/y.png)"),
            (Block("p", text="戊"), "戊"),
        ],
    )
    def test_render_block_mapping(self, block: Block, expected: str) -> None:
        assert render_block(block) == expected

    def test_render_block_img_without_src(self) -> None:
        assert render_block(Block("img", src="", alt="缺图")) == "*（图片缺失：缺图）*"


# ----------------------------------------------------------------------
# R2 审计 #4：md 远端正文净化（HTML 注入 / 围栏逃逸 / 注释逃逸）
# ----------------------------------------------------------------------


class TestMdSanitization:
    """远端 block.text 是攻击者可控输入：进 .md 前必须净化。

    测试源码里刻意不写字面反引号（避免与围栏混淆），统一用 chr(96) 构造。
    """

    BT = chr(96)  # 反引号

    def test_script_and_img_payloads_never_bare(self, tmp_path: Path) -> None:
        attack = (
            "<script>alert(1)</script> 与 <img src=x onerror=alert(2)> 还有 "
            + "闭合注释 --> 与围栏 " + self.BT * 3
        )
        arts = [Article(title="章", url="https://x/1", blocks=[Block("p", text=attack)])]
        text = export_one("书", arts, "md", tmp_path).read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in text
        assert "<img src=x" not in text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text  # 实体化后按字面渲染
        assert "&lt;img src=x onerror=alert(2)&gt;" in text
        assert "<" not in text, "整篇不得残留裸 <（payload 全部实体化）"
        assert self.BT * 3 not in text, "不得残留裸三反引号围栏"
        for line in text.splitlines():
            bare = line.replace("&lt;", "").replace("&gt;", "").replace("&amp;", "")
            if ">" in bare:
                assert line.startswith(">"), "裸 > 只允许出现在引用行首"

    def test_code_fence_escape(self, tmp_path: Path) -> None:
        """反引号逐个加反斜杠转义：远端内容拼不出代码围栏/行内码。"""
        fence = self.BT * 3
        arts = [Article(
            title="章", url="https://x/1",
            blocks=[Block("p", text=fence + "py\nprint(1)\n" + fence)],
        )]
        text = export_one("书", arts, "md", tmp_path).read_text(encoding="utf-8")
        assert fence not in text
        assert self.BT not in text.replace(chr(92) + self.BT, ""), "每个反引号前都必须有反斜杠"

    def test_heading_and_source_escaped(self, tmp_path: Path) -> None:
        arts = [Article(
            title="恶<title><script>x</script>",
            url="https://x/?a=1&b=2" + chr(34) + "><svg onload=alert(3)>",
            blocks=[Block("p", text="正文")],
        )]
        text = export_one("书", arts, "md", tmp_path).read_text(encoding="utf-8")
        assert "<script>" not in text and "<svg" not in text
        assert "&lt;script&gt;" in text and "&amp;" in text

    def test_no_html_comment_header(self, tmp_path: Path) -> None:
        """首行注释删除：含 --> 的书名不再可能逃逸成 HTML。"""
        arts = [Article(title="章", url="", blocks=[Block("p", text="正文")])]
        text = export_one("书-->恶意", arts, "md", tmp_path).read_text(encoding="utf-8")
        assert "<!--" not in text and "-->" not in text
        assert text.startswith("# 章")

    def test_img_alt_and_src_escaped(self) -> None:
        q = chr(34)
        got = render_block(Block("img", src="https://x/a.png" + q + " onerror=" + q + "alert(1)",
                                alt="a" + q + "b<c>"))
        assert got == "![a&quot;b&lt;c&gt;](https://x/a.png&quot; onerror=&quot;alert(1))"
        assert "<" not in got and q not in got

    def test_clean_text_unchanged(self) -> None:
        """普通中英文零损耗（转义只针对 HTML/围栏字符）。"""
        assert render_block(Block("p", text="第 1 章：「你好，world」！100% 稳。")) == \
            "第 1 章：「你好，world」！100% 稳。"


# ----------------------------------------------------------------------
# epub
# ----------------------------------------------------------------------


class TestEpubExport:
    """epub：ebooklib 读回验证章节数 / TOC / identifier / 图片 / CSS / 封面。"""

    def test_file_created(self, articles: list[Article], tmp_path: Path) -> None:
        path = export_one("我的书", articles, "epub", tmp_path)
        assert path.suffix == ".epub" and path.exists() and path.stat().st_size > 0

    def test_chapter_count(self, articles: list[Article], tmp_path: Path) -> None:
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        docs = [i.get_name() for i in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)]
        assert sorted(n for n in docs if n.startswith("chapter_")) == [
            "chapter_0.xhtml",
            "chapter_1.xhtml",
            "chapter_2.xhtml",
            "chapter_3.xhtml",
        ]
        assert len(articles) == 4

    def test_identifier_is_stable_sha1(self, articles: list[Article], tmp_path: Path) -> None:
        """两次导出（不同目录）identifier 必须一致，且等于 sha1 十六进制。"""
        first = export_one("我的书", articles, "epub", tmp_path / "a")
        second = export_one("我的书", articles, "epub", tmp_path / "b")
        expected = hashlib.sha1(f"我的书|{articles[0].url}".encode()).hexdigest()
        assert read_epub(first).get_metadata("DC", "identifier")[0][0] == expected
        assert read_epub(second).get_metadata("DC", "identifier")[0][0] == expected

    def test_toc_two_levels(self, articles: list[Article], tmp_path: Path) -> None:
        """TOC 两级：正文章归「正文」，番外/作者说归「附录」。"""
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        sections = {entry[0].title: [link.title for link in entry[1]] for entry in book.toc}
        assert list(sections) == ["正文", "附录"]
        assert sections["正文"] == ["第一章 开始", "第二章 继续"]
        assert sections["附录"] == ["【番外】彩蛋篇", "【作者说】创作谈"]

    def test_toc_normal_only_book_has_no_appendix(self, tmp_path: Path) -> None:
        arts = [Article(title="唯一章", url="https://x/1", blocks=[Block("p", text="正文")])]
        book = read_epub(export_one("单章书", arts, "epub", tmp_path))
        assert [entry[0].title for entry in book.toc] == ["正文"]

    def test_cover_page_and_image_item(self, articles: list[Article], tmp_path: Path) -> None:
        path = export_one("我的书", articles, "epub", tmp_path)
        book = read_epub(path)
        cover_image = book.get_item_with_id("cover-img")
        assert cover_image is not None
        assert cover_image.media_type == "image/svg+xml"
        assert b"<svg" in cover_image.get_content()
        assert any(n.endswith("cover.xhtml") for n in zip_names(path))
        assert any(n.endswith("cover_image.svg") for n in zip_names(path))
        cover_html = chapter_body(book, "cover")
        assert "我的书" in cover_html and "佚名" in cover_html

    def test_local_image_embedded(self, articles: list[Article], local_png: Path, tmp_path: Path) -> None:
        """output_dir 内的绝对路径 src 是合法用例 → 内嵌为图片项并在正文引用。

        终局定稿 containment（R2 #5，A10 门禁冻结）：唯一判据是 resolve 后
        containment；v5.1 图片下载回填就长这样。
        """
        assert local_png.parent.parent == tmp_path  # tmp_path/assets/pic.png 在输出目录内
        articles[1].blocks.append(Block("img", src=str(local_png), alt="本地图"))
        path = export_one("我的书", articles, "epub", tmp_path)
        book = read_epub(path)
        images = [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if i.get_name().startswith("images/")]
        assert len(images) == 1
        assert images[0].media_type == "image/png"
        assert images[0].get_content() == png_bytes()
        assert any(n.endswith("images/image_0.png") for n in zip_names(path))
        body = chapter_body(book, "chapter_1")
        assert 'src="images/image_0.png"' in body and "本地图" in body

    def test_same_local_image_embedded_once(self, articles: list[Article], local_png: Path, tmp_path: Path) -> None:
        """同一张本地图被两章引用 → 只内嵌一份。"""
        articles[0].blocks.append(Block("img", src=str(local_png), alt="复用图"))
        articles[1].blocks.append(Block("img", src=str(local_png.resolve()), alt="复用图"))
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        images = [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if i.get_name().startswith("images/")]
        assert len(images) == 1

    def test_remote_image_degrades_to_alt(self, articles: list[Article], tmp_path: Path) -> None:
        """src 是远端 URL（离线不可得）→ 渲染 alt 文本，不产生坏图。"""
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        body = chapter_body(book, "chapter_0")
        assert "[图片：远程图片]" in body
        assert "<img" not in body.split('class="source"')[1]

    def test_missing_local_file_degrades_to_alt(self, articles: list[Article], tmp_path: Path) -> None:
        articles[0].blocks.append(Block("img", src=str(tmp_path / "nope.png"), alt="丢失的图"))
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        assert "[图片：丢失的图]" in chapter_body(book, "chapter_0")

    def test_css_embedded_with_indent_and_line_height(self, articles: list[Article], tmp_path: Path) -> None:
        path = export_one("我的书", articles, "epub", tmp_path)
        book = read_epub(path)
        css_items = [i for i in book.get_items() if i.media_type == "text/css"]
        assert len(css_items) == 1
        css = css_items[0].get_content().decode("utf-8")
        assert "text-indent: 2em" in css        # 段首缩进
        assert "line-height: 1.6" in css        # 行距
        assert "h1.chapter-title" in css        # 标题样式
        assert css == BASE_CSS
        # 章节确实引用了样式表（读回后需看压缩包原文，get_content 会重建 head）
        with zipfile.ZipFile(path) as zf:
            assert 'href="style/default.css"' in zf.read("EPUB/chapter_0.xhtml").decode("utf-8")

    def test_html_escaping(self, tmp_path: Path) -> None:
        arts = [Article(title='危<险>&"章"', url="https://x/?a=1&b=2", blocks=[Block("p", text="A & B <b>粗</b>")])]
        book = read_epub(export_one("危<险>&书", arts, "epub", tmp_path))
        body = chapter_body(book, "chapter_0")
        assert "A &amp; B" in body
        assert "<b>" not in body  # 正文里的标签被转义，不会被当作 HTML

    def test_spine_order_follows_articles(self, articles: list[Article], tmp_path: Path) -> None:
        """阅读顺序保持原始章节顺序（附录只在 TOC 里分组）。"""
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        ids = [item_id for item_id, _ in book.spine]
        assert ids[:2] == ["cover", "nav"]
        assert ids[2:] == ["chapter_0", "chapter_1", "chapter_2", "chapter_3"]

    def test_metadata_title_and_language(self, articles: list[Article], tmp_path: Path) -> None:
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        assert book.get_metadata("DC", "title")[0][0] == "我的书"
        assert book.get_metadata("DC", "language")[0][0] == "zh-CN"

    def test_empty_articles_still_valid(self, tmp_path: Path) -> None:
        path = export_one("空书", [], "epub", tmp_path)
        book = read_epub(path)
        assert "暂无内容" in chapter_body(book, "chapter_0")
        assert any(n.endswith("content.opf") for n in zip_names(path))

    def test_cover_svg_contains_title_and_author(self) -> None:
        svg = build_cover_svg("很长很长很长很长很长很长的书名", "佚名", 3).decode("utf-8")
        assert svg.startswith("<svg")
        assert "佚名" in svg and "共 3 章" in svg
        assert svg.count("<text") >= 3  # 书名折成多行

    def test_cover_svg_escapes_title(self) -> None:
        svg = build_cover_svg('a<b>&"c"', "佚名", 1).decode("utf-8")
        assert "<b>" not in svg and "&amp;" in svg


# ----------------------------------------------------------------------
# R2 审计 #5（终局定稿 containment，冻结于 A10 门禁；§2.12/§6 表同步）：
# 唯一判据 = resolve 后 realpath 落在 output_dir 之内；框外必拒 + 框内必嵌
# 双钉；SVG 永不内嵌。翻转任何一侧 → 本矩阵与 scripts/acceptance.py A10
# 同时 FAIL——这就是"勿再翻"的可执行形态。
# ----------------------------------------------------------------------


class TestEpubImageEmbeddingSecurity:
    """containment 矩阵：框内绝对/相对 → 内嵌；框外绝对/../软链逃逸/SVG → alt。"""

    @staticmethod
    def _embedded_images(path: Path) -> list:
        book = read_epub(path)
        return [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if i.get_name().startswith("images/")]

    def test_absolute_path_outside_output_dir_not_embedded(
        self, articles: list[Article], tmp_path: Path
    ) -> None:
        """真攻击面：绝对路径指向 output_dir 外（兄弟目录）→ 降级 alt，字节不进包。"""
        outside = tmp_path / "secrets"
        outside.mkdir()
        secret = outside / "private.png"
        secret.write_bytes(png_bytes())
        out_dir = tmp_path / "books"
        articles[0].blocks.append(Block("img", src=str(secret), alt="磁盘他处图"))
        path = export_one("我的书", articles, "epub", out_dir)
        assert self._embedded_images(path) == []
        assert "[图片：磁盘他处图]" in chapter_body(read_epub(path), "chapter_0")
        assert png_bytes() not in path.read_bytes()

    def test_absolute_path_inside_output_dir_embedded(
        self, articles: list[Article], local_png: Path, tmp_path: Path
    ) -> None:
        """定稿钉（A10 inside_lock 的镜像）：框内绝对路径（v5.1 回填形态）
        是合法用例 → 必须内嵌成功；判据是 containment 而非路径形态。"""
        articles[0].blocks.append(Block("img", src=str(local_png), alt="框内绝对图"))
        path = export_one("我的书", articles, "epub", tmp_path)
        images = self._embedded_images(path)
        assert len(images) == 1 and images[0].media_type == "image/png"
        assert images[0].get_content() == png_bytes()
        assert 'src="images/image_0.png"' in chapter_body(read_epub(path), "chapter_0")

    def test_relative_path_inside_output_dir_embedded(
        self, articles: list[Article], local_png: Path, tmp_path: Path
    ) -> None:
        """合法正例：相对 src 以 output_dir 为根解析 → 正常内嵌。"""
        articles[0].blocks.append(Block("img", src="assets/pic.png", alt="框内相对图"))
        path = export_one("我的书", articles, "epub", tmp_path)
        images = self._embedded_images(path)
        assert len(images) == 1 and images[0].media_type == "image/png"
        assert images[0].get_content() == png_bytes()
        assert 'src="images/image_0.png"' in chapter_body(read_epub(path), "chapter_0")

    def test_relative_escape_outside_output_dir_not_embedded(
        self, articles: list[Article], tmp_path: Path
    ) -> None:
        """../ 逃逸到 output_dir 之外的相对路径 → 拒绝内嵌。"""
        secret = tmp_path / "secret.png"
        secret.write_bytes(png_bytes())
        out_dir = tmp_path / "books"
        articles[0].blocks.append(Block("img", src="../secret.png", alt="越界图"))
        path = export_one("我的书", articles, "epub", out_dir)
        book = read_epub(path)
        images = [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if i.get_name().startswith("images/")]
        assert images == []
        assert "[图片：越界图]" in chapter_body(book, "chapter_0")

    def test_symlink_escape_not_embedded(self, articles: list[Article], tmp_path: Path) -> None:
        """output_dir 内的符号链接指向外部文件 → resolve 后越界，拒绝。"""
        if os.name == "nt":  # pragma: no cover - Windows 需要开发者权限建软链
            pytest.skip("POSIX symlink")
        secret = tmp_path / "secret.png"
        secret.write_bytes(png_bytes())
        out_dir = tmp_path / "books"
        out_dir.mkdir()
        (out_dir / "link.png").symlink_to(secret)
        articles[0].blocks.append(Block("img", src="link.png", alt="软链图"))
        path = export_one("我的书", articles, "epub", out_dir)
        book = read_epub(path)
        images = [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if i.get_name().startswith("images/")]
        assert images == []
        assert "[图片：软链图]" in chapter_body(book, "chapter_0")

    def test_svg_inside_output_dir_not_embedded(self, articles: list[Article], tmp_path: Path) -> None:
        """SVG 可携带脚本：即使在 output_dir 内也一律降级 alt。"""
        svg = tmp_path / "evil.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', encoding="utf-8")
        articles[0].blocks.append(Block("img", src="evil.svg", alt="SVG图"))
        path = export_one("我的书", articles, "epub", tmp_path)
        book = read_epub(path)
        images = [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if i.get_name().startswith("images/")]
        assert images == []
        assert "[图片：SVG图]" in chapter_body(book, "chapter_0")
        assert b"<script>alert(1)</script>" not in path.read_bytes()

    def test_remote_url_still_degrades(self, articles: list[Article], tmp_path: Path) -> None:
        """远端 URL（含 scheme，非本机路径）维持降级 alt。"""
        articles[0].blocks.append(Block("img", src="https://picx.zhimg.com/a.png", alt="远端"))
        book = read_epub(export_one("我的书", articles, "epub", tmp_path))
        assert "[图片：远端]" in chapter_body(book, "chapter_0")


# ----------------------------------------------------------------------
# 统一入口 export_book
# ----------------------------------------------------------------------


class TestExportBook:
    """export_book 分发与错误。"""

    def test_formats_constant(self) -> None:
        assert FORMATS == ("txt", "md", "epub")

    @pytest.mark.parametrize(("fmt", "suffix"), [("txt", ".txt"), ("md", ".md"), ("epub", ".epub")])
    def test_returns_single_path(self, articles: list[Article], tmp_path: Path, fmt: str, suffix: str) -> None:
        files = export_book("我的书", articles, fmt, tmp_path)
        assert isinstance(files, list) and len(files) == 1
        assert files[0].endswith(suffix) and Path(files[0]).exists()
        assert isinstance(files[0], str)

    def test_format_is_case_insensitive(self, articles: list[Article], tmp_path: Path) -> None:
        assert export_book("我的书", articles, "MD", tmp_path)[0].endswith(".md")
        assert export_book("我的书", articles, " epub ", tmp_path)[0].endswith(".epub")

    def test_unknown_format_raises_export_error(self, articles: list[Article], tmp_path: Path) -> None:
        with pytest.raises(ExportError) as exc:
            export_book("我的书", articles, "docx", tmp_path)
        message = str(exc.value)
        assert "docx" in message                      # 指出坏输入
        assert all(f in message for f in FORMATS)      # 给出可操作的替代方案

    def test_empty_format_raises(self, articles: list[Article], tmp_path: Path) -> None:
        with pytest.raises(ExportError):
            export_book("我的书", articles, "", tmp_path)

    def test_creates_missing_output_dir(self, articles: list[Article], tmp_path: Path) -> None:
        target = tmp_path / "deep" / "nested"
        assert export_one("我的书", articles, "txt", target).parent == target
        assert target.is_dir()

    def test_unsafe_title_sanitised(self, articles: list[Article], tmp_path: Path) -> None:
        """坏标题进、安全文件名出：非法字符全部下划线化，扩展名由格式决定。"""
        path = export_one('a/b:c*d?', articles, "txt", tmp_path)
        assert path.name == "a_b_c_d_.txt"
        assert path.exists()
        assert export_one("///", articles, "md", tmp_path).name == "zhihu.md"


# ----------------------------------------------------------------------
# R1 审查 M5：export_book 契约——写盘失败必须 ExportError，不得裸 OSError
# ----------------------------------------------------------------------


class TestExportFailureContract:
    """output_dir 撞普通文件 / 目标撞目录：中文 ExportError + 下一步，零 traceback。"""

    def test_resolve_output_dir_over_existing_file(self, tmp_path: Path) -> None:
        blocker = tmp_path / "books"
        blocker.write_text("我是文件不是目录", encoding="utf-8")
        with pytest.raises(ExportError) as exc:
            resolve_output_dir(blocker)
        message = str(exc.value)
        assert "输出目录" in message and "--output" in message

    def test_export_book_output_dir_over_file_all_formats(
        self, articles: list[Article], tmp_path: Path
    ) -> None:
        blocker = tmp_path / "books"
        blocker.write_text("x", encoding="utf-8")
        for fmt in FORMATS:
            with pytest.raises(ExportError):
                export_book("我的书", articles, fmt, blocker / "sub")

    @pytest.mark.filterwarnings("ignore::UserWarning")  # ebooklib 撞目录时只发弃用式警告，正靠事后校验兜底
    @pytest.mark.parametrize(("fmt", "suffix"), [("txt", ".txt"), ("md", ".md"), ("epub", ".epub")])
    def test_target_path_is_directory_raises_export_error(
        self, articles: list[Article], tmp_path: Path, fmt: str, suffix: str
    ) -> None:
        """同名目录占位：write/write_epub 抛 OSError → 必须包装成 ExportError。"""
        (tmp_path / f"我的书{suffix}").mkdir()
        with pytest.raises(ExportError) as exc:
            export_book("我的书", articles, fmt, tmp_path)
        message = str(exc.value)
        assert "我的书" in message  # 指出坏路径
        assert any(k in message for k in ("目录", "权限", "空间"))  # 给出下一步
