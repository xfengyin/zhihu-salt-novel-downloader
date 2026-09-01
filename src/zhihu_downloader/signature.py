"""知乎 x-zse-96 / x-zst-81 签名模块。

纯 Python 移植自 MediaCrawler 的 zhihu.js（SM4 风格分组密码），
参考实现来自公开仓库 Smart75850/smart-agent 的 zhihu_sign.py。

许可说明：
- MediaCrawler (NanmiCoder/MediaCrawler) 采用 Apache License 2.0；
- 本移植仅使用 Python 标准库（hashlib/random/re），不引入任何第三方加密依赖。

算法要点：
    x-zst-81 为固定常量；x-zse-96 = "2.0_" + base64-ish(
        SM4 风格的 48 字节初始化数组变换，
        输入为 md5(f"{version}+{url}+{d_c0}+{x_zst_81}") 的 hex
    )，其中每个签名的随机前缀来自 random.randint(0, 127)。
"""

from __future__ import annotations

import hashlib
import random

__all__ = ["XZSE_93_VERSION", "generate_zhihu_sign"]

#: 请求头 x-zse-93 的版本号（与签名 md5 的 version 保持一致）
XZSE_93_VERSION = "101_3_3.0"

#: x-zse-96 最终编码表（64 字符）
_INIT_STR = "6fpLRqJO8M/c3jnYxFkUVC4ZIG12SiH=5v0mXDazWBTsuw7QetbKdoPyAl+hN9rgE"

#: SM4 风格密钥扩展常量（32 个 32 位有符号整数）
_ZK = [
    1170614578,
    1024848638,
    1413669199,
    -343334464,
    -766094290,
    -1373058082,
    -143119608,
    -297228157,
    1933479194,
    -971186181,
    -406453910,
    460404854,
    -547427574,
    -1891326262,
    -1679095901,
    2119585428,
    -2029270069,
    2035090028,
    -1521520070,
    -5587175,
    -77751101,
    -2094365853,
    -1243052806,
    1579901135,
    1321810770,
    456816404,
    -1391643889,
    -229302305,
    330002838,
    -788960546,
    363569021,
    -1947871109,
]

#: SM4 风格 S 盒（256 字节）
_ZB = [
    20, 223, 245, 7, 248, 2, 194, 209, 87, 6, 227, 253, 240, 128, 222, 91,
    237, 9, 125, 157, 230, 93, 252, 205, 90, 79, 144, 199, 159, 197, 186, 167,
    39, 37, 156, 198, 38, 42, 43, 168, 217, 153, 15, 103, 80, 189, 71, 191,
    97, 84, 247, 95, 36, 69, 14, 35, 12, 171, 28, 114, 178, 148, 86, 182,
    32, 83, 158, 109, 22, 255, 94, 238, 151, 85, 77, 124, 254, 18, 4, 26,
    123, 176, 232, 193, 131, 172, 143, 142, 150, 30, 10, 146, 162, 62, 224, 218,
    196, 229, 1, 192, 213, 27, 110, 56, 231, 180, 138, 107, 242, 187, 54, 120,
    19, 44, 117, 228, 215, 203, 53, 239, 251, 127, 81, 11, 133, 96, 204, 132,
    41, 115, 73, 55, 249, 147, 102, 48, 122, 145, 106, 118, 74, 190, 29, 16,
    174, 5, 177, 129, 63, 113, 99, 31, 161, 76, 246, 34, 211, 13, 60, 68,
    207, 160, 65, 111, 82, 165, 67, 169, 225, 57, 112, 244, 155, 51, 236, 200,
    233, 58, 61, 47, 100, 137, 185, 64, 17, 70, 234, 163, 219, 108, 170, 166,
    59, 149, 52, 105, 24, 212, 78, 173, 45, 0, 116, 226, 119, 136, 206, 135,
    175, 195, 25, 92, 121, 208, 126, 139, 3, 75, 141, 21, 130, 98, 241, 40,
    154, 66, 184, 49, 181, 46, 243, 88, 101, 183, 8, 23, 72, 188, 104, 179,
    210, 134, 250, 201, 164, 89, 216, 202, 220, 50, 221, 152, 140, 33, 235, 214,
]

#: x-zst-81 固定常量
_TC = (
    "3_2.0aR_sn77yn6O92wOB8hPZnQr0EMYxc4f18wNBUgpTQ6nxERFZfTY0-4Lm-h3_tufIwJS8gcxTgJS_AuPZNcXCTwxI78YxEM20s4PGDwN8gGcYAupMWufIoLVqr4gxrRPOI0cY7HL8qun9g93mFukyigcmebS_FwOYPRP0E4rZUrN9DDom3hnynAUMnAVPF_PhaueTFH9fQL39OCCqYTxfb0rfi9wfPhSM6vxGDJo_rBHpQGNmBBLqPJHK2_w8C9eTVMO9Z9NOrMtfhGH_DgpM-BNM1DOxScLG3gg1Hre1FCXKQcXKkrSL1r9GWDXMk8wqBLNmbRH96BtOFqVZ7UYG3gC8D9cMS7Y9UrHLVCLZPJO8_CL_6GNCOg_zhJS8PbXmGTcBpgxfkieOPhNfthtf2gC_qD3YOce8nCwG2uwBOqeMoML9NBC1xb9yk6SuJhHLK7SM6LVfCve_3vLKlqcL6TxL_UosDvHLxrHmWgxBQ8Xs"
)


def _to_unsigned(n: int) -> int:
    """转为无符号 32 位整数。"""
    return n & 0xFFFFFFFF


def _i(val: int, arr: list, offset: int) -> None:
    """将 32 位整数按大端序写入 arr[offset:offset+4]。"""
    arr[offset] = 255 & (val >> 24)
    arr[offset + 1] = 255 & (val >> 16)
    arr[offset + 2] = 255 & (val >> 8)
    arr[offset + 3] = 255 & val


def _Q(val: int, shift: int) -> int:
    """32 位循环左移。"""
    return _to_unsigned((_to_unsigned(val) << shift) | (_to_unsigned(val) >> (32 - shift)))


def _B(arr: list, offset: int) -> int:
    """按大端序读取 4 字节为有符号 32 位整数。"""
    v = (
        (255 & arr[offset]) << 24
        | (255 & arr[offset + 1]) << 16
        | (255 & arr[offset + 2]) << 8
        | 255 & arr[offset + 3]
    )
    return v if v < 0x80000000 else v - 0x100000000


def _G(val: int) -> int:
    """S 盒替换 + 线性变换（SM4 的 T 变换）。"""
    t = [0] * 4
    n = [0] * 4
    _i(val, t, 0)
    n[0] = _ZB[255 & t[0]]
    n[1] = _ZB[255 & t[1]]
    n[2] = _ZB[255 & t[2]]
    n[3] = _ZB[255 & t[3]]
    r = _B(n, 0)
    return _to_unsigned(r ^ _Q(r, 2) ^ _Q(r, 10) ^ _Q(r, 18) ^ _Q(r, 24))


def _array_0_16_offset(arr: list) -> list:
    """SM4 32 轮密钥扩展，返回 16 字节。"""
    t = [0] * 16
    n = [0] * 36
    n[0] = _B(arr, 0)
    n[1] = _B(arr, 4)
    n[2] = _B(arr, 8)
    n[3] = _B(arr, 12)
    for r in range(32):
        o = _G(_to_unsigned(n[r + 1] ^ n[r + 2] ^ n[r + 3] ^ _ZK[r]))
        n[r + 4] = _to_unsigned(n[r] ^ o)
    _i(n[35], t, 0)
    _i(n[34], t, 4)
    _i(n[33], t, 8)
    _i(n[32], t, 12)
    return t


def _array_16_48_offset(arr: list, prev: list) -> list:
    """处理剩余数据块。"""
    result = []
    t = prev[:]
    for i in range(0, len(arr), 16):
        block = arr[i : i + 16]
        a = [0] * 16
        for c in range(16):
            a[c] = block[c] ^ t[c]
        t = _array_0_16_offset(a)
        result.extend(t)
    return result


def _encode_0_16(arr: list) -> list:
    """对前 16 字节做固定偏移异或与 42 异或后做密钥扩展。"""
    array_offset = [48, 53, 57, 48, 53, 51, 102, 55, 100, 49, 53, 101, 48, 49, 100, 55]
    result = []
    for i in range(len(arr)):
        a = arr[i] ^ array_offset[i]
        b = a ^ 42
        result.append(b)
    return _array_0_16_offset(result)


def _encode_3bytes(ar: list) -> list:
    """将 3 字节编码为 4 个 6bit 索引（base64 风格）。"""
    b_val = ar[1] << 8
    c_val = ar[0] | b_val
    d_val = ar[2] << 16
    e_val = c_val | d_val
    result = [e_val & 63]
    x = 6
    while len(result) < 4:
        result.append((e_val >> x) & 63)
        x += 6
    return result


def _get_init_array(md5_hex: str) -> list:
    """由 md5 hex 构造 48 字节初始化数组。"""
    init = [ord(c) for c in md5_hex]
    init.insert(0, 0)
    init.insert(0, random.randint(0, 127))
    while len(init) < 48:
        init.append(14)
    a0 = _encode_0_16(init[:16])
    a48 = _array_16_48_offset(init[16:48], a0)
    return a0 + a48


def _get_zse_96(md5_hex: str) -> str:
    """由 md5 hex 计算 x-zse-96 签名。"""
    init_arr = _get_init_array(md5_hex)
    for i in range(47, -1, -4):
        init_arr[i] ^= 58
    init_arr.reverse()

    result_chars = []
    for j in range(3, len(init_arr) + 1, 3):
        ar = init_arr[j - 3 : j]
        result_chars.extend(_encode_3bytes(ar))

    result = "".join(_INIT_STR[idx] for idx in result_chars)
    return "2.0_" + result


def generate_zhihu_sign(url: str, cookies: dict[str, str]) -> dict[str, str]:
    """生成知乎 x-zst-81 与 x-zse-96 签名请求头。

    Args:
        url: 请求的完整 URL（含 query string）。
        cookies: Cookie 字典，需包含 ``d_c0``。

    Returns:
        包含 ``x-zst-81`` 与 ``x-zse-96`` 的字典；当 cookies 缺少 ``d_c0``
        时返回空字典。
    """
    dc0 = cookies.get("d_c0")
    if not dc0:
        return {}
    join_str = "+".join([XZSE_93_VERSION, url or "", dc0, _TC])
    md5_hex = hashlib.md5(join_str.encode("utf-8")).hexdigest()
    return {
        "x-zst-81": _TC,
        "x-zse-96": _get_zse_96(md5_hex),
    }
