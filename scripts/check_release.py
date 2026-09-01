#!/usr/bin/env python3
"""发布前校验脚本（P1 拥有；release.yml 的 preflight job 与本地自查共用）。

用法：
    python scripts/check_release.py --tag v5.0.0

校验项（全部通过 exit 0；任一失败中文报错 exit 1）：
    1. tag 形如 vX.Y.Z（可带预发布后缀），去 v 后必须等于
       src/zhihu_downloader/__init__.py 的 __version__（架构规格书铁律 4：版本号唯一来源）；
    2. pyproject.toml 的 [project].version 必须与 __version__ 一致
       （v4 教训：6 处版本号漂移，发布物与代码对不上号）；
    3. CHANGELOG.md 必须存在且含该版本段落
       （v4 教训：Release 页面没有变更说明，用户不知道升级了什么）。

仅用标准库：tomllib（3.11+）缺失时退回手写 [project] 段解析，
保证在 Python 3.10 裸环境也能跑。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_FILE = REPO_ROOT / "src" / "zhihu_downloader" / "__init__.py"
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"

_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.MULTILINE)
_TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?)$")


def check_tag_format(tag: str) -> tuple[str | None, str | None]:
    """返回 (version, error)。tag 必须形如 v5.0.0 / v5.1.0-rc1。"""
    m = _TAG_RE.match(tag.strip())
    if not m:
        return None, (
            f"tag 格式非法：{tag!r}。要求形如 vX.Y.Z（如 v5.0.0），"
            "v5 只认这一种发布 tag——v3*/v4* 前缀路由已随旧仓库一起废弃。"
        )
    return m.group(1), None


def read_init_version() -> tuple[str | None, str | None]:
    """返回 (version, error)。"""
    if not INIT_FILE.is_file():
        return None, f"找不到版本唯一来源文件：{INIT_FILE}"
    text = INIT_FILE.read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if not m:
        return None, f"{INIT_FILE} 中找不到 __version__ = \"x.y.z\" 赋值行"
    return m.group(1), None


def read_pyproject_version() -> tuple[str | None, str | None]:
    """返回 (version, error)。优先 tomllib（3.11+），否则手写 [project] 段解析。"""
    if not PYPROJECT_FILE.is_file():
        return None, f"找不到 {PYPROJECT_FILE}"
    text = PYPROJECT_FILE.read_text(encoding="utf-8")
    try:
        import tomllib  # Python >= 3.11
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception as exc:  # 换成可操作的中文报错
            return None, f"pyproject.toml 解析失败：{exc!r}"
        version = (data.get("project") or {}).get("version")
        if not version:
            return None, "pyproject.toml 的 [project] 段缺少 version 字段"
        return str(version), None
    # Python 3.10 兜底：逐行定位 [project] 段内的 version = "..."
    in_project = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if in_project:
            m = re.match(r"""version\s*=\s*["']([^"']+)["']""", line)
            if m:
                return m.group(1), None
    return None, "pyproject.toml 的 [project] 段找不到 version（且当前 Python 无 tomllib 可做深度解析）"


def find_changelog_section(version: str) -> tuple[str | None, str | None]:
    """返回 (段落文本, error)。段落标题接受 ## 5.0.0 / ## v5.0.0 / ## [5.0.0]。"""
    if not CHANGELOG_FILE.is_file():
        return None, f"找不到 {CHANGELOG_FILE}——发布说明必须有，不允许空着 tag 就发"
    text = CHANGELOG_FILE.read_text(encoding="utf-8")
    head = re.compile(r"^##\s+\[?v?" + re.escape(version) + r"\]?(?!\d)", re.MULTILINE)
    m = head.search(text)
    if not m:
        return None, (
            f"CHANGELOG.md 中没有版本 {version} 的段落（要求形如 \"## {version} ...\" 的标题行）。"
            "请先补写该版本的变更条目再打 tag。"
        )
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    section = text[m.start(): m.end() + (nxt.start() if nxt else len(rest))].strip()
    # 段落除标题外还得有正文，防空壳
    if len(section.splitlines()) < 2:
        return None, f"CHANGELOG.md 中版本 {version} 的段落是空的，请补写变更内容。"
    return section, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_release.py",
        description="发布前校验：tag / __version__ / pyproject / CHANGELOG 四方一致",
    )
    parser.add_argument("--tag", required=True, help="本次发布的 git tag，如 v5.0.0")
    args = parser.parse_args(argv)

    errors: list[str] = []
    ok_lines: list[str] = []

    version_from_tag, err = check_tag_format(args.tag)
    if err:
        errors.append(err)

    init_version, err = read_init_version()
    if err:
        errors.append(err)

    pyproject_version, err = read_pyproject_version()
    if err:
        errors.append(err)

    if version_from_tag and init_version:
        if version_from_tag == init_version:
            ok_lines.append(
                f"[通过] tag({args.tag}) 去 v 后 == __init__.__version__ == {init_version}"
            )
        else:
            errors.append(
                f"版本不一致：tag {args.tag!r} 去 v 后是 {version_from_tag!r}，"
                f"而 src/zhihu_downloader/__init__.py 的 __version__ 是 {init_version!r}。"
                "版本号唯一来源是 __init__.py——请改代码后重新打 tag，而不是改 tag 迁就代码。"
            )

    if init_version and pyproject_version:
        if init_version == pyproject_version:
            ok_lines.append(
                f"[通过] pyproject.toml version == __version__ == {pyproject_version}"
            )
        else:
            errors.append(
                f"版本漂移：pyproject.toml 是 {pyproject_version!r}，"
                f"__init__.py 是 {init_version!r}。v4 就栽在 6 处版本号各写各的——请统一为 __init__.py 的值。"
            )

    if version_from_tag:
        section, err = find_changelog_section(version_from_tag)
        if err:
            errors.append(err)
        elif section is not None:
            first_line = section.splitlines()[0]
            ok_lines.append(f"[通过] CHANGELOG.md 含版本段：{first_line}")

    for line in ok_lines:
        print(line)
    if errors:
        print()
        print("发布前校验未通过，共 " + str(len(errors)) + " 项问题：", file=sys.stderr)
        for i, e in enumerate(errors, 1):
            print(f"  [{i}] {e}", file=sys.stderr)
        print()
        print("修复以上问题后重新运行；CI 的 preflight job 会在同一脚本上把关。", file=sys.stderr)
        return 1

    print(f"全部校验通过：{args.tag} 可以发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
