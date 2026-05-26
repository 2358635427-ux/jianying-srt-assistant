#!/usr/bin/env bash
# ============================================================
#  剪映字幕助手 — 一键安装脚本
#  使用方法：双击或在终端运行 ./setup.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="剪映字幕助手"
VENV_DIR="$SCRIPT_DIR/venv"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📦 $APP_NAME — 一键安装"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ---- 检查 Python3 ----
if ! command -v python3 &>/dev/null; then
    echo "❌ 未检测到 python3，请先安装 Python 3.10+"
    echo "   macOS: brew install python3"
    echo "   官网: https://www.python.org/downloads/"
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python $PY_VER 已就绪"

# ---- 创建虚拟环境 ----
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "⏳ 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    echo "✅ 虚拟环境创建完成"
else
    echo "✅ 虚拟环境已存在，跳过创建"
fi

# ---- 激活并安装依赖 ----
echo ""
echo "⏳ 安装依赖 (PyQt6)..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
deactivate

# ---- 创建启动器 (macOS .command 文件) ----
LAUNCHER="$SCRIPT_DIR/启动剪映字幕助手.command"
if [ ! -f "$LAUNCHER" ]; then
    cat > "$LAUNCHER" << 'LAUNCHEREOF'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "⚠️  虚拟环境不存在，请先运行 setup.sh 进行安装"
    read -p "按回车键退出..."
    exit 1
fi

source "$VENV_DIR/bin/activate"
cd "$SCRIPT_DIR"
python3 main.py
deactivate
LAUNCHEREOF
    chmod +x "$LAUNCHER"
    echo "✅ 已创建启动器: 启动剪映字幕助手.command"
fi

# ---- 完成 ----
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 安装完成！"
echo ""
echo "  启动方式："
echo "    • 双击 Finder 中的 「启动剪映字幕助手.command」"
echo "    • 或在终端运行:"
echo "      cd "$SCRIPT_DIR" && source venv/bin/activate && python3 main.py"
echo ""
echo "  下次重新安装请再次运行本脚本。"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 如果是 macOS，询问是否打开
if [[ "$(uname)" == "Darwin" ]]; then
    echo ""
    read -p "是否立即启动程序？(Y/n): " answer
    if [[ "$answer" != "n" && "$answer" != "N" ]]; then
        open "$LAUNCHER"
    fi
fi
