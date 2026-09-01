"""cleaner 测试：广告/水印/垃圾文本块整块过滤、img 保留、extra_patterns、幂等。全部离线。"""

from __future__ import annotations

import re

import pytest

from zhihu_downloader.parse.cleaner import clean
from zhihu_downloader.types import Article, Block


def _make_article() -> Article:
    """构造包含正常块与各类应被清洗块的样例文章。"""
    return Article(
        title="测试章节",
        url="https://www.zhihu.com/market/paid_column/1/section/2",
        blocks=[
            Block(kind="h2", text="第二章"),
            Block(kind="p", text="夜色如墨，他推门而入。"),
            Block(kind="p", text="关注公众号「盐言故事」，回复关键词领全文。"),
            Block(kind="p", text="点击下载 APP 解锁全文。"),
            Block(kind="p", text="本文来源：知乎盐选专栏"),
            Block(kind="p", text="相关阅读"),
            Block(kind="p", text="   "),
            Block(kind="img", src="https://pic1.zhihu.com/a.png", alt="插图"),
            Block(kind="li", text="他低声说：走！"),
            Block(kind="quote", text="「小心有诈。」"),
        ],
    )


class TestClean:
    def test_returns_same_article(self) -> None:
        article = _make_article()
        assert clean(article) is article

    def test_ad_and_watermark_blocks_removed(self) -> None:
        kept_texts = [b.text for b in clean(_make_article()).blocks if b.kind != "img"]
        assert "关注公众号「盐言故事」，回复关键词领全文。" not in kept_texts
        assert "点击下载 APP 解锁全文。" not in kept_texts
        # round49 改判：「本文来源：」非块首脚标，按新语义保留（漏删优于误杀）。
        assert "本文来源：知乎盐选专栏" in kept_texts
        assert "相关阅读" not in kept_texts

    def test_empty_text_block_removed(self) -> None:
        assert all(b.text.strip() for b in clean(_make_article()).blocks if b.kind != "img")

    def test_normal_blocks_kept(self) -> None:
        kept = clean(_make_article()).blocks
        # round49 改判新增保留项：「本文来源：…」非块首，按设计漏删（见 e1 注释）。
        assert [b.kind for b in kept] == ["h2", "p", "p", "img", "li", "quote"]
        assert kept[1].text == "夜色如墨，他推门而入。"
        assert kept[2].text == "本文来源：知乎盐选专栏"
        assert kept[4].text == "他低声说：走！"

    def test_img_blocks_never_filtered(self) -> None:
        article = _make_article()
        article.blocks.append(Block(kind="img", src="https://www.zhihu.com/x.png", alt=""))
        imgs = [b for b in clean(article).blocks if b.kind == "img"]
        assert len(imgs) == 2

    def test_extra_patterns(self) -> None:
        cleaned = clean(_make_article(), extra_patterns=["夜色"])
        texts = [b.text for b in cleaned.blocks if b.kind == "p"]
        assert "夜色如墨，他推门而入。" not in texts
        # 不加 extra_patterns 时该块应保留（对照组）
        assert "夜色如墨，他推门而入。" in [b.text for b in clean(_make_article()).blocks]

    def test_invalid_extra_pattern_raises(self) -> None:
        with pytest.raises(re.error):
            clean(_make_article(), extra_patterns=["(未闭合"])

    def test_idempotent(self) -> None:
        once = clean(_make_article())
        count = len(once.blocks)
        assert len(clean(once).blocks) == count

    def test_watermark_bracket_pattern(self) -> None:
        article = Article(title="t", url="u", blocks=[Block(kind="p", text="[转载@某某]"), Block(kind="p", text="正常段落内容")])
        kept = [b.text for b in clean(article).blocks]
        assert kept == ["正常段落内容"]

    def test_trash_pure_marker(self) -> None:
        article = Article(
            title="t",
            url="u",
            blocks=[
                Block(kind="p", text="相关推荐"),
                Block(kind="p", text="<!--注释残留-->"),
                Block(kind="p", text="{模板变量}"),
            ],
        )
        assert clean(article).blocks == []


class TestEnglishWordBoundaries:
    """R1 审查 m4：英文词形不得作为裸子串误杀正常文本。

    边界用 (?<![A-Za-z])X(?![A-Za-z]) 而非 \\bX\\b：Python re 中 CJK 也是
    \\w，\\b 会漏掉「下载知乎APP」这类中英夹杂真广告；排除式环视只挡
    ASCII 字母拼接。中文来源/出处词表 round49 起改为块首锚定（见改判用例）。
    """

    @staticmethod
    def _kept(texts: list[str]) -> list[str]:
        article = Article(title="t", url="u", blocks=[Block(kind="p", text=x) for x in texts])
        return [b.text for b in clean(article).blocks]

    def test_read_shadow_header_apple_not_removed(self) -> None:
        texts = [
            "Please READ this before dawn.",
            "The SHADOW fell on the HEADER.",
            "an APPLE pie and a BAD idea",
        ]
        assert self._kept(texts) == texts

    def test_cjk_adjacent_ads_still_removed(self) -> None:
        """真广告不因边界而漏：中文紧邻 APP / 括号包裹 AD 仍整块删除。"""
        kept = self._kept(["下载知乎APP解锁全文", "打开APP看更多", "【AD】本页推广位"])
        assert kept == []

    def test_ad_with_ascii_punctuation_still_removed(self) -> None:
        kept = self._kept(["AD: sponsored", "(AD) 广告位"])
        assert kept == []

    def test_zhihu_domain_boundary(self) -> None:
        """myzhihu.com 不再被裸子串误杀；www.zhihu.com 水印照常删。"""
        kept = self._kept(["详见 myzhihu.com 站", "见 www.zhihu.com 首页"])
        assert kept == ["详见 myzhihu.com 站"]

    def test_chinese_vocabulary_unchanged(self) -> None:
        """round49 改判：块首短脚标照删，句中「出处/来源」必须保留（D1 证据）。"""
        assert self._kept(["来源：知乎盐选专栏", "出处：《清史稿》"]) == []
        keep = [
            "这段引文的出处：《清史稿》里另有记载。",
            "本文来源：知乎盐选专栏",  # 「本文」前缀使锚点不中——设计内漏删
            "他缓缓开口：\"故事的来源，往往比结局更动人。\"",
        ]
        assert self._kept(keep) == keep
