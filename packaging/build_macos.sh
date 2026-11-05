#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PYINSTALLER="${ROOT}/.venv/bin/pyinstaller"
APP_NAME="羽栖 BirdRoost"
if [ ! -x "$PYINSTALLER" ]; then
  echo "缺少 PyInstaller：请先运行 .venv/bin/pip install 'pyinstaller>=6,<7'"
  exit 1
fi
rm -rf build "dist/${APP_NAME}.app" "dist/${APP_NAME}.dmg" "dist/${APP_NAME}-macOS-arm64.zip"
"$PYINSTALLER" \
  --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --icon packaging/AppIcon.icns \
  --osx-bundle-identifier com.birdclass.birdroost \
  --paths src \
  --collect-data birdclass \
  --collect-data pypinyin \
  --collect-submodules qcloud_cos \
  --exclude-module tkinter \
  packaging/launcher.py
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 0.2.5" "dist/${APP_NAME}.app/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 0.2.5" "dist/${APP_NAME}.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion 1" "dist/${APP_NAME}.app/Contents/Info.plist" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 1" "dist/${APP_NAME}.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName ${APP_NAME}" "dist/${APP_NAME}.app/Contents/Info.plist" 2>/dev/null || true
codesign --force --deep --sign - --timestamp=none "dist/${APP_NAME}.app"
ditto -c -k --sequesterRsrc --keepParent "dist/${APP_NAME}.app" "dist/${APP_NAME}-macOS-arm64.zip"
DMG_STAGE="build/dmg-stage"
rm -rf "$DMG_STAGE"
mkdir -p "$DMG_STAGE"
ditto "dist/${APP_NAME}.app" "$DMG_STAGE/${APP_NAME}.app"
ln -s /Applications "$DMG_STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_STAGE" -ov -format UDZO "dist/${APP_NAME}.dmg"
echo "Built: dist/${APP_NAME}.app"
echo "Built: dist/${APP_NAME}.dmg"
echo "Built: dist/${APP_NAME}-macOS-arm64.zip"
