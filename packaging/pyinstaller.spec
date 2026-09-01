# -*- mode: python ; coding: utf-8 -*-
"""知乎盐选小说下载器 v5 —— PyInstaller spec（onefile，三平台共用一份）。

用法（在仓库根目录或 packaging/ 下执行均可，路径全部相对 SPECPATH 解析）：

    pyinstaller packaging/pyinstaller.spec --clean -y --distpath dist --workpath build

产物（名称内嵌版本号与平台，供 release.yml 聚合发布直接取用）：
    dist/zhihu-downloader-<version>-<platform>          Linux ELF / macOS Mach-O
    dist/zhihu-downloader-<version>-windows-x64.exe     Windows PE（PyInstaller 自动加 .exe）

产品形态（架构规格书 §2.15「双击即用」）：
    console=True —— 终端保留日志输出；Windows 用户双击 EXE 时 argv 无子命令，
    cli.main() 按 §2.15 等价于 "gui"：起本地服务 + 自动开浏览器。
    入口直接用 src/zhihu_downloader/__main__.py（v5 已改为绝对导入
    "from zhihu_downloader.cli import main"，不再需要 v4 那种临时生成入口包装脚本）。

v4 教训 → v5 对策（逐条落实）：
    1. 旧根 spec 用 Path(os.getcwd()) 定位项目根 → 一切路径以 SPECPATH 为锚，与 cwd 无关；
    2. 旧 spec 对 collect_all(...) 用 except Exception: pass 静默吞错 → 失败立即 raise，
       禁止降级出「能跑但缺件」的包；
    3. 旧 spec upx=True 但 CI 无 upx，是无效开关 → upx=False，少一个假变量；
    4. uvicorn 全靠字符串动态导入（loops/protocols/lifespan），静态分析必漏 →
       collect_submodules("uvicorn") 兜底 + 显式列出 auto 系列（参考 v4 simple/pyinstaller.spec）；
    5. 旧产物名不带版本、发布时靠 workflow 改名 → spec 内从 __version__ 单一来源取名，
       版本号漂移在打包这一刻就无处遁形（读不到 __version__ 直接 raise）。
"""

import platform
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ---------------------------------------------------------------------------
# 路径锚点：SPECPATH 由 PyInstaller 注入 = 本 spec 所在目录（packaging/）。
# 禁止 os.getcwd()：CI 与本地手动构建的 cwd 不同，旧版因此踩坑。
# ---------------------------------------------------------------------------
SPEC_DIR = Path(SPECPATH).resolve()           # <repo>/packaging
REPO_ROOT = SPEC_DIR.parent                   # <repo>
SRC_DIR = REPO_ROOT / "src"                   # <repo>/src
PKG_DIR = SRC_DIR / "zhihu_downloader"        # 包根（入口所在）
STATIC_SRC = PKG_DIR / "app" / "static"       # 原生 Web UI（零构建步骤，铁律 2）

def _say(msg):
    """Windows 控制台安全打印：cp1252/cp936 编不出中文时降级为替换符，绝不炸构建。

    v5.0.0 教训：spec 里 print("[spec] 已内嵌静态资源…") 在 windows runner 的
    cp1252 stdout 上抛 UnicodeEncodeError，PyInstaller 直接退出 1——Linux/macOS
    全绿、唯独 Windows 挂，且本地测试永远复现不了。中文用户机器同理，必须治在 spec 里。
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


block_cipher = None

# ---------------------------------------------------------------------------
# 版本号：唯一来源 src/zhihu_downloader/__init__.py:__version__（铁律 4）。
# 不 import 包本体（构建环境未必装好依赖），用正则直读文本。
# ---------------------------------------------------------------------------
_INIT_TEXT = (PKG_DIR / "__init__.py").read_text(encoding="utf-8")
_VERSION_M = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", _INIT_TEXT, re.MULTILINE)
if not _VERSION_M:
    raise RuntimeError(
        f"[spec] 无法从 {PKG_DIR / '__init__.py'} 读到 __version__——"
        "版本号是发布链路的单一事实源，读不到即打包中止，禁止凭记忆填版本"
    )
VERSION = _VERSION_M.group(1)


def _platform_tag() -> str:
    """产物名里的平台段：windows-x64 / linux-x64 / linux-arm64 / macos-arm64 / macos-x64。

    与 release.yml 矩阵的 platform 标签保持同一口径（x86_64/amd64 一律归一为 x64），
    避免「workflow 标签叫 linux-x64、产物文件却叫 linux-x86_64」的命名漂移。
    """
    machine = (platform.machine() or "").lower()
    arch_map = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}
    arch = arch_map.get(machine, machine or "unknown")
    os_map = {"win32": "windows", "cygwin": "windows", "linux": "linux", "darwin": "macos"}
    os_name = os_map.get(sys.platform, sys.platform)
    return f"{os_name}-{arch}"


PLATFORM_TAG = _platform_tag()
EXE_NAME = f"zhihu-downloader-{VERSION}-{PLATFORM_TAG}"

# ---------------------------------------------------------------------------
# 隐式导入：uvicorn 的 loops/protocols/lifespan 全部经字符串动态导入，
# 静态分析发现不了（旧版 EXE 双击闪退的头号原因）。
# collect_submodules 兜全 uvicorn 子模块，auto 系列再显式钉一遍双保险。
# ---------------------------------------------------------------------------
hiddenimports = [
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
    # ebooklib 在 export/epub.py 里延迟导入，显式声明避免漏打包
    "ebooklib",
]
# collect_submodules 失败同样会直接炸——吞错只会把问题留给最终用户
hiddenimports += collect_submodules("uvicorn")

datas = []
binaries = []

# 运行时 5 依赖（铁律 1）逐个 collect_all：数据文件 + 子模块一网打尽。
# v4 教训：except Exception: pass 让缺依赖的残包一路绿灯发到用户手里。
for package in ("fastapi", "uvicorn", "ebooklib", "bs4", "requests"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    except Exception as exc:  # 捕获只为换更有用的报错，随后立即 raise——绝不吞
        raise RuntimeError(
            f"[spec] collect_all({package!r}) 失败，打包中止。"
            f"请确认该包已随 pip install . 装入当前构建环境。原始错误：{exc!r}"
        ) from exc
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# ---------------------------------------------------------------------------
# 内嵌 Web UI 静态资源：app/server.py 以 Path(__file__).parent / "static" 定位；
# onefile 运行时 __file__ 落在 sys._MEIPASS 下，故 dest 必须是
# zhihu_downloader/app/static，与源码树同构。
# 「双击即用」是产品级承诺：静态资源缺失 = 残废产物，直接 raise（v4 只 print 警告放行）。
# ---------------------------------------------------------------------------
if not (STATIC_SRC / "index.html").is_file():
    raise RuntimeError(
        f"[spec] 未找到 Web UI 静态资源 {STATIC_SRC / 'index.html'} —— "
        "v5 的产品形态是双击即用（GUI+浏览器），缺前端页面打包出来就是废件，中止。"
    )
datas.append((str(STATIC_SRC), "zhihu_downloader/app/static"))
_say(f"[spec] 已内嵌静态资源: {STATIC_SRC}")

hiddenimports = sorted(set(hiddenimports))

_say(f"[spec] 构建目标: {EXE_NAME} (onefile, console=True, python={sys.version.split()[0]})")

a = Analysis(
    [str(PKG_DIR / "__main__.py")],  # v5 绝对导入入口，等价 python -m zhihu_downloader
    pathex=[str(SRC_DIR)],           # 未 pip install 时也能解析 zhihu_downloader 包
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "tests",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # CI 无 upx：旧版 upx=True 是无效开关，删掉假变量
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,        # 终端保留日志；双击无参数时 cli 按 §2.15 起 GUI+开浏览器
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
