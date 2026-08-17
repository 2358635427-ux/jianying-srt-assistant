#!/usr/bin/env bash
# ============================================================
#  剪映字幕助手 — macOS DMG 构建脚本
#  生成带「应用程序」快捷方式的安装包，用户打开后一步拖拽即可安装
#  用法: ./build_dmg.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="剪映字幕助手"
# 版本号从 setup.py 单一来源读取，避免多处硬编码
VERSION="$(grep -m1 '^VERSION' "$SCRIPT_DIR/setup.py" | sed -E 's/.*"([^"]+)".*/\1/')"
DIST_DIR="$SCRIPT_DIR/dist"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
STAGING="$SCRIPT_DIR/.dmg_staging"
TMP_DMG="$SCRIPT_DIR/.tmp_build.dmg"
APP_PATH="$DIST_DIR/$APP_NAME.app"

cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📦 $APP_NAME v$VERSION — DMG 构建"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ---- 1. 确保 .app 存在（否则先 py2app 打包） ----
if [ ! -d "$APP_PATH" ]; then
    echo "⏳ 未找到 .app，先运行 py2app 打包..."
    venv/bin/python setup.py py2app
fi

# ---- 2. 准备 staging 目录：.app + Applications 快捷方式 ----
echo "📦 准备 DMG 内容..."
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

# ---- 3. 先打成可读写 UDRW（用于写入引导布局） ----
echo "📀 生成 DMG..."
rm -f "$TMP_DMG" "$DMG_NAME"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" -ov -format UDRW "$TMP_DMG" >/dev/null

# ---- 4. 设置 Finder 引导布局（图标位置 + 窗口大小） ----
# 失败不影响 DMG 本身，仅少一层视觉引导
echo "🎨 设置安装引导布局..."
if MOUNT_POINT="$(hdiutil attach "$TMP_DMG" -nobrowse -readwrite 2>/dev/null | tail -1 | awk '{print $NF}')" && [ -n "$MOUNT_POINT" ]; then
    osascript >/dev/null 2>&1 <<APPLESCRIPT || true
tell application "Finder"
  tell disk "$APP_NAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {300, 100, 820, 480}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to 72
    set position of item "$APP_NAME.app" to {120, 190}
    set position of item "Applications" to {400, 190}
    close
    open
  end tell
end tell
APPLESCRIPT
    hdiutil detach "$MOUNT_POINT" >/dev/null 2>&1 || true
else
    echo "  ⚠️ 无法挂载设置布局（已直接生成 DMG，仍含 Applications 快捷方式）"
fi

# ---- 5. 转换为压缩只读 UDZO ----
hdiutil convert "$TMP_DMG" -format UDZO -o "$DMG_NAME" >/dev/null
rm -f "$TMP_DMG"

# ---- 6. 清理 ----
rm -rf "$STAGING"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ 完成: $DMG_NAME"
echo "  用户打开后：把「$APP_NAME.app」拖到「Applications」即可安装"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
