"""
PyQt6 main window — 剪映字幕助手 (Draft SRT Assistant)

Dark theme, card-based layout with optional custom wallpaper background.
- Card opacity auto-adjusts based on wallpaper brightness.
- Text lightness slider for manual foreground contrast control.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QClipboard, QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from srt_processor import (
    parse_srt,
    entries_to_srt,
    process_srt_entries,
    split_subtitle_text,
    redistribute_timestamps,
    _fix_overlaps,
    merge_short_entries,
    _is_primarily_cjk,
    SubtitleEntry,
)


SETTINGS_ORG = "DraftSRTAssistant"
SETTINGS_APP = "DraftSRTAssistant"
DEFAULT_CHINESE_LIMIT = 12
DEFAULT_ENGLISH_LIMIT = 21
DEFAULT_WALLPAPER_OPACITY = 30   # percent, 0–100
DEFAULT_CARD_ALPHA = 0.90        # card background opacity (0.0–1.0)
DEFAULT_TEXT_LIGHTNESS = 85      # 0=dark text, 100=light text


# ===================================================================
#  Color interpolation helpers
# ===================================================================

def _parse_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Parse '#rrggbb' or '#rrggbbaa' into (r, g, b)."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _lerp_color(light_hex: str, dark_hex: str, t: float) -> str:
    """Linearly interpolate between two hex colors.  t=1 → light, t=0 → dark."""
    lr, lg, lb = _parse_rgb(light_hex)
    dr, dg, db = _parse_rgb(dark_hex)
    r = int(dr + (lr - dr) * t)
    g = int(dg + (lg - dg) * t)
    b = int(db + (lb - db) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


# Light-text palette  (t=1, default for dark backgrounds)
LIGHT_TEXT = {
    "primary":   "#c8c4ba",
    "secondary": "#a09888",
    "dim":       "#8a8070",
    "bright":    "#e4e0d8",
    "button":    "#d4c8b0",
    "accent":    "#d4a040",
    "preview":   "#c8c4ba",
}

# Dark-text palette  (t=0, for bright wallpapers / high contrast)
DARK_TEXT = {
    "primary":   "#3a3a48",
    "secondary": "#4e4e5c",
    "dim":       "#5e5e6c",
    "bright":    "#2a2a36",
    "button":    "#444454",
    "accent":    "#b08020",
    "preview":   "#3e3e4c",
}


def _text_colors(t: float) -> dict:
    """Return interpolated text color dict for lightness t (0–1)."""
    return {
        k: _lerp_color(LIGHT_TEXT[k], DARK_TEXT[k], t)
        for k in LIGHT_TEXT
    }


# ===================================================================
#  WallpaperScrollArea  —  paints background image behind content
# ===================================================================

class WallpaperScrollArea(QScrollArea):
    """QScrollArea that renders an optional wallpaper image on its viewport."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._wallpaper: Optional[QPixmap] = None
        self._wallpaper_brightness: float = 128.0
        self._opacity_pct: int = DEFAULT_WALLPAPER_OPACITY

    def set_wallpaper(self, path: Optional[str]) -> None:
        if path:
            self._wallpaper = QPixmap(path)
            self._wallpaper_brightness = _analyze_image_brightness(self._wallpaper)
        else:
            self._wallpaper = None
            self._wallpaper_brightness = 128.0
        self.viewport().update()

    def set_wallpaper_opacity(self, pct: int) -> None:
        self._opacity_pct = max(5, min(100, pct))
        self.viewport().update()

    @property
    def wallpaper_brightness(self) -> float:
        return self._wallpaper_brightness

    @property
    def has_wallpaper(self) -> bool:
        return self._wallpaper is not None and not self._wallpaper.isNull()

    def paintEvent(self, event) -> None:
        if self._wallpaper and not self._wallpaper.isNull():
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            vp = self.viewport()
            vw, vh = vp.width(), vp.height()
            pw, ph = self._wallpaper.width(), self._wallpaper.height()

            if pw > 0 and ph > 0:
                scale = max(vw / pw, vh / ph)
                sw, sh = int(pw * scale), int(ph * scale)
                scaled = self._wallpaper.scaled(
                    sw, sh,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x, y = (vw - sw) // 2, (vh - sh) // 2

                alpha = self._opacity_pct / 100.0
                painter.setOpacity(alpha)
                painter.drawPixmap(x, y, scaled)

        super().paintEvent(event)


# ===================================================================
#  ClickableWatermark  —  outlined text, click to copy
# ===================================================================

class ClickableWatermark(QLabel):
    """A label with stroke-outlined black text that copies contact info on click."""

    def __init__(self, text: str = "", copy_text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._copy_text = copy_text or text
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击复制联系方式")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont(self.font())
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)

        # Draw white stroke outline: paint text at 8 offsets
        pen = QPen(QColor(220, 220, 230))
        pen.setWidthF(2.5)
        painter.setPen(pen)

        dx, dy = 1, 1
        for ox in (-dx, 0, dx):
            for oy in (-dy, 0, dy):
                if ox == 0 and oy == 0:
                    continue
                painter.drawText(
                    self.rect().translated(ox, oy),
                    int(self.alignment()),
                    self.text(),
                )

        # Draw black fill text on top
        pen = QPen(QColor(0, 0, 0))
        pen.setWidthF(0)
        painter.setPen(pen)
        painter.drawText(self.rect(), int(self.alignment()), self.text())

        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            clipboard = QApplication.instance().clipboard()
            clipboard.setText(self._copy_text)
            self.setToolTip("已复制: " + self._copy_text)
            # Reset tooltip after 2 seconds
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.setToolTip("点击复制联系方式"))
        super().mousePressEvent(event)


# ===================================================================
#  Brightness analysis
# ===================================================================

def _analyze_image_brightness(pixmap: QPixmap) -> float:
    """Return average perceived brightness of a pixmap (0–255).

    Uses ITU-R BT.709 luminance weights.  Samples at most ~2500 pixels.
    """
    if pixmap.isNull():
        return 128.0

    img = pixmap.toImage()
    w, h = img.width(), img.height()

    step = max(1, max(w, h) // 50)
    total = 0.0
    count = 0

    for y in range(0, h, step):
        for x in range(0, w, step):
            rgb = img.pixelColor(x, y)
            lum = 0.2126 * rgb.red() + 0.7152 * rgb.green() + 0.0722 * rgb.blue()
            total += lum
            count += 1

    return total / count if count > 0 else 128.0


def _brightness_to_card_alpha(brightness: float) -> float:
    """Map wallpaper brightness to recommended card background alpha."""
    if brightness < 50:       return 0.85
    elif brightness < 90:     return 0.88
    elif brightness < 130:    return 0.90
    elif brightness < 170:    return 0.93
    elif brightness < 210:    return 0.96
    else:                     return 0.98


def _brightness_to_text_lightness(brightness: float) -> int:
    """Map wallpaper brightness to recommended text lightness (0–100).

    Bright wallpaper → dark text; dark wallpaper → light text.
    """
    if brightness < 60:       return 85   # dark wallpaper — light text
    elif brightness < 100:    return 75
    elif brightness < 140:    return 55
    elif brightness < 180:    return 35
    elif brightness < 220:    return 20
    else:                     return 10   # very bright wallpaper — dark text


# ===================================================================
#  Dynamic stylesheet builder
# ===================================================================

def make_stylesheet(card_alpha: float = DEFAULT_CARD_ALPHA,
                    text_lightness: int = DEFAULT_TEXT_LIGHTNESS) -> str:
    """Build the full application stylesheet.

    Args:
        card_alpha: Opacity of card backgrounds (0.0–1.0).
        text_lightness: 0 = dark text, 100 = light text.
    """
    ca = max(0.75, min(1.0, card_alpha))
    ga = max(0.75, min(1.0, card_alpha + 0.02))
    t = max(0.0, min(1.0, text_lightness / 100.0))
    c = _text_colors(t)

    card_bg = f"rgba(30, 30, 42, {ca:.2f})"
    card_border = f"rgba(46, 46, 58, {ca:.2f})"
    guide_bg = f"rgba(26, 28, 38, {ga:.2f})"

    return f"""
QMainWindow {{
    background-color: #16161d;
}}
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}

/* ---- Group Box (Cards) ---- */
QGroupBox {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 16px 10px 16px;
    font-weight: 600;
    font-size: 12px;
    color: {c['secondary']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {c['dim']};
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}

QLabel {{
    color: {c['primary']};
    background: transparent;
}}

/* ---- Radio Buttons ---- */
QRadioButton {{
    color: {c['primary']};
    spacing: 6px;
    padding: 3px 0;
    font-size: 13px;
}}
QRadioButton::indicator {{
    width: 15px; height: 15px;
    border-radius: 8px;
    border: 2px solid #4a4550;
    background: #1e1e28;
}}
QRadioButton::indicator:checked {{
    border-color: {c['accent']};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.4,
        fx:0.5, fy:0.5, stop:0 {c['accent']}, stop:1 #1e1e28);
}}
QRadioButton::indicator:hover {{ border-color: {c['dim']}; }}

/* ---- Spin Boxes ---- */
QSpinBox {{
    background-color: rgba(34, 34, 46, 0.90);
    color: {c['bright']};
    border: 1px solid #3a3545;
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 13px;
    min-width: 64px;
}}
QSpinBox:focus {{ border-color: {c['accent']}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 16px; border: none; background: #2a2a38; border-radius: 2px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #3a3a4a; }}

/* ---- Buttons ---- */
QPushButton {{
    background-color: rgba(42, 42, 56, 0.90);
    color: {c['button']};
    border: 1px solid #3a3545;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
}}
QPushButton:hover {{ background-color: #353548; border-color: #5a5565; color: {c['bright']}; }}
QPushButton:pressed {{ background-color: #252535; }}

QPushButton#primaryBtn {{
    background-color: #c8782a;
    color: #faf6f0;
    border: none;
    font-weight: 600;
    font-size: 14px;
    padding: 9px 28px;
    border-radius: 7px;
}}
QPushButton#primaryBtn:hover {{ background-color: #d48830; }}
QPushButton#primaryBtn:pressed {{ background-color: #b06820; }}

QPushButton#exportBtn {{
    background-color: rgba(42, 58, 42, 0.90);
    border: 1px solid #3a5a3a;
    color: #a0d0a0;
}}
QPushButton#exportBtn:hover {{ background-color: #354a35; color: #c0e8c0; }}

QPushButton#fileBtn {{
    background-color: rgba(37, 37, 53, 0.90);
    border: 1px dashed #4a4550;
    color: {c['dim']};
    padding: 8px 20px;
}}
QPushButton#fileBtn:hover {{ border-color: {c['dim']}; color: {c['button']}; }}

/* wall paper control buttons  —  tiny */
QPushButton#wpBtn {{
    background: transparent;
    border: 1px solid #3a3545;
    border-radius: 9px;
    color: {c['dim']};
    padding: 1px 8px;
    font-size: 10px;
}}
QPushButton#wpBtn:hover {{ border-color: {c['dim']}; color: {c['button']}; }}

QPushButton#wpClearBtn {{
    background: transparent;
    border: none;
    color: #6a6470;
    padding: 1px 4px;
    font-size: 10px;
}}
QPushButton#wpClearBtn:hover {{ color: #cc6666; }}

/* ---- Sliders ---- */
QSlider::groove:horizontal {{
    background: #2a2a38;
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {c['dim']};
    width: 12px; height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {c['accent']}; }}
QSlider::sub-page:horizontal {{
    background: #c8782a;
    border-radius: 2px;
}}

/* ---- Text Edit / Preview ---- */
QTextEdit {{
    background-color: rgba(26, 26, 36, 0.90);
    color: {c['preview']};
    border: 1px solid #2e2e3a;
    border-radius: 6px;
    padding: 10px;
    font-family: "SF Mono", "Menlo", "Cascadia Code", "Courier New", monospace;
    font-size: 12px;
    selection-background-color: #4a3a20;
    selection-color: #f0ece4;
}}
QTextEdit:focus {{ border-color: #4a4550; }}

/* ---- Scrollbar ---- */
QScrollBar:vertical {{
    background: rgba(26, 26, 36, 0.80); width: 7px; margin: 0; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: #3a3545; min-height: 30px; border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{ background: #5a5565; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: rgba(26, 26, 36, 0.80); height: 7px; margin: 0; border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: #3a3545; min-width: 30px; border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{ background: #5a5565; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ---- Status Bar ---- */
QStatusBar {{
    background-color: rgba(26, 26, 36, 0.92);
    border-top: 1px solid #2e2e3a;
    color: {c['dim']};
    font-size: 11px;
    padding: 3px 10px;
}}

/* ---- Menu Bar ---- */
QMenuBar {{
    background-color: rgba(26, 26, 36, 0.92);
    border-bottom: 1px solid #2e2e3a;
    color: {c['secondary']};
    padding: 1px 0;
}}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; }}
QMenuBar::item:selected {{ background-color: #2a2a38; color: {c['bright']}; }}

QMenu {{
    background-color: rgba(30, 30, 40, 0.95);
    border: 1px solid #3a3545;
    border-radius: 7px;
    padding: 5px;
}}
QMenu::item {{ padding: 5px 24px 5px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: #2a2a38; color: #f0ece4; }}
QMenu::separator {{ height: 1px; background: #2e2e3a; margin: 3px 6px; }}

/* ---- Checkbox ---- */
QCheckBox {{
    color: {c['dim']};
    spacing: 6px;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border-radius: 3px;
    border: 2px solid #4a4550;
    background: #1e1e28;
}}
QCheckBox::indicator:checked {{ background: #c8782a; border-color: #c8782a; }}
QCheckBox::indicator:hover {{ border-color: {c['dim']}; }}

QToolTip {{
    background-color: #2a2a38;
    color: {c['bright']};
    border: 1px solid #3a3545;
    border-radius: 5px;
    padding: 5px 9px;
    font-size: 12px;
}}
"""


def make_guide_card_style(card_alpha: float = DEFAULT_CARD_ALPHA) -> str:
    """Build the guide card inline style snippet."""
    ga = max(0.75, min(1.0, card_alpha + 0.02))
    guide_bg = f"rgba(26, 28, 38, {ga:.2f})"
    return f"""
    QGroupBox {{
        background-color: {guide_bg};
        border: 1px solid #282832;
    }}
"""


# ===================================================================
#  MAIN WINDOW
# ===================================================================

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("剪映字幕助手 · Draft SRT Assistant")
        self.setMinimumSize(620, 500)
        self.resize(740, 660)

        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._selected_file: Optional[str] = None
        self._last_processed_srt: str = ""
        self._wallpaper_path: Optional[str] = None
        self._card_alpha: float = DEFAULT_CARD_ALPHA
        self._text_lightness: int = DEFAULT_TEXT_LIGHTNESS

        self._setup_ui()
        self._load_settings()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        content = QWidget()
        content.setStyleSheet("background-color: transparent;")

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(10)

        self._setup_menu_bar()

        layout.addLayout(self._make_header())
        layout.addWidget(self._make_mode_card())
        layout.addWidget(self._make_file_card())

        preview = self._make_preview_card()
        layout.addWidget(preview, 1)

        layout.addLayout(self._make_action_bar())
        layout.addWidget(self._make_guide_card())

        # Watermark — bottom-right, outlined black text, click to copy
        watermark = ClickableWatermark(
            text="小方 · My-seraphim",
            copy_text="My-seraphim",
        )
        watermark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        watermark.setStyleSheet(
            "background: transparent; padding: 2px 8px 4px 0;"
        )
        layout.addWidget(watermark)

        self._scroll = WallpaperScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(content)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "WallpaperScrollArea { background: transparent; border: none; }"
        )
        self.setCentralWidget(self._scroll)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("就绪 — 请上传 SRT 字幕文件开始处理")

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _setup_menu_bar(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("文件")
        file_menu.addAction(QAction("打开 SRT 文件...", self, triggered=self._on_open_srt))
        file_menu.addAction(QAction("导出处理结果...", self, triggered=self._on_save_srt))
        file_menu.addSeparator()
        file_menu.addAction(QAction("退出", self, triggered=self.close))

        help_menu = mb.addMenu("帮助")
        help_menu.addAction(QAction("关于本程序", self, triggered=self._on_about))

    # ------------------------------------------------------------------
    # Header  (title  +  text lightness  +  wp controls  +  version)
    # ------------------------------------------------------------------

    def _make_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 0)

        left = QVBoxLayout()
        left.setSpacing(1)
        title = QLabel("剪映字幕助手")
        title.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #f0ece4; background: transparent;"
        )
        sub = QLabel("Draft SRT Assistant  ·  字幕单行化重构工具")
        sub.setStyleSheet(
            "font-size: 11px; color: #6a6470; background: transparent; letter-spacing: 0.3px;"
        )
        left.addWidget(title)
        left.addWidget(sub)
        layout.addLayout(left)
        layout.addStretch()

        # --- Text lightness slider (always visible) ---
        lbl_text = QLabel("文字")
        lbl_text.setStyleSheet(
            "font-size: 10px; color: #6a6470; background: transparent; padding-right: 4px;"
        )
        layout.addWidget(lbl_text)

        self._text_slider = QSlider(Qt.Orientation.Horizontal)
        self._text_slider.setRange(5, 95)
        self._text_slider.setValue(DEFAULT_TEXT_LIGHTNESS)
        self._text_slider.setFixedWidth(72)
        self._text_slider.setToolTip("文字明暗 — 左=深色文字 右=浅色文字")
        self._text_slider.valueChanged.connect(self._on_text_lightness_changed)
        layout.addWidget(self._text_slider)

        self._lbl_brightness = QLabel("")
        self._lbl_brightness.setVisible(False)
        self._lbl_brightness.setToolTip("壁纸亮度感知 — 卡片自动调节对比度")
        layout.addWidget(self._lbl_brightness)

        # small spacer before wallpaper controls
        layout.addSpacing(8)

        # --- Wallpaper opacity slider ---
        self._wp_slider = QSlider(Qt.Orientation.Horizontal)
        self._wp_slider.setRange(5, 100)
        self._wp_slider.setValue(DEFAULT_WALLPAPER_OPACITY)
        self._wp_slider.setFixedWidth(80)
        self._wp_slider.setToolTip("壁纸透明度")
        self._wp_slider.valueChanged.connect(self._on_wp_opacity_changed)
        self._wp_slider.setVisible(False)
        layout.addWidget(self._wp_slider)

        # --- Wallpaper button ---
        self._wp_btn = QPushButton("▤ 壁纸")
        self._wp_btn.setObjectName("wpBtn")
        self._wp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wp_btn.setToolTip("设置背景壁纸")
        self._wp_btn.clicked.connect(self._on_choose_wallpaper)
        layout.addWidget(self._wp_btn)

        # --- Clear wallpaper button ---
        self._wp_clear_btn = QPushButton("✕")
        self._wp_clear_btn.setObjectName("wpClearBtn")
        self._wp_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wp_clear_btn.setToolTip("清除壁纸")
        self._wp_clear_btn.clicked.connect(self._on_clear_wallpaper)
        self._wp_clear_btn.setVisible(False)
        layout.addWidget(self._wp_clear_btn)

        # --- Version badge ---
        badge = QLabel("v1.4")
        badge.setStyleSheet(
            "font-size: 10px; color: #6a6470; background: rgba(30, 30, 40, 0.90); "
            "border: 1px solid #2e2e3a; border-radius: 9px; padding: 1px 9px;"
        )
        badge.setFixedHeight(20)
        layout.addWidget(badge)

        return layout

    # ------------------------------------------------------------------
    # Text lightness
    # ------------------------------------------------------------------

    def _on_text_lightness_changed(self, value: int) -> None:
        self._text_lightness = value
        self._apply_full_stylesheet()

    # ------------------------------------------------------------------
    # Wallpaper + contrast auto-adjust
    # ------------------------------------------------------------------

    def _on_choose_wallpaper(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景壁纸", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)",
        )
        if not path:
            return

        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.critical(self, "错误", "无法加载图片，请检查文件格式。")
            return

        self._wallpaper_path = path
        self._scroll.set_wallpaper(path)
        self._scroll.set_wallpaper_opacity(self._wp_slider.value())

        brightness = self._scroll.wallpaper_brightness
        self._apply_card_contrast(brightness)

        self._wp_slider.setVisible(True)
        self._wp_clear_btn.setVisible(True)
        self._wp_btn.setText("▤ 换壁纸")

        self._save_wp_settings()
        self._status_bar.showMessage(
            f"壁纸已设置 — 亮度 {brightness:.0f}/255，卡片与文字对比度已自动调节"
        )

    def _on_clear_wallpaper(self) -> None:
        self._wallpaper_path = None
        self._scroll.set_wallpaper(None)

        self._wp_slider.setVisible(False)
        self._wp_clear_btn.setVisible(False)
        self._wp_btn.setText("▤ 壁纸")

        self._apply_card_contrast(128.0)

        self._save_wp_settings()
        self._status_bar.showMessage("壁纸已清除，恢复默认对比度")

    def _on_wp_opacity_changed(self, value: int) -> None:
        self._scroll.set_wallpaper_opacity(value)
        self._save_wp_settings()

    def _apply_card_contrast(self, brightness: float) -> None:
        """Adjust card opacity and suggest text lightness based on wallpaper brightness."""
        self._card_alpha = _brightness_to_card_alpha(brightness)

        # Auto-set text lightness based on brightness
        suggested = _brightness_to_text_lightness(brightness)
        self._text_slider.setValue(suggested)
        self._text_lightness = suggested

        self._apply_full_stylesheet()
        self._update_brightness_badge(brightness)

    def _apply_full_stylesheet(self) -> None:
        """Rebuild and apply the application stylesheet with current settings."""
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.setStyleSheet(make_stylesheet(self._card_alpha, self._text_lightness))
        self._scroll.setStyleSheet(
            "WallpaperScrollArea { background: transparent; border: none; }"
        )

        # Update guide card inline style
        guide = self.findChild(QGroupBox, "guideCard")
        if guide:
            ga = max(0.75, min(1.0, self._card_alpha + 0.02))
            guide_bg = f"rgba(26, 28, 38, {ga:.2f})"
            guide.setStyleSheet(
                f"QGroupBox {{ background-color: {guide_bg}; border: 1px solid #282832; }}"
            )

    def _update_brightness_badge(self, brightness: float) -> None:
        """Show a small badge indicating wallpaper brightness and contrast level."""
        has_wp = self._scroll.has_wallpaper
        self._lbl_brightness.setVisible(has_wp)

        if not has_wp:
            return

        if brightness < 50:
            label, color = "暗色壁纸", "#5a8a6a"
        elif brightness < 90:
            label, color = "偏暗", "#7a9a6a"
        elif brightness < 130:
            label, color = "适中", "#8a8070"
        elif brightness < 170:
            label, color = "偏亮", "#c89840"
        elif brightness < 210:
            label, color = "亮色壁纸", "#d48830"
        else:
            label, color = "高亮壁纸", "#d47040"

        self._lbl_brightness.setText(label)
        self._lbl_brightness.setStyleSheet(
            f"font-size: 9px; color: {color}; "
            "background: rgba(30, 30, 40, 0.80); "
            "border: 1px solid #2e2e3a; border-radius: 7px; "
            "padding: 1px 7px;"
        )

    def _save_wp_settings(self) -> None:
        self._settings.setValue("wallpaper_path", self._wallpaper_path or "")
        self._settings.setValue("wallpaper_opacity", self._wp_slider.value())
        self._settings.setValue("text_lightness", self._text_lightness)

    def _restore_wallpaper(self) -> None:
        path = self._settings.value("wallpaper_path", "")
        opacity = int(self._settings.value("wallpaper_opacity", DEFAULT_WALLPAPER_OPACITY))

        if path and Path(str(path)).exists():
            self._wallpaper_path = str(path)
            self._scroll.set_wallpaper(str(path))
            self._scroll.set_wallpaper_opacity(opacity)
            self._wp_slider.setValue(opacity)
            self._wp_slider.setVisible(True)
            self._wp_clear_btn.setVisible(True)
            self._wp_btn.setText("▤ 换壁纸")

            self._apply_card_contrast(self._scroll.wallpaper_brightness)

    # ------------------------------------------------------------------
    # Mode card
    # ------------------------------------------------------------------

    def _make_mode_card(self) -> QGroupBox:
        card = QGroupBox("处理模式")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        radio_row = QHBoxLayout()
        self._mode_general = QRadioButton("通用模式（中/英文自动识别）")
        self._mode_general.setChecked(True)
        self._mode_general.toggled.connect(self._on_mode_changed)
        radio_row.addWidget(self._mode_general)

        self._mode_en = QRadioButton("纯英文模式")
        self._mode_en.toggled.connect(self._on_mode_changed)
        radio_row.addWidget(self._mode_en)

        self._chk_capitalize = QCheckBox("首字母大写")
        self._chk_capitalize.setChecked(True)
        self._chk_capitalize.setToolTip("自动将每条字幕的首字母大写")
        radio_row.addWidget(self._chk_capitalize)
        radio_row.addStretch()
        layout.addLayout(radio_row)

        limits_row = QHBoxLayout()
        limits_row.setSpacing(16)

        cn = QHBoxLayout()
        cn.setSpacing(6)
        cn.addWidget(QLabel("中文上限"))
        self._spin_chinese = QSpinBox()
        self._spin_chinese.setRange(4, 100)
        self._spin_chinese.setValue(DEFAULT_CHINESE_LIMIT)
        self._spin_chinese.setSuffix(" 字")
        self._spin_chinese.setToolTip("中文每行最大字符数")
        cn.addWidget(self._spin_chinese)
        limits_row.addLayout(cn)

        en = QHBoxLayout()
        en.setSpacing(6)
        en.addWidget(QLabel("英文上限"))
        self._spin_english = QSpinBox()
        self._spin_english.setRange(4, 150)
        self._spin_english.setValue(DEFAULT_ENGLISH_LIMIT)
        self._spin_english.setSuffix(" chars")
        self._spin_english.setToolTip("英文每行最大字符数")
        en.addWidget(self._spin_english)
        limits_row.addLayout(en)

        limits_row.addStretch()
        layout.addLayout(limits_row)

        card.setLayout(layout)
        return card

    # ------------------------------------------------------------------
    # File card
    # ------------------------------------------------------------------

    def _make_file_card(self) -> QGroupBox:
        card = QGroupBox("字幕文件")
        layout = QHBoxLayout()
        layout.setSpacing(10)

        self._btn_upload = QPushButton("选择 SRT 文件")
        self._btn_upload.setObjectName("fileBtn")
        self._btn_upload.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_upload.clicked.connect(self._on_open_srt)
        layout.addWidget(self._btn_upload)

        self._lbl_file = QLabel("未选择文件")
        self._lbl_file.setStyleSheet(
            "color: #5a5565; font-style: italic; background: transparent;"
        )
        self._lbl_file.setWordWrap(True)
        self._lbl_file.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._lbl_file, 1)

        card.setLayout(layout)
        return card

    # ------------------------------------------------------------------
    # Preview card  (stretch=1 in parent layout)
    # ------------------------------------------------------------------

    def _make_preview_card(self) -> QGroupBox:
        card = QGroupBox("字幕预览")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self._preview_text = QTextEdit()
        self._preview_text.setReadOnly(True)
        self._preview_text.setMinimumHeight(120)
        self._preview_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_text.setPlaceholderText(
            "上传 SRT 文件后，此处显示字幕预览..."
        )
        layout.addWidget(self._preview_text)

        card.setLayout(layout)
        return card

    # ------------------------------------------------------------------
    # Action bar
    # ------------------------------------------------------------------

    def _make_action_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(2, 2, 2, 0)

        self._chk_merge = QCheckBox("合并相邻短句，减少断句感")
        self._chk_merge.setChecked(True)
        self._chk_merge.setToolTip("相邻短字幕合并后不超过字数限制时自动合并")
        layout.addWidget(self._chk_merge)
        layout.addStretch()

        self._btn_process = QPushButton("开始处理")
        self._btn_process.setObjectName("primaryBtn")
        self._btn_process.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_process.clicked.connect(self._on_execute)
        layout.addWidget(self._btn_process)

        self._btn_export = QPushButton("导出 SRT")
        self._btn_export.setObjectName("exportBtn")
        self._btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_export.clicked.connect(self._on_save_srt)
        layout.addWidget(self._btn_export)

        return layout

    # ------------------------------------------------------------------
    # Usage guide  —  compact two-column
    # ------------------------------------------------------------------

    def _make_guide_card(self) -> QGroupBox:
        card = QGroupBox("使用指南")
        card.setObjectName("guideCard")
        card.setStyleSheet(card.styleSheet() + make_guide_card_style(self._card_alpha))

        layout = QVBoxLayout()
        layout.setSpacing(2)

        steps = [
            ("1", "剪映导出 SRT", "菜单「导出」→ 选择 SRT 格式"),
            ("2", "上传文件", "点击上方按钮选择 .srt 文件"),
            ("3", "设定参数", "选择模式，调整字数上限"),
            ("4", "开始处理", "查看预览，确认后导出"),
        ]

        for row_idx in range(0, len(steps), 2):
            row = QHBoxLayout()
            row.setSpacing(24)
            for i in range(row_idx, min(row_idx + 2, len(steps))):
                num, title, desc = steps[i]
                cell = QHBoxLayout()
                cell.setSpacing(8)
                cell.setContentsMargins(0, 2, 0, 2)

                badge = QLabel(num)
                badge.setFixedSize(20, 20)
                badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                badge.setStyleSheet(
                    "font-size: 10px; font-weight: 700; color: #d4a040; "
                    "background: #252535; border-radius: 10px; "
                    "border: 1px solid #3a3030;"
                )
                cell.addWidget(badge)

                text = QLabel(
                    f"<span style='color:#b0a890; font-weight:600'>{title}</span>"
                    f"<span style='color:#6a6470'> — {desc}</span>"
                )
                text.setWordWrap(True)
                text.setTextFormat(Qt.TextFormat.RichText)
                cell.addWidget(text, 1)
                row.addLayout(cell, 1)

            layout.addLayout(row)

        card.setLayout(layout)
        return card

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _on_mode_changed(self) -> None:
        is_en = self._mode_en.isChecked()
        self._spin_chinese.setEnabled(not is_en)
        self._chk_capitalize.setEnabled(is_en)
        msg = (
            "纯英文模式：所有字幕按英文限制处理"
            if is_en else
            "通用模式：自动识别中/英文，分别应用字数限制"
        )
        self._status_bar.showMessage(msg)

    # ------------------------------------------------------------------
    # File open / save
    # ------------------------------------------------------------------

    def _on_open_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开字幕文件", "",
            "字幕文件 (*.srt *.txt);;所有文件 (*)",
        )
        if not path:
            return

        try:
            raw = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                raw = Path(path).read_text(encoding="gbk")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法读取文件：\n{e}")
                return

        try:
            entries = parse_srt(raw)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"解析 SRT 文件失败：\n{e}")
            return

        if not entries:
            QMessageBox.warning(self, "提示", "文件中未找到有效字幕条目。")
            return

        self._selected_file = path
        self._last_processed_srt = raw
        self._lbl_file.setText(os.path.basename(path))
        self._lbl_file.setStyleSheet(
            "color: #a0d0a0; background: transparent; font-style: normal;"
        )
        self._preview_text.setPlainText(self._make_preview(entries, "原始"))
        self._status_bar.showMessage(
            f"已加载: {os.path.basename(path)}  —  {len(entries)} 条字幕"
        )

    def _on_save_srt(self) -> None:
        if not self._last_processed_srt:
            QMessageBox.warning(self, "提示", "没有可保存的内容。请先上传并处理。")
            return

        default_name = "processed.srt"
        if self._selected_file:
            base = os.path.splitext(os.path.basename(self._selected_file))[0]
            default_name = f"{base}_processed.srt"

        path, _ = QFileDialog.getSaveFileName(
            self, "导出处理后的字幕", default_name,
            "字幕文件 (*.srt);;所有文件 (*)",
        )
        if not path:
            return

        try:
            Path(path).write_text(self._last_processed_srt, encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败：\n{e}")
            return

        self._status_bar.showMessage(f"已导出: {os.path.basename(path)}")
        QMessageBox.information(self, "导出完成", f"字幕已保存到：\n{path}")

    # ------------------------------------------------------------------
    # Execute processing
    # ------------------------------------------------------------------

    def _on_execute(self) -> None:
        if not self._last_processed_srt:
            QMessageBox.warning(self, "提示", "请先上传字幕文件。")
            return

        is_en = self._mode_en.isChecked()
        ch_limit = self._spin_chinese.value()
        en_limit = self._spin_english.value()
        do_merge = self._chk_merge.isChecked()

        entries = parse_srt(self._last_processed_srt)
        if not entries:
            QMessageBox.warning(self, "提示", "没有可处理的字幕。")
            return

        try:
            if is_en:
                processed = process_srt_entries(
                    entries, max_chars=en_limit, mode="en_only", merge=do_merge,
                    capitalize=self._chk_capitalize.isChecked(),
                )
            else:
                processed = self._process_with_per_entry_limits(
                    entries, ch_limit, en_limit, do_merge,
                )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"处理失败：\n{e}")
            return

        result_srt = entries_to_srt(processed)
        self._last_processed_srt = result_srt
        self._preview_text.setPlainText(self._make_preview(processed, "处理后"))
        self._status_bar.showMessage(
            f"处理完成: {len(entries)} 条 → {len(processed)} 条  —  可点击「导出 SRT」保存"
        )

        QMessageBox.information(
            self, "处理完成",
            f"处理完成！\n\n"
            f"原始: {len(entries)} 条字幕\n"
            f"处理后: {len(processed)} 条字幕\n\n"
            f"点击「导出 SRT」保存结果。",
        )

    def _process_with_per_entry_limits(
        self, entries: list, ch_limit: int, en_limit: int, merge: bool,
    ) -> list:
        result: list = []
        for entry in entries:
            limit = ch_limit if _is_primarily_cjk(entry.text) else en_limit
            pieces = split_subtitle_text(entry.text, limit)

            if len(pieces) == 1 and pieces[0] == entry.text:
                result.append(SubtitleEntry(
                    index=0, start_ms=entry.start_ms, end_ms=entry.end_ms,
                    text=pieces[0],
                ))
            else:
                last_end = result[-1].end_ms + 30 if result else None
                result.extend(redistribute_timestamps(entry, pieces, last_end))

        result = _fix_overlaps(result)
        if merge:
            result = merge_short_entries(result, max(ch_limit, en_limit))
        for i, e in enumerate(result, 1):
            e.index = i
        return result

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _load_settings(self) -> None:
        if self._settings.value("mode", "general") == "en_only":
            self._mode_en.setChecked(True)

        self._spin_chinese.setValue(
            int(self._settings.value("chinese_limit", DEFAULT_CHINESE_LIMIT))
        )
        self._spin_english.setValue(
            int(self._settings.value("english_limit", DEFAULT_ENGLISH_LIMIT))
        )
        self._chk_merge.setChecked(
            bool(self._settings.value("merge_short", True))
        )
        self._chk_capitalize.setChecked(
            bool(self._settings.value("capitalize", True))
        )

        # Restore text lightness (or default)
        saved_text = int(self._settings.value("text_lightness", DEFAULT_TEXT_LIGHTNESS))
        self._text_slider.setValue(saved_text)
        self._text_lightness = saved_text

        # Restore wallpaper (which triggers contrast auto-adjust)
        self._restore_wallpaper()

        # Apply initial stylesheet with saved text lightness
        self._apply_full_stylesheet()

    def _save_settings(self) -> None:
        self._settings.setValue(
            "mode", "en_only" if self._mode_en.isChecked() else "general"
        )
        self._settings.setValue("chinese_limit", self._spin_chinese.value())
        self._settings.setValue("english_limit", self._spin_english.value())
        self._settings.setValue("merge_short", self._chk_merge.isChecked())
        self._settings.setValue("capitalize", self._chk_capitalize.isChecked())
        self._settings.setValue("text_lightness", self._text_lightness)
        self._save_wp_settings()

    def closeEvent(self, event) -> None:
        self._save_settings()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # About
    # ------------------------------------------------------------------

    def _on_about(self) -> None:
        import platform as _platform
        QMessageBox.about(
            self, "关于 剪映字幕助手",
            "<h3 style='color:#d4a040'>剪映字幕助手</h3>"
            "<p style='color:#c8c0b0'>Draft SRT Assistant v1.4</p>"
            "<p style='color:#8a8070'>"
            "专门针对剪映的字幕后处理工具。<br>"
            "支持单行字幕字数限制（中/英文可配置），<br>"
            "智能切分与时间轴重新分配。</p>"
            "<p style='color:#6a6470; font-size:11px'>"
            "壁纸亮度感知 + 文字明暗可调 — 卡片与文字对比度自动/手动调节</p>"
            "<p style='color:#8a8070; font-size:11px'>"
            "软件开发者：小方</p>"
            f"<p style='color:#6a6470; font-size:11px'>"
            f"运行环境: {_platform.system()} {_platform.release()}</p>",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_preview(self, entries: list, label: str = "") -> str:
        lines: list[str] = []
        if label:
            lines.append(f"══ {label} ({len(entries)} 条) ══\n")
        max_show = min(len(entries), 40)
        for e in entries[:max_show]:
            text_display = e.text.replace("\n", " ↵ ")
            lines.append(
                f"[{e.start_str} → {e.end_str}] ({len(e.text)}字)  {text_display}"
            )
        if len(entries) > max_show:
            lines.append(f"\n... 共 {len(entries)} 条，仅显示前 {max_show} 条")
        return "\n".join(lines)
