"""
py2app build configuration for 剪映字幕助手 (Draft SRT Assistant).
Run:  python setup.py py2app
"""
import sys
from pathlib import Path
from setuptools import setup

APP_NAME = "剪映字幕助手"
BUNDLE_ID = "com.draft-srt-assistant.app"
VERSION = "1.3.0"

PROJECT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
# Ensure our modules are importable
sys.path.insert(0, str(PROJECT_DIR))

OPTIONS = {
    "py2app": {
        # Don't include a console window in the bundle — this is a GUI app
        "argv_emulation": False,
        # Bundle everything into the .app (not symlinked)
        "site_packages": True,
        # Strip debug symbols for smaller size
        "strip": True,
        # Packages that py2app must include
        "packages": [
            "PyQt6",
            "srt_processor",
            "draft_manager",
            "ui_main",
        ],
        # Additional files/directories to include in the bundle Resources
        "resources": [],
        # Exclude large unused PyQt6 parts to reduce bundle size
        "excludes": [
            "PyQt6.QtBluetooth",
            "PyQt6.QtDBus",
            "PyQt6.QtDesigner",
            "PyQt6.QtHelp",
            "PyQt6.QtMultimedia",
            "PyQt6.QtMultimediaWidgets",
            "PyQt6.QtNetwork",
            "PyQt6.QtNfc",
            "PyQt6.QtOpenGL",
            "PyQt6.QtOpenGLWidgets",
            "PyQt6.QtPdf",
            "PyQt6.QtPdfWidgets",
            "PyQt6.QtPositioning",
            "PyQt6.QtPrintSupport",
            "PyQt6.QtQml",
            "PyQt6.QtQuick",
            "PyQt6.QtQuick3D",
            "PyQt6.QtQuickWidgets",
            "PyQt6.QtRemoteObjects",
            "PyQt6.QtSensors",
            "PyQt6.QtSerialPort",
            "PyQt6.QtSql",
            "PyQt6.QtSvg",
            "PyQt6.QtSvgWidgets",
            "PyQt6.QtTest",
            "PyQt6.QtTextToSpeech",
            "PyQt6.QtWebChannel",
            "PyQt6.QtWebEngine",
            "PyQt6.QtWebEngineCore",
            "PyQt6.QtWebEngineQuick",
            "PyQt6.QtWebEngineWidgets",
            "PyQt6.QtWebSockets",
            "PyQt6.QtXml",
        ],
        # Frameworks to include
        "frameworks": [],
        # Plist entries
        "plist": {
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleVersion": VERSION,
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSMinimumSystemVersion": "11.0",
            "LSMultipleInstancesProhibited": True,
        },
    },
}

setup(
    name=APP_NAME,
    version=VERSION,
    app=["main.py"],
    options=OPTIONS,
    setup_requires=["py2app"],
)
