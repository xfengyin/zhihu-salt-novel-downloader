"""签名固定向量回归测试。

signature.py 的常量全部硬编码（知乎轮换即失效）。本测试钉死：
1. 随机前缀置固定后的完整签名值（向量）；
2. 结构不变量（前缀/长度/字符集）；
3. x-zst-81 常量与缺 d_c0 行为。
知乎轮换签名算法时，本测试会第一时间红——提醒维护者更新常量而非静默失效。
"""

from __future__ import annotations

import pytest

from zhihu_downloader import signature
from zhihu_downloader.signature import XZSE_93_VERSION, generate_zhihu_sign


@pytest.fixture(autouse=True)
def _fixed_random(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 random.randint 钉死为 66，消除 x-zse-96 的随机前缀。"""
    monkeypatch.setattr(signature.random, "randint", lambda a, b: 66)


def test_vector_section_url() -> None:
    sign = generate_zhihu_sign(
        "https://www.zhihu.com/market/paid_column/123/section/456",
        {"d_c0": "abc"},
    )
    assert sign["x-zse-96"] == "2.0_5f1QplgX29OtRWmqMcfQwzjU9/pqfWdNyWQ2P77zRVXIDnYhBjqtWxjwDcH/gh/C"
    assert sign["x-zst-81"] == signature._TC


def test_vector_column_url() -> None:
    sign = generate_zhihu_sign(
        "https://www.zhihu.com/market/paid_column/999",
        {"d_c0": "xyz789"},
    )
    assert sign["x-zse-96"].startswith("2.0_")
    assert len(sign["x-zse-96"]) == len("2.0_") + 64


def test_structure_invariants() -> None:
    for url, dc0 in [
        ("https://www.zhihu.com/market/paid_column/1", "d1"),
        ("https://www.zhihu.com/api/v4/me", "d2"),
        ("", "d3"),
    ]:
        sign = generate_zhihu_sign(url, {"d_c0": dc0})
        zse = sign["x-zse-96"]
        assert zse.startswith("2.0_")
        body = zse[4:]
        assert len(body) == 64
        assert all(c in signature._INIT_STR for c in body)


def test_zst_81_constant() -> None:
    a = generate_zhihu_sign("https://www.zhihu.com/a", {"d_c0": "x"})
    b = generate_zhihu_sign("https://www.zhihu.com/b", {"d_c0": "y"})
    assert a["x-zst-81"] == b["x-zst-81"]


def test_missing_d_c0_returns_empty() -> None:
    assert generate_zhihu_sign("https://www.zhihu.com/x", {}) == {}
    assert generate_zhihu_sign("https://www.zhihu.com/x", {"z_c0": "v"}) == {}


def test_different_inputs_different_signs() -> None:
    s1 = generate_zhihu_sign("https://www.zhihu.com/a", {"d_c0": "x"})
    s2 = generate_zhihu_sign("https://www.zhihu.com/b", {"d_c0": "x"})
    s3 = generate_zhihu_sign("https://www.zhihu.com/a", {"d_c0": "y"})
    assert s1["x-zse-96"] != s2["x-zse-96"]
    assert s1["x-zse-96"] != s3["x-zse-96"]


def test_version_constant() -> None:
    assert XZSE_93_VERSION == "101_3_3.0"
