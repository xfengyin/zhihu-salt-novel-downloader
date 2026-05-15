#!/bin/bash

set -e

echo "📦 开始构建知乎盐选小说下载器..."

# 检查 pyinstaller 是否安装
if ! command -v pyinstaller &> /dev/null; then
    echo "🔧 安装 pyinstaller..."
    uv pip install pyinstaller>=6.0.0
fi

# 创建构建目录
mkdir -p build dist

echo "🔨 构建 Linux 版本..."
pyinstaller pyinstaller.spec --clean -y

echo "✅ 构建完成！"
echo "📁 输出目录: dist/"
echo ""
echo "📖 使用方法:"
echo "  ./dist/zhihu-downloader --help"
echo "  ./dist/zhihu-downloader download --url <URL>"
echo "  ./dist/zhihu-downloader shelf --list"
