@echo off
setlocal enabledelayedexpansion

echo 正在构建知乎盐选小说下载器...

:: 检查 pyinstaller 是否安装
pyinstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo 安装 pyinstaller...
    uv pip install pyinstaller>=6.0.0
)

:: 创建构建目录
if not exist build mkdir build
if not exist dist mkdir dist

echo 构建 Windows 版本...
pyinstaller pyinstaller.spec --clean -y

echo 构建完成！
echo 输出目录: dist\
echo.
echo 使用方法:
echo   dist\zhihu-downloader.exe --help
echo   dist\zhihu-downloader.exe download --url ^<URL^>
echo   dist\zhihu-downloader.exe shelf --list
