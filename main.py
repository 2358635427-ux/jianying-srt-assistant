#!/usr/bin/env python3
"""
剪映字幕助手 — Draft SRT Assistant
==================================

剪映（JianYing）字幕单行化重构工具。
上传 SRT 字幕文件，自动切分/合并以控制单行字数，导出新 SRT。

启动方式:
    python main.py

依赖:
    PyQt6
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the package directory is on sys.path so sibling imports work.
_pkg_dir = Path(__file__).resolve().parent
if str(_pkg_dir) not in sys.path:
    sys.path.insert(0, str(_pkg_dir))


def main() -> None:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont

    app = QApplication(sys.argv)
    app.setApplicationName("DraftSRTAssistant")
    app.setOrganizationName("DraftSRTAssistant")

    # Use a reasonable default font
    font = QFont()
    if sys.platform == "darwin":
        font.setFamily("PingFang SC")
        font.setPointSize(13)
    elif sys.platform == "win32":
        font.setFamily("Microsoft YaHei UI")
        font.setPointSize(10)
    else:
        font.setPointSize(11)
    app.setFont(font)

    from ui_main import MainWindow, make_stylesheet
    app.setStyleSheet(make_stylesheet())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
