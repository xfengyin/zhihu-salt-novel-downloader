# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - 知乎盐选小说下载器 Windows/Linux 打包配置

构建产物：
  - onefile 模式：单个可执行文件 zhihu-downloader(.exe)
  - 包含 CLI 子命令：download / shelf / serve
  - 包含 FastAPI 服务、SQLAlchemy、Pydantic 等全部依赖
  - 包含前端 Web 界面静态资源（serve 启动后浏览器即可访问）

使用方式：
  pyinstaller pyinstaller.spec --clean -y

注意：
  - Windows 上构建产出 .exe
  - Linux 上构建产出 ELF 二进制
  - 跨平台构建请使用 Wine 或 Docker
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ------------------------------------------------------------------
# 收集隐式依赖（PyInstaller 静态分析无法发现的动态导入）
# ------------------------------------------------------------------
hiddenimports = [
    # FastAPI / Starlette / Uvicorn
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
    "anyio._backends._asyncio",
    "email_validator",
    "dns.resolver",
    # SQLAlchemy
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.postgresql",
    "aiosqlite",
    # Pydantic
    "pydantic._internal._validators",
    # 认证
    "jose",
    "jose.jwt",
    "jose.backends",
    "jose.backends.cryptography_backend",
    "passlib.handlers.bcrypt",
    # 插件
    "pluggy",
    # 项目内部模块（确保全部打包）
    *collect_submodules("zhihu_downloader"),
]

# 收集三方库的数据文件与子模块
datas = []
binaries = []

for package in [
    "zhihu_downloader",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "sqlalchemy",
    "uvicorn",
    "jose",
    "passlib",
    "ebooklib",
    "lxml",
    "bs4",
]:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

# ------------------------------------------------------------------
# 打包前端 Web 界面静态资源
# ------------------------------------------------------------------
# 定位 web/dist 目录（构建前端后生成）
_project_root = Path(os.getcwd())
_web_dist = _project_root / "web" / "dist"

if _web_dist.is_dir() and (_web_dist / "index.html").exists():
    # 将 web/dist 整体打包到 exe 内的 web_dist/ 目录
    # 运行时通过 sys._MEIPASS/web_dist 访问
    datas.append((str(_web_dist), "web_dist"))
    print(f"[spec] 已包含前端静态资源: {_web_dist}")
else:
    print(f"[spec] 警告: 未找到前端构建产物 {_web_dist}，exe 将仅提供 API 服务")
    print("[spec] 请先执行: cd web && npm run build")

# 去重
hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    ["src/zhihu_downloader/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块以减小体积
        "tkinter",
        "unittest",
        "test",
        "tests",
        "pytest",
        "mypy",
        "ruff",
        "black",
        "isort",
        "IPython",
        "notebook",
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
    upx_exclude=[
        "vcruntime140.dll",
        "python3.dll",
        "python310.dll",
        "python311.dll",
        "python312.dll",
    ],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 图标（Windows）
    icon="web/src-tauri/icons/icon.ico" if sys.platform == "win32" else None,
)
