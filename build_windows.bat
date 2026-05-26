@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================================
echo   剪映字幕助手 — Windows 一键构建脚本
echo   Draft SRT Assistant Build Script
echo ============================================================
echo.

:: ------------------------------------------------------------------
:: Step 0 — Check for required tools
:: ------------------------------------------------------------------
echo [1/4] 检查构建环境...

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo   ✓ Python 已就绪

where pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 正在安装 PyInstaller...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)
echo   ✓ PyInstaller 已就绪

where iscc >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [!] 未找到 Inno Setup 编译器 (iscc)
    echo     请从以下地址下载安装 Inno Setup:
    echo     https://jrsoftware.org/isdl.php
    echo.
    echo     安装完成后重新运行本脚本即可。
    echo     如果不需要 .exe 安装包，PyInstaller 已生成的 dist\剪映字幕助手\
    echo     文件夹可直接分发使用。
    echo.
    choice /c yn /m "是否继续（仅生成 PyInstaller 产物，跳过安装包）"
    if errorlevel 2 exit /b 0
    set SKIP_INNO=1
) else (
    echo   ✓ Inno Setup 已就绪
    set SKIP_INNO=0
)

:: ------------------------------------------------------------------
:: Step 1 — Install Python dependencies
:: ------------------------------------------------------------------
echo.
echo [2/4] 安装 Python 依赖...
pip install PyQt6>=6.5.0
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo   ✓ 依赖安装完成

:: ------------------------------------------------------------------
:: Step 2 — PyInstaller build
:: ------------------------------------------------------------------
echo.
echo [3/4] PyInstaller 打包中（可能需要几分钟）...

if exist dist\剪映字幕助手 rmdir /s /q dist\剪映字幕助手
if exist build rmdir /s /q build

pyinstaller build_win.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo [错误] PyInstaller 打包失败
    pause
    exit /b 1
)
echo   ✓ PyInstaller 打包完成

:: ------------------------------------------------------------------
:: Step 3 — Inno Setup installer
:: ------------------------------------------------------------------
echo.
echo [4/4] 生成安装包...

if "%SKIP_INNO%"=="1" (
    echo   ! 跳过 Inno Setup（未安装）
    echo.
    echo ============================================================
    echo   构建完成！
    echo   可分发目录:  dist\剪映字幕助手\
    echo ============================================================
    pause
    exit /b 0
)

if not exist Output mkdir Output
iscc installer.iss
if %errorlevel% neq 0 (
    echo [错误] Inno Setup 打包失败
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   构建完成！
echo   安装包位置:  Output\剪映字幕助手_Setup_v*.exe
echo   可分发目录:  dist\剪映字幕助手\
echo ============================================================
echo.
echo   安装包功能:
echo     - 支持 Windows 7 及以上系统
echo     - 支持自定义安装目录
echo     - 创建开始菜单快捷方式
echo     - 可选创建桌面快捷方式
echo     - 自带卸载程序
echo ============================================================

pause
endlocal
