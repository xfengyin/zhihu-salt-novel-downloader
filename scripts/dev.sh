#!/usr/bin/env bash
# ============================================================================
# 启动开发环境：后端 FastAPI + 前端 Vite
# ============================================================================
# 用法：
#   ./scripts/dev.sh                # 启动后端和前端（推荐）
#   ./scripts/dev.sh --backend      # 仅启动后端
#   ./scripts/dev.sh --frontend     # 仅启动前端
#
# 停止：Ctrl+C 同时终止所有子进程
# ============================================================================

set -euo pipefail

# 定位项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

# 配置
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-3000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[dev]${NC} $*"; }
warn() { echo -e "${YELLOW}[dev]${NC} $*"; }
err() { echo -e "${RED}[dev]${NC} $*" >&2; }

# 检查 uv
if ! command -v uv >/dev/null 2>&1; then
    err "未找到 uv，请先安装：curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 启动后端
start_backend() {
    log "准备启动后端服务（端口 ${BACKEND_PORT}）..."
    if [ ! -d ".venv" ]; then
        log "创建虚拟环境..."
        uv venv .venv
    fi
    log "安装依赖..."
    uv sync --frozen 2>/dev/null || uv sync

    log "启动后端：uv run zhihu-downloader serve --host ${BACKEND_HOST} --port ${BACKEND_PORT}"
    uv run zhihu-downloader serve --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" &
    BACKEND_PID=$!
    echo "${BACKEND_PID}" > /tmp/zhihu-backend.pid
    log "后端 PID: ${BACKEND_PID}"
}

# 启动前端
start_frontend() {
    log "准备启动前端服务（端口 ${FRONTEND_PORT}）..."
    cd "${PROJECT_ROOT}/web"
    if [ ! -d "node_modules" ]; then
        log "安装前端依赖..."
        npm install
    fi
    log "启动前端：npm run dev"
    npm run dev &
    FRONTEND_PID=$!
    echo "${FRONTEND_PID}" > /tmp/zhihu-frontend.pid
    log "前端 PID: ${FRONTEND_PID}"
    cd "${PROJECT_ROOT}"
}

# 清理
cleanup() {
    warn "正在停止所有子进程..."
    [ -n "${BACKEND_PID:-}" ] && kill "${BACKEND_PID}" 2>/dev/null || true
    [ -n "${FRONTEND_PID:-}" ] && kill "${FRONTEND_PID}" 2>/dev/null || true
    [ -f /tmp/zhihu-backend.pid ] && kill "$(cat /tmp/zhihu-backend.pid)" 2>/dev/null || true
    [ -f /tmp/zhihu-frontend.pid ] && kill "$(cat /tmp/zhihu-frontend.pid)" 2>/dev/null || true
    rm -f /tmp/zhihu-backend.pid /tmp/zhihu-frontend.pid
    exit 0
}

trap cleanup INT TERM

# 主流程
case "${1:-}" in
    --backend)
        start_backend
        wait ${BACKEND_PID}
        ;;
    --frontend)
        start_frontend
        wait ${FRONTEND_PID}
        ;;
    *)
        start_backend
        sleep 2
        start_frontend
        log "后端: http://localhost:${BACKEND_PORT}/docs"
        log "前端: http://localhost:${FRONTEND_PORT}/"
        log "按 Ctrl+C 停止"
        wait
        ;;
esac
