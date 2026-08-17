@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

title 剪映字幕助手 — 一键构建安装包

echo.
echo   ╔══════════════════════════════════════════════════════╗
echo   ║     剪映字幕助手 v1.7.0 — Windows 安装包构建       ║
echo   ║     Draft SRT Assistant Build Script               ║
echo   ╚══════════════════════════════════════════════════════╝
echo.

:: ====================================================================
:: Step 0 — Check Python (try multiple versions)
:: ====================================================================
echo [1/5] 检查 Python 环境...

set PYTHON_CMD=
for %%p in (python python3 py) do (
    where %%p >nul 2>&1
    if !errorlevel! equ 0 (
        %%p --version >nul 2>&1
        if !errorlevel! equ 0 set PYTHON_CMD=%%p
    )
)

if "%PYTHON_CMD%"=="" (
    echo   [错误] 未找到 Python，请先安装 Python 3.9+
    echo          https://www.python.org/downloads/
    echo          ^(安装时请勾选 "Add Python to PATH"^)
    pause
    exit /b 1
)

%PYTHON_CMD% --version
echo   ✓ Python 已就绪

:: ====================================================================
:: Step 1 — Install dependencies
:: ====================================================================
echo.
echo [2/5] 安装 Python 依赖...

%PYTHON_CMD% -m pip install --upgrade pip --quiet 2>&1
%PYTHON_CMD% -m pip install -r requirements.txt --quiet 2>&1
if !errorlevel! neq 0 (
    echo   [!] requirements.txt 安装失败，尝试直接安装 PyQt6...
    %PYTHON_CMD% -m pip install PyQt6>=6.5.0
    if !errorlevel! neq 0 (
        echo   [错误] PyQt6 安装失败，请检查网络连接
        pause
        exit /b 1
    )
)

:: Install PyInstaller
%PYTHON_CMD% -m pip install pyinstaller --quiet 2>&1
if !errorlevel! neq 0 (
    echo   [!] PyInstaller 安装失败，重试...
    %PYTHON_CMD% -m pip install pyinstaller
    if !errorlevel! neq 0 (
        echo   [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)
echo   ✓ 依赖安装完成

:: ====================================================================
:: Step 2 — PyInstaller build
:: ====================================================================
echo.
echo [3/5] PyInstaller 打包中 ^(约 3-8 分钟^)...

:: Clean previous builds
if exist dist\剪映字幕助手 rmdir /s /q dist\剪映字幕助手 2>nul
if exist build rmdir /s /q build 2>nul

%PYTHON_CMD% -m PyInstaller build_win.spec --clean --noconfirm
if !errorlevel! neq 0 (
    echo   [错误] PyInstaller 打包失败
    echo   请检查：1^) 磁盘空间是否充足  2^) 杀毒软件是否拦截
    pause
    exit /b 1
)
echo   ✓ PyInstaller 打包完成

:: ====================================================================
:: Step 3 — Detect Inno Setup
:: ====================================================================
echo.
echo [4/5] 查找 Inno Setup...

set ISCC_PATH=
:: Try PATH first
where iscc >nul 2>&1
if !errorlevel! equ 0 (
    for /f "delims=" %%i in ('where iscc 2^>nul') do set ISCC_PATH=%%i
)

:: Try standard install locations
if "%ISCC_PATH%"=="" (
    for %%d in (
        "C:\Program Files (x86)\Inno Setup 6"
        "C:\Program Files (x86)\Inno Setup 5"
        "C:\Program Files\Inno Setup 6"
        "C:\Program Files\Inno Setup 5"
    ) do (
        if exist %%d\ISCC.exe (
            set ISCC_PATH=%%d\ISCC.exe
        )
    )
)

:: Try registry
if "%ISCC_PATH%"=="" (
    reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1" /v "InstallLocation" >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2*" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1" /v "InstallLocation" 2^>nul ^| find "InstallLocation"') do (
            set ISCC_PATH=%%b\ISCC.exe
        )
    )
)

if "%ISCC_PATH%"=="" (
    echo   [!] 未找到 Inno Setup
    echo.
    echo   ┌─────────────────────────────────────────────────────┐
    echo   │  安装包需要 Inno Setup 才能生成                     │
    echo   │  下载地址：https://jrsoftware.org/isdl.php          │
    echo   │                                                     │
    echo   │  不需要安装包？PyInstaller 已生成的                  │
    echo   │  dist\剪映字幕助手\ 文件夹可以直接分发使用           │
    echo   └─────────────────────────────────────────────────────┘
    echo.
    goto :skip_inno
)

echo   ✓ 找到: %ISCC_PATH%

:: ====================================================================
:: Step 4 — Inno Setup installer
:: ====================================================================
echo.
echo [5/5] 生成安装包...

if not exist Output mkdir Output
"%ISCC_PATH%" installer.iss
if !errorlevel! neq 0 (
    echo   [错误] Inno Setup 打包失败
    pause
    exit /b 1
)
echo   ✓ 安装包生成完成
goto :done

:skip_inno
echo   ! 跳过安装包 ^(Inno Setup 未安装^)

:: ====================================================================
:: Done
:: ====================================================================
:done
echo.
echo   ╔══════════════════════════════════════════════════════╗
echo   ║                   构建完成！                         ║
echo   ╚══════════════════════════════════════════════════════╝
echo.

if exist "dist\剪映字幕助手\剪映字幕助手.exe" (
    for %%f in ("dist\剪映字幕助手\剪映字幕助手.exe") do (
        echo   便携版: dist\剪映字幕助手\  ^(%%~zf bytes^)
    )
)

if exist "Output\剪映字幕助手_Setup_*.exe" (
    echo.
    for %%f in (Output\剪映字幕助手_Setup_*.exe) do (
        echo   安装包: %%f  ^(%%~zf bytes^)
    )
)

echo.
echo   ┌─────────────────────────────────────────────────────┐
echo   │  安装包功能：                                        │
echo   │  · 支持 Windows 7 及以上系统                         │
echo   │  · 支持自定义安装目录                                │
echo   │  · 开始菜单快捷方式                                  │
echo   │  · 可选桌面快捷方式                                  │
echo   │  · 自带卸载程序                                      │
echo   └─────────────────────────────────────────────────────┘
echo.
echo   按任意键退出...
pause >nul
endlocal
