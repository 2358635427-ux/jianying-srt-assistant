#!/usr/bin/env bash
# ============================================================
#  剪映字幕助手 — 启动器
#  双击此文件即可启动程序
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "⚠️  尚未安装，请先双击运行 setup.sh 进行一键安装"
    read -p "按回车键退出..."
    exit 1
fi

source "$VENV_DIR/bin/activate"
cd "$SCRIPT_DIR"
python3 main.py
