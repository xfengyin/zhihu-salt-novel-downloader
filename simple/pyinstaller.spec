# -*- mode: python ; coding: utf-8 -*-
"""极简 v4 PyInstaller spec —— onefile CLI + 内嵌 Web 静态资源。

用法（在 simple/ 目录下执行）：
    cd simple
    pyinstaller pyinstaller.spec --clean -y

产物：
    dist/zhihu-downloader       （Linux ELF）
    dist/zhihu-downloader.exe   （Windows PE，Windows 上自动加 .exe）

静态资源兼容性：
    webapp.py 使用 `Path(__file__).parent / "static"` 定位前端资源。
    onefile 打包后 `__file__` 指向 `sys._MEIPASS/zhihu_downloader/webapp.py`，
    因此只需把 static/ 放到 bundle 内的 `zhihu_downloader/static` 即可被 webapp 找到，
    无需改动后端源码。
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# spec 所在目录（simple/），与 cwd 无关，保证从仓库根目录或 simple/ 调用都可用
SPEC_DIR = Path(SPECPATH).resolve()

block_cipher = None

# ---------------------------------------------------------------------------
# 入口说明：
#   `zhihu_downloader/__main__.py` 使用相对导入 `from .cli import main`。
#   PyInstaller 以顶层脚本方式运行 __main__.py 时 __package__ 为空，
#   会导致运行时 `attempted relative import with no known parent package`。
#   因此这里在 build/（gitignore 目录）生成一个等价的绝对导入入口包装脚本，
#   完全等价于 `python -m zhihu_downloader`，无需改动后端源码。
# ---------------------------------------------------------------------------
ENTRY_DIR = SPEC_DIR / "build"
ENTRY_DIR.mkdir(parents=True, exist_ok=True)
ENTRY = ENTRY_DIR / "_zhihu_entry.py"
ENTRY.write_text(
    "from zhihu_downloader.cli import main\n"
    "\n"
    "if __name__ == '__main__':\n"
    "    raise SystemExit(main())\n",
    encoding="utf-8",
)

STATIC_SRC = SPEC_DIR / "zhihu_downloader" / "static"

datas = []
binaries = []
hiddenimports = [
    # uvicorn 通过字符串动态导入的协议 / 日志 / 事件循环实现
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # ebooklib 在 exporters.py 的 try/except 中延迟导入，显式声明避免漏打包
    "ebooklib",
]

# 收集三方包数据文件与子模块（fastapi / uvicorn / ebooklib / bs4 / requests）
for package in ["fastapi", "uvicorn", "ebooklib", "bs4", "requests"]:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

# 内嵌前端静态资源：webapp.py 在 frozen 下通过 sys._MEIPASS/zhihu_downloader/static 定位
if (STATIC_SRC / "index.html").exists():
    datas.append((str(STATIC_SRC), "zhihu_downloader/static"))
    print(f"[spec] 已内嵌静态资源: {STATIC_SRC}")
else:
    print(f"[spec] 警告: 未找到 {STATIC_SRC}，产物将无前端页面")

hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    [str(ENTRY)],
    pathex=[str(SPEC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "test",
        "tests",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="zhihu-downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
