#!/usr/bin/env python3
"""v5.0.0 最终验收 harness（主审编写，冻结后一条命令出全量结论）。

  python scripts/acceptance.py

A1 全量 pytest / A2 ruff / A3 发布门禁 / A4 依赖铁律 / A5 版本单源
A6 GUI 全链路冒烟（假引擎注入，零网络零真实家目录）/ A7 静态资源 / A8 敏感文件忽略
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (" — " + detail if detail else ""))


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, timeout=900)


def _top_imports(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods.append(node.module.split(".")[0])
    return mods


def _read_version() -> str:
    text = (SRC / "zhihu_downloader" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "__version__" in line and "=" in line:
            seg = line.split("=", 1)[1]
            for q in ('"', "'"):
                if q in seg:
                    return seg.split(q)[1]
    raise RuntimeError("__version__ 未找到")


def main() -> int:
    py = sys.executable

    # 注意：pyproject addopts 已含 -q，此处不再叠加（双 -q 会吞掉统计行）
    r = run([py, "-m", "pytest", "tests"])
    out = r.stdout + r.stderr
    m = re.search(r"(\d+) passed", out)
    n = int(m.group(1)) if m else 0
    if n == 0 and r.returncode == 0:  # 兜底：统计行缺失时数进度点
        n = sum(line.count(".") for line in out.splitlines()
                if re.match(r"^[.sFEx]+\s+\[\s*\d+%\]\s*$", line))
    check("A1 pytest", r.returncode == 0 and n >= 400, f"{n} passed")

    r = run([py, "-m", "ruff", "check", "src", "tests", "scripts"])
    last = (r.stdout + r.stderr).strip().splitlines()
    check("A2 ruff", r.returncode == 0, last[-1] if last else "")

    version = _read_version()
    r = run([py, "scripts/check_release.py", "--tag", "v" + version])
    check("A3 check_release", r.returncode == 0, "tag v" + version)

    # pydantic：fastapi 硬传递依赖；urllib3：requests 硬传递依赖（client 闸门与 HTTP 栈同解析器，主审裁决 R2-P0-2）
    ALLOWED = {"requests", "bs4", "fastapi", "uvicorn", "ebooklib",
               "browser_cookie3", "zhihu_downloader", "pydantic", "urllib3"}
    violations: set[str] = set()
    for f in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            violations.add(f.name + ":SYNTAX")
            continue
        for mod in _top_imports(tree):
            if mod not in ALLOWED and mod not in sys.stdlib_module_names:
                violations.add(f.name + ":" + mod)
    check("A4 依赖铁律", not violations,
          ",".join(sorted(violations)) or "仅白名单+标准库")

    bad: list[str] = []
    for f in sorted((SRC / "zhihu_downloader").rglob("*.py")):
        if f.name == "__init__.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[vV]?\d+\.\d+\.\d+", node.value):
                    bad.append(f.name)
    check("A5 版本单源", not bad, ",".join(sorted(set(bad))) or "无硬编码版本字面量")

    try:
        ok6, d6 = _gui_smoke()
    except Exception as e:  # noqa: BLE001
        ok6, d6 = False, f"EXC {type(e).__name__}: {str(e)[:200]}"
    check("A6 GUI 冒烟", ok6, d6)

    st = SRC / "zhihu_downloader" / "app" / "static"
    ok7 = all((st / x).exists() and (st / x).stat().st_size > 200
              for x in ("index.html", "app.js", "style.css"))
    check("A7 静态资源", ok7, "三件套存在且非占位")

    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    ok8 = "cookies.json" in gi and "shelf.json" in gi
    check("A8 敏感文件忽略", ok8, ".gitignore 覆盖 cookies/shelf")

    try:
        ok9, d9 = _security_pack()
    except Exception as e:  # noqa: BLE001
        ok9, d9 = False, f"EXC {type(e).__name__}: {str(e)[:160]}"
    check("A9 安全回归包", ok9, d9)

    try:
        ok10, d10 = _export_security_pack()
    except Exception as e:  # noqa: BLE001
        ok10, d10 = False, f"EXC {type(e).__name__}: {str(e)[:160]}"
    check("A10 导出面安全包", ok10, d10)

    try:
        ok11, d11 = _wrapup_pack()
    except Exception as e:  # noqa: BLE001
        ok11, d11 = False, f"EXC {type(e).__name__}: {str(e)[:160]}"
    check("A11 终局欠账包", ok11, d11)

    failed = [x[0] for x in RESULTS if not x[1]]
    print("\n" + ("ALL GREEN" if not failed else "NOT PASSED: " + repr(failed)))
    return 0 if not failed else 1


def _gui_smoke() -> tuple[bool, str]:
    sys.path.insert(0, str(SRC))
    from fastapi.testclient import TestClient  # noqa: I001  (sys.path 注入后本地导入块)
    from zhihu_downloader.app import server
    from zhihu_downloader.engine.client import ZhihuClient
    from zhihu_downloader.shelf.shelf import Shelf
    from zhihu_downloader.types import BookMeta, BookResult, ChapterRef, ProgressEvent

    tmp = Path(tempfile.mkdtemp(prefix="accept-"))
    out = tmp / "out"
    out.mkdir()

    def fake_resolve(client, url, *a, **k):
        return BookMeta(title="冒烟书", url=url, chapters=[
            ChapterRef(url=url + "/section/1", title="第一章", index=1),
            ChapterRef(url=url + "/section/2", title="第二章", index=2)])

    def fake_download(client, url, fmt="md", output_dir=".", progress=None,
                      resume=True, workers=3, meta=None, *a, **k):
        if progress:
            progress(ProgressEvent("toc", 0, 2, "", ""))
            progress(ProgressEvent("chapter", 1, 2, "第一章", ""))
            progress(ProgressEvent("chapter", 2, 2, "第二章", ""))
            progress(ProgressEvent("export", 2, 2, "", fmt))
            progress(ProgressEvent("done", 2, 2, "", ""))
        p = Path(output_dir) / "冒烟书.md"
        p.write_text("# ok\n", encoding="utf-8")
        return BookResult(title="冒烟书", url=url, chapters=2, files=[str(p)])

    server.resolve_book = fake_resolve
    server.download_book = fake_download
    client = ZhihuClient(cookie_file=tmp / "cookies.json", rate_limit=0)
    app = server.create_app(client=client, output_dir=out,
                            shelf=Shelf(path=tmp / "shelf.json"))
    url = "https://www.zhihu.com/market/paid_column/9"
    with TestClient(app) as c:
        h = c.get("/api/health")
        ok_h = h.status_code == 200 and bool(h.json().get("version"))
        ck = c.get("/api/cookies")
        ok_ck = ck.status_code == 200 and all(
            isinstance(v, bool) for v in ck.json().values())
        d = c.post("/api/download", json={"url": url, "format": "md"})
        ok_d = d.status_code == 200 and "task_id" in d.json()
        tid = d.json().get("task_id", "")
        e = c.get(f"/api/tasks/{tid}/events")
        ok_e = (e.status_code == 200 and b"[DONE]" in e.content
                and b'"kind"' in e.content)
        det = c.get(f"/api/tasks/{tid}")
        ok_det = det.status_code == 200 and det.json().get("status") == "done"
        fl = (det.json().get("files") or []) if ok_det else []
        fname = fl[0].rsplit("/", 1)[-1] if fl else ""
        fd = c.get(f"/api/files/{tid}/{fname}") if fname else None
        ok_file = bool(fd) and fd.status_code == 200
        sh = c.get("/api/shelf")
        ok_sh = sh.status_code == 200 and len(sh.json()) == 1
        bad = c.post("/api/download", json={"url": "http://127.0.0.1:2298/x"})
        ok_ssrf = bad.status_code == 400
        trav = c.get(f"/api/files/{tid}/..%2f..%2fetc%2fpasswd")
        ok_trav = trav.status_code in (400, 404)
        idx = c.get("/")
        body = idx.content.lower()
        ok_idx = idx.status_code == 200 and (b"<html" in body or b"<!doctype" in body)
    flags = dict(health=ok_h, cookies_bool=ok_ck, dl=ok_d, sse_done=ok_e,
                 detail=ok_det, file=ok_file, shelf=ok_sh, ssrf400=ok_ssrf,
                 traversal=ok_trav, index=ok_idx)
    return all(flags.values()), " ".join(
        k + ("=Y" if v else "=N") for k, v in flags.items())


def _security_pack() -> tuple[bool, str]:
    """A9：R2 安全审查点名的线级回归（不依赖单测命名，直接打 API）。"""
    sys.path.insert(0, str(SRC))
    from fastapi.testclient import TestClient

    from zhihu_downloader.app import server
    from zhihu_downloader.engine.client import ZhihuClient
    from zhihu_downloader.shelf.shelf import Shelf

    tmp = Path(tempfile.mkdtemp(prefix="sec-"))
    client = ZhihuClient(cookie_file=tmp / "cookies.json", rate_limit=0)
    app = server.create_app(client=client, output_dir=tmp,
                            shelf=Shelf(path=tmp / "shelf.json"))
    with TestClient(app) as c:
        # P0-2：反斜杠/@ 解析器差分载荷必须 400
        p1 = c.post("/api/download", json={
            "url": "http://127.0.0.1:9501\\@www.zhihu.com/question/1/answer/2"})
        p2 = c.post("/api/download",
                    json={"url": "http://169.254.169.254@www.zhihu.com/x"})
        # P0-3：跨站 Origin 的无 body 写请求必须 403
        o1 = c.post("/api/qrcode", headers={"Origin": "http://evil.example"})
        o2 = c.post("/api/shelf/nonexistent/update",
                    headers={"Origin": "http://evil.example"})
        # 同源 Origin 必须放行（用不触网的端点：不存在的 id → 404 而非 403）
        o3 = c.post("/api/shelf/nonexistent/update",
                    headers={"Origin": "http://127.0.0.1:3000"})
        # P0-3：docs/openapi 关闭
        d1 = c.get("/docs")
        d2 = c.get("/openapi.json")
        # 安全头
        idx = c.get("/")
        csp = "default-src" in idx.headers.get("content-security-policy", "")
        nosniff = idx.headers.get("x-content-type-options") == "nosniff"
        frame = idx.headers.get("x-frame-options") == "DENY"
    ok = (p1.status_code == 400 and p2.status_code == 400
          and o1.status_code == 403 and o2.status_code == 403
          and o3.status_code == 404
          and d1.status_code == 404 and d2.status_code == 404
          and csp and nosniff and frame)
    detail = (f"backslash={p1.status_code} at={p2.status_code} "
              f"xorigin={o1.status_code}/{o2.status_code} "
              f"sameorigin={o3.status_code} docs={d1.status_code}/{d2.status_code} "
              f"csp={csp} nosniff={nosniff} frame={frame}")
    return ok, detail


def _export_security_pack() -> tuple[bool, str]:
    """A10：R2 #4/#5/#8 的线级回归（纯函数直调，零网络）。"""
    sys.path.insert(0, str(SRC))
    import zipfile  # noqa: TC003  （A10 现场用）

    from zhihu_downloader.export import export_book
    from zhihu_downloader.types import Article, Block

    tmp = Path(tempfile.mkdtemp(prefix="sec10-"))
    out10 = tmp / "out"
    out10.mkdir()
    # 真实 PNG 放 output_dir 之外的"受害者目录"（realpath 不在导出目录内才命中 R2#5）
    victim = tmp / "victim"
    victim.mkdir()
    secret_png = victim / "tax_return.png"
    secret_png.write_bytes(bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000a49444154789c6360000002000100ffff03000006000"
        "554bf32590000000049454e44ae426082"))
    evil = "<script>alert(1)</script>"
    art = Article(url="https://www.zhihu.com/market/paid_column/9/section/1",
                  title="第一章", blocks=[Block("p", evil),
                                          Block("img", "", src=str(secret_png), alt="x")])
    # #4：md 不得含裸 <script
    files = export_book("测试书", [art], "md", out10)
    md_text = Path(files[0]).read_text(encoding="utf-8")
    ok_md = "<script>" not in md_text and "onerror" not in md_text.lower() or "<script>" not in md_text
    ok_md = "<script>" not in md_text
    # #5：epub 不得内嵌绝对路径指向的本机文件
    efiles = export_book("测试书", [art], "epub", out10)
    with zipfile.ZipFile(efiles[0]) as z:
        names = z.namelist()
        img_entries = [n for n in names if "/images/" in n.lower()]
        embedded = len(img_entries) > 0
    ok_epub = not embedded  # output_dir 外的本机 PNG 必须被降级，零图片条目
    # #5b containment 正向锁（主审 round49 可执行冻结）：框内绝对 src **必须**内嵌成功。
    # 本判据把规则焊死在门禁里：谁翻回「绝对一律拒」的严格版，A10 即 FAIL。
    inside = out10 / "in_dir.png"
    inside.write_bytes(secret_png.read_bytes())
    art2 = Article(url="https://www.zhihu.com/market/paid_column/9/section/1",
                   title="锁定", blocks=[Block("img", "", src=str(inside), alt="y")])
    efiles2 = export_book("锁定书", [art2], "epub", out10)
    with zipfile.ZipFile(efiles2[0]) as z2:
        ok_inside = any("/images/" in n.lower() for n in z2.namelist())
    ok_epub = ok_epub and ok_inside
    # #8：cookies.save 权限原子性（umask=0 环境）
    from zhihu_downloader.auth import cookies as ck  # noqa: PLC0415
    old_mask = os.umask(0)
    try:
        ckpath = tmp / "cookies.json"
        ck.save({"z_c0": "x", "d_c0": "y"}, ckpath)
        mode = os.stat(ckpath).st_mode & 0o777
    finally:
        os.umask(old_mask)
    ok_perm = mode == 0o600
    ok = ok_md and ok_epub and ok_perm
    return ok, (f"md_escape={ok_md} epub_no_local={ok_epub}(inside_lock={ok_inside}) "
                f"cookies_0600={ok_perm}(mode={oct(mode)})")


def _wrapup_pack() -> tuple[bool, str]:
    """A11：I3 final4 的线级钉（#9 三重加固/就绪探针/R2-B 文案/横幅死链）。"""
    sys.path.insert(0, str(SRC))
    checks: dict[str, bool] = {}
    from zhihu_downloader import update as up
    # 9a：超长数字段不抛（CPython 4300 位上限）
    try:
        checks["9a_int_limit"] = up.parse_version("9" * 5000) == (0,)
    except Exception:  # noqa: BLE001
        checks["9a_int_limit"] = False
    # 9b：渲染边界——剥控制序列 + Releases 前缀白名单 + 截断
    esc = chr(27)
    prefix = "https://github.com/xfengyin/zhihu-salt-novel-downloader/releases/"
    try:
        evil = up.format_release_hint({
            "has_update": True, "latest": "9" * 300 + esc + "]52;cAAAA",
            "url": "https://evil.test/" + esc + "]8;;http://phish"})
        good = up.format_release_hint({
            "has_update": True, "latest": "v9.9.9",
            "url": prefix + "tag/v9.9.9"})
        checks["9b_escape_whitelist"] = (
            esc not in evil and "evil.test" not in evil and "phish" not in evil
            and len(evil) < 400 and prefix in good and "9" * 300 not in good)
    except Exception:  # noqa: BLE001
        checks["9b_escape_whitelist"] = False
    # R2-B 四条稿 + 就绪探针 + 无 /docs 死链（cli.py 文本特征）
    cli_src = (SRC / "zhihu_downloader" / "cli.py").read_text(encoding="utf-8")
    checks["r2b_four_risks"] = ("内网" in cli_src and "覆盖" in cli_src
                                and "读取你的 Cookie" not in cli_src)
    checks["no_docs_banner"] = "API 文档" not in cli_src
    checks["health_readiness"] = "api/health" in cli_src
    # 主审接线：CLI shelf remove 必须 prune（镜像 server DELETE；防未来重写丢件）
    checks["cli_shelf_prune"] = ("CheckpointStore(state_dir, book_key=book.url).prune()" in cli_src
                                 or "book_key=book.url).prune()" in cli_src)
    ok = all(checks.values())
    return ok, " ".join(k + ("=Y" if v else "=N") for k, v in checks.items())


if __name__ == "__main__":
    raise SystemExit(main())
