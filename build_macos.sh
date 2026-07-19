#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$SCRIPT_DIRECTORY"
readonly SCRIPT_DIRECTORY

readonly PYTHON_BIN=python3
readonly DEPENDENCY_CONSTRAINT=constraints/requirements-macos-py312.txt
readonly DEPENDENCY_VERIFIER=scripts/verify_dependency_environment.py
export PIP_CONFIG_FILE=/dev/null
readonly -a REPOSITORY_SENTINELS=(
  build_macos.sh
  main.py
  requirements.txt
  "$DEPENDENCY_CONSTRAINT"
  "$DEPENDENCY_VERIFIER"
)

for repository_sentinel in "${REPOSITORY_SENTINELS[@]}"; do
  if [[ ! -f "$repository_sentinel" || -L "$repository_sentinel" ]]; then
    echo "Refusing to build outside the physical GM2Godot repository root: missing regular file $repository_sentinel."
    exit 1
  fi
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS."
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "CPython 3.12.10 for macOS arm64 is required, but python3 was not found."
  exit 1
fi

if ! "$PYTHON_BIN" - <<'PY'
import platform
import sys

expected = ("CPython", "3.12.10", "darwin", "Darwin", "arm64")
observed = (
    platform.python_implementation(),
    platform.python_version(),
    sys.platform,
    platform.system(),
    platform.machine(),
)
if observed != expected:
    print(
        "Unsupported Python/host tuple. "
        f"Expected {expected!r}; observed {observed!r}.",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
then
  echo "Install CPython 3.12.10 for macOS arm64 and make it available as python3."
  exit 1
fi

BUILD_TEMP_PARENT="$(cd -- "${TMPDIR:-/tmp}" && pwd -P)"
BUILD_TEMP_ROOT=""

cleanup_build_temp() {
  if [[ -z "$BUILD_TEMP_ROOT" ]]; then
    return 0
  fi
  if [[ "$BUILD_TEMP_ROOT" != "$BUILD_TEMP_PARENT"/gm2godot-build-* ]]; then
    echo "Refusing to clean unexpected temporary build path: $BUILD_TEMP_ROOT" >&2
    return 1
  fi
  if [[ -e "$BUILD_TEMP_ROOT" ]] && ! rm -rf -- "$BUILD_TEMP_ROOT"; then
    echo "Could not remove temporary build environment: $BUILD_TEMP_ROOT" >&2
    return 1
  fi
  if [[ -e "$BUILD_TEMP_ROOT" ]]; then
    echo "Temporary build environment still exists after cleanup: $BUILD_TEMP_ROOT" >&2
    return 1
  fi
  BUILD_TEMP_ROOT=""
}

cleanup_on_exit() {
  local exit_code=$?
  trap - EXIT
  if ! cleanup_build_temp; then
    exit_code=1
  fi
  exit "$exit_code"
}

trap cleanup_on_exit EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

BUILD_TEMP_ROOT="$(mktemp -d "${BUILD_TEMP_PARENT}/gm2godot-build-XXXXXX")"
readonly BUILD_VENV="${BUILD_TEMP_ROOT}/venv"
readonly BUILD_RECEIPT="${BUILD_TEMP_ROOT}/dependency-environment-macos.json"
readonly VENV_PYTHON="${BUILD_VENV}/bin/python"

echo "Creating isolated build environment..."
"$PYTHON_BIN" -m venv "$BUILD_VENV"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "The isolated build environment did not create an executable Python interpreter."
  exit 1
fi

echo "Installing dependencies..."
"$VENV_PYTHON" -m pip --isolated --disable-pip-version-check --no-input install --no-cache-dir --only-binary=:all: \
  --constraint "$DEPENDENCY_CONSTRAINT" \
  pip==26.1.2
"$VENV_PYTHON" -m pip --isolated --disable-pip-version-check --no-input install --no-cache-dir --only-binary=:all: \
  --constraint "$DEPENDENCY_CONSTRAINT" \
  -r requirements.txt PyInstaller==6.21.0

echo "Verifying dependency environment..."
"$VENV_PYTHON" "$DEPENDENCY_VERIFIER" \
  --constraint "$DEPENDENCY_CONSTRAINT" \
  --mode subset \
  --require pip \
  --require Pillow \
  --require markdown2 \
  --require requests \
  --require PySide6 \
  --require PyInstaller \
  --expected-python 3.12.10 \
  --expected-platform darwin \
  --expected-machine arm64 \
  --expected-pip 26.1.2 \
  --output "$BUILD_RECEIPT"

echo "Cleaning old build artifacts..."
rm -rf -- build dist release dmg
rm -f -- GM2Godot-macos.zip GM2Godot-macos.dmg GM2Godot.spec

echo "Building macOS app bundle..."
"$VENV_PYTHON" -m PyInstaller --onedir \
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

cleanup_build_temp

echo "Build complete."
echo "App bundle: dist/GM2Godot.app"
echo "Zip: GM2Godot-macos.zip"
echo "DMG: GM2Godot-macos.dmg"
