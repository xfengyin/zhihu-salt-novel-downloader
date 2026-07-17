#!/usr/bin/env bash
# ============================================================================
# 在 Linux 云端环境交叉编译构建 Windows exe
# ============================================================================
# 原理：使用 Wine64 运行 Windows Python + PyInstaller 进行交叉编译
#
# 用法：
#   ./scripts/build-windows-exe.sh
#
# 前置依赖（脚本会自动安装）：
#   - wine64
#   - Windows Python 3.12 embeddable
#   - 项目所有 Python 依赖
#
# 产物：
#   dist/zhihu-downloader.exe
#   zhihu-downloader-windows-x64.zip
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[build-win]${NC} $*"; }
info() { echo -e "${BLUE}[build-win]${NC} $*"; }
warn() { echo -e "${YELLOW}[build-win]${NC} $*"; }
err() { echo -e "${RED}[build-win]${NC} $*" >&2; }

# 配置
PYTHON_VERSION="3.12.8"
PYTHON_DIR="/opt/python-win/python312"
WINEPREFIX_DIR="${WINEPREFIX:-/root/.wine64}"
WINE="/usr/lib/wine/wine64"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

cd "${PROJECT_ROOT}"

# ------------------------------------------------------------------
# 1. 检查并安装 Wine64
# ------------------------------------------------------------------
log "步骤 1/5: 检查 Wine64..."
if ! command -v wine64 >/dev/null 2>&1 && [ ! -x "${WINE}" ]; then
    warn "未找到 wine64，开始安装..."
    dpkg --add-architecture i386 2>/dev/null || true
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends wine64
fi

# 初始化 Wine 前缀
export WINEPREFIX="${WINEPREFIX_DIR}"
export WINEDEBUG=-all
export WINEARCH=win64

if [ ! -d "${WINEPREFIX_DIR}" ]; then
    log "初始化 Wine 前缀..."
    "${WINE}" wineboot --init 2>&1 | tail -3
fi

log "Wine 版本: $(${WINE} --version 2>&1)"

# ------------------------------------------------------------------
# 2. 下载并配置 Windows Python
# ------------------------------------------------------------------
log "步骤 2/5: 配置 Windows Python ${PYTHON_VERSION}..."
if [ ! -x "${PYTHON_DIR}/python.exe" ]; then
    mkdir -p /opt/python-win
    cd /opt/python-win

    PYTHON_ZIP="python-${PYTHON_VERSION}-embed-amd64.zip"
    if [ ! -f "${PYTHON_ZIP}" ]; then
        log "下载 Python ${PYTHON_VERSION} embeddable..."
        curl -fsSL -o "${PYTHON_ZIP}" \
            "https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_ZIP}"
    fi

    log "解压 Python..."
    unzip -q "${PYTHON_ZIP}" -d python312

    # 启用 site-packages
    cat > python312/python312._pth <<EOF
python312.zip
.
Lib\site-packages

import site
EOF

    # 安装 pip
    log "安装 pip..."
    curl -fsSL -o get-pip.py https://bootstrap.pypa.io/get-pip.py
    "${WINE}" python312/python.exe get-pip.py 2>&1 | tail -3

    cd "${PROJECT_ROOT}"
fi

PYTHON="${PYTHON_DIR}/python.exe"
log "Python 版本: $(${WINE} ${PYTHON} -c 'import sys; print(sys.version)' 2>&1)"

# ------------------------------------------------------------------
# 3. 安装项目依赖
# ------------------------------------------------------------------
log "步骤 3/5: 安装项目依赖到 Wine Python..."

# 解析 pyproject.toml 中的依赖
${WINE} ${PYTHON} -m pip install -i ${PIP_INDEX_URL} --upgrade pip wheel setuptools 2>&1 | tail -3

# 安装所有运行时依赖 + pyinstaller
${WINE} ${PYTHON} -m pip install -i ${PIP_INDEX_URL} \
    "aiohttp>=3.9.0" \
    "beautifulsoup4>=4.12.0" \
    "click>=8.1.0" \
    "ebooklib>=0.18" \
    "lxml>=4.9.0" \
    "pyyaml>=6.0" \
    "requests>=2.31.0" \
    "pillow>=10.0.0" \
    "fastapi>=0.109.0" \
    "uvicorn[standard]>=0.27.0" \
    "pydantic>=2.5.0" \
    "pydantic-settings>=2.1.0" \
    "sqlalchemy>=2.0.0" \
    "pluggy>=1.6.0" \
    "nats-py>=2.15.0" \
    "python-jose[cryptography]>=3.5.0" \
    "passlib[bcrypt]>=1.7.4" \
    "httpx>=0.28.0" \
    "python-multipart>=0.0.3" \
    "email-validator>=2.3.0" \
    "aiosqlite" \
    "pyinstaller>=6.0.0" \
    2>&1 | tail -5

log "依赖安装完成"

# ------------------------------------------------------------------
# 4. 执行 PyInstaller 构建
# ------------------------------------------------------------------
log "步骤 4/5: 执行 PyInstaller 构建..."
export PYTHONIOENCODING=utf-8

cd "${PROJECT_ROOT}"
rm -rf build dist

${WINE} ${PYTHON} -m PyInstaller pyinstaller.spec --clean -y --log-level WARN 2>&1 | \
    grep -v "SyntaxWarning\|warnings.filterwarnings\|assertWarningList\|with self\|(" || true

if [ ! -f "dist/zhihu-downloader.exe" ]; then
    err "构建失败：dist/zhihu-downloader.exe 不存在"
    exit 1
fi

log "构建成功！"
ls -lh dist/zhihu-downloader.exe
file dist/zhihu-downloader.exe

# ------------------------------------------------------------------
# 5. 验证并打包
# ------------------------------------------------------------------
log "步骤 5/5: 验证 exe 并打包..."

info "验证 exe 可运行..."
${WINE} dist/zhihu-downloader.exe --help 2>&1 | head -10

# 生成说明文件
cat > dist/README-使用说明.txt <<'README_EOF'
=================================================
  知乎盐选小说下载器 v3.1.0 - Windows 可执行程序
=================================================

【文件说明】
  zhihu-downloader.exe   主程序（单文件，无需安装 Python）

【🌟 最简单的使用方式】
  直接双击 zhihu-downloader.exe 即可！
  程序会自动：
    1. 启动 Web 服务（默认端口 3000）
    2. 打开默认浏览器访问 Web 界面
    3. 在浏览器中即可使用全部功能（下载、书架、设置）

  关闭服务：关闭弹出的命令行窗口，或按 Ctrl+C

【快速开始（命令行模式）】

  # 查看所有命令
  zhihu-downloader.exe --help

  # 双击启动 = 等同于
  zhihu-downloader.exe serve

  # 启动 Web 服务（不自动打开浏览器）
  zhihu-downloader.exe serve --no-browser

  # 指定端口
  zhihu-downloader.exe serve --port 8080

  # 仅本机访问（更安全）
  zhihu-downloader.exe serve --host 127.0.0.1

【常用下载命令】

  # 下载单本小说（Markdown 格式）
  zhihu-downloader.exe download -u "https://www.zhihu.com/market/book/12345" -f md

  # 自动从浏览器读取 Cookie 下载
  zhihu-downloader.exe download -u "https://www.zhihu.com/market/book/12345" --auto-cookie

  # 批量下载（urls.txt 每行一个URL）
  zhihu-downloader.exe download -b urls.txt -f epub

  # 断点续传
  zhihu-downloader.exe download -u "https://www.zhihu.com/market/book/12345" --resume

  # 查看书架
  zhihu-downloader.exe shelf --list

【访问地址（启动 serve 后）】
  Web 界面: http://127.0.0.1:3000
  API 文档: http://127.0.0.1:3000/docs
  OpenAPI:  http://127.0.0.1:3000/openapi.json

【环境要求】
  - Windows 10/11 64位
  - 无需安装 Python（已打包）
  - 首次运行如果被杀毒软件拦截，请添加信任

【合规声明】
  本工具仅限用于已购买内容的个人离线阅读。
  请勿用于内容分发、商业使用或侵权传播。
README_EOF

# 复制图标
cp web/src-tauri/icons/icon.ico dist/ 2>/dev/null || true

# 打包 zip
ZIP_NAME="zhihu-downloader-windows-x64.zip"
rm -f "${ZIP_NAME}"
cd dist && zip -9 "../${ZIP_NAME}" zhihu-downloader.exe README-使用说明.txt icon.ico 2>&1 | tail -3
cd "${PROJECT_ROOT}"

log "=============================================="
log "  ✅ 构建完成！"
log "=============================================="
log "  exe 文件:  dist/zhihu-downloader.exe"
log "  zip 分发:  ${ZIP_NAME}"
log "  文件大小:  $(ls -lh ${ZIP_NAME} | awk '{print $5}')"
log "=============================================="
