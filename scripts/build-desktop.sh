#!/usr/bin/env bash
# ============================================================================
# 构建桌面端发布包
# ============================================================================
# 用法：
#   ./scripts/build-desktop.sh           # 构建当前平台
#   ./scripts/build-desktop.sh --linux   # 仅 Linux
#   ./scripts/build-desktop.sh --macos   # 仅 macOS
#   ./scripts/build-desktop.sh --windows # 仅 Windows
#
# 前置依赖：
#   - Rust 工具链（cargo, rustc）
#   - Node.js 18+ 与 npm
#   - Tauri 2.x 平台依赖（参见 https://v2.tauri.app/start/prerequisites/）
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[build]${NC} $*"; }
warn() { echo -e "${YELLOW}[build]${NC} $*"; }
err() { echo -e "${RED}[build]${NC} $*" >&2; }

# 1. 检查环境
log "检查构建环境..."
if ! command -v cargo >/dev/null 2>&1; then
    err "未找到 cargo，请先安装 Rust：https://rustup.rs/"
    exit 1
fi
if ! command -v node >/dev/null 2>&1; then
    err "未找到 node，请先安装 Node.js 18+"
    exit 1
fi

# 2. 构建前端
log "构建前端..."
cd "${PROJECT_ROOT}/web"
if [ ! -d "node_modules" ]; then
    log "安装前端依赖..."
    npm install
fi
npm run build
log "前端构建完成：web/dist"

# 3. 构建 Tauri 桌面端
log "构建 Tauri 桌面端..."
cd "${PROJECT_ROOT}/web/src-tauri"
case "${1:-}" in
    --linux)
        log "目标平台：Linux"
        cargo tauri build --target deb
        cargo tauri build --target appimage
        ;;
    --macos)
        log "目标平台：macOS"
        cargo tauri build --target universal-apple-darwin
        ;;
    --windows)
        log "目标平台：Windows"
        cargo tauri build --target nsis
        cargo tauri build --target msi
        ;;
    *)
        log "目标平台：当前平台全量构建"
        cargo tauri build
        ;;
esac

log "构建完成！产物路径：web/src-tauri/target/release/bundle/"
