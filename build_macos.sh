#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS."
  exit 1
fi

echo "Cleaning old build artifacts..."
rm -rf build dist release dmg
rm -f GM2Godot-macos.zip GM2Godot-macos.dmg GM2Godot.spec

echo "Installing dependencies..."
python3 -m pip install -r requirements.txt pyinstaller

echo "Building macOS app bundle..."
pyinstaller --onedir \
  --windowed \
  --clean \
  --name GM2Godot \
  --icon img/Logo.png \
  --hidden-import markdown2 \
  --hidden-import PIL \
  --hidden-import PySide6.QtWidgets \
  --hidden-import PySide6.QtCore \
  --hidden-import PySide6.QtGui \
  --add-data "img:img" \
  --add-data "src:src" \
  --add-data "Languages:Languages" \
  --add-data "Current Language:." \
  main.py

echo "Preparing release directory..."
mkdir -p release
cp -R dist/GM2Godot.app release/
cp README.md release/

echo "Creating zip archive..."
(
  cd release
  ditto -c -k --sequesterRsrc --keepParent GM2Godot.app ../GM2Godot-macos.zip
)

echo "Creating DMG image..."
mkdir -p dmg
cp -R release/GM2Godot.app dmg/
ln -s /Applications dmg/Applications
hdiutil create \
  -volname "GM2Godot" \
  -srcfolder dmg \
  -ov \
  -format UDZO \
  GM2Godot-macos.dmg

echo "Build complete."
echo "App bundle: dist/GM2Godot.app"
echo "Zip: GM2Godot-macos.zip"
echo "DMG: GM2Godot-macos.dmg"
