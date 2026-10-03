#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$SCRIPT_DIRECTORY"
readonly SCRIPT_DIRECTORY

readonly PYTHON_BIN=python3
readonly DEPENDENCY_CONSTRAINT=constraints/requirements-macos-py312.lock
readonly DEPENDENCY_BOOTSTRAP=requirements-bootstrap.txt
readonly DEPENDENCY_BOOTSTRAP_VERIFIER=scripts/verify_dependency_bootstrap.py
readonly DEPENDENCY_VERIFIER=scripts/verify_dependency_environment.py
readonly MACOS_BUNDLE_SPEC=packaging/macos/GM2Godot.spec
readonly MACOS_METADATA_POLICY=packaging/macos/bundle_metadata.py
readonly MACOS_METADATA_VERIFIER=scripts/verify_macos_bundle_metadata.py
readonly MACOS_GUI_VERIFIER=scripts/verify_macos_gui_artifact.py
export PIP_CONFIG_FILE=/dev/null
readonly -a REPOSITORY_SENTINELS=(
  build_macos.sh
  main.py
  requirements.txt
  "$DEPENDENCY_BOOTSTRAP"
  "$DEPENDENCY_CONSTRAINT"
  "$DEPENDENCY_BOOTSTRAP_VERIFIER"
  "$DEPENDENCY_VERIFIER"
  "$MACOS_BUNDLE_SPEC"
  "$MACOS_METADATA_POLICY"
  "$MACOS_METADATA_VERIFIER"
  "$MACOS_GUI_VERIFIER"
)

for repository_sentinel in "${REPOSITORY_SENTINELS[@]}"; do
  if [[ ! -f "$repository_sentinel" || -L "$repository_sentinel" ]]; then
    echo "Refusing to build outside the physical GM2Godot repository root: missing regular file $repository_sentinel."
    exit 1
  fi
done

if [[ "$#" -ne 2 || "${1:-}" != "--architecture" ]]; then
  echo "Usage: $0 --architecture arm64|x86_64" >&2
  exit 1
fi
case "$2" in
  arm64|x86_64) ;;
  *)
    echo "The native macOS architecture must be arm64 or x86_64." >&2
    exit 1
    ;;
esac
readonly MACOS_ARCHITECTURE="$2"
readonly BUILD_NAME="macos-${MACOS_ARCHITECTURE}"
readonly BUILD_DIRECTORY="build/${BUILD_NAME}"
readonly DIST_DIRECTORY="dist/${BUILD_NAME}"
readonly RELEASE_DIRECTORY="release/${BUILD_NAME}"
readonly DMG_DIRECTORY="dmg/${BUILD_NAME}"
readonly ZIP_ARTIFACT="GM2Godot-${BUILD_NAME}.zip"
readonly DMG_ARTIFACT="GM2Godot-${BUILD_NAME}.dmg"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS."
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "CPython 3.12.10 for macOS $MACOS_ARCHITECTURE is required, but python3 was not found."
  exit 1
fi

if ! "$PYTHON_BIN" - "$MACOS_ARCHITECTURE" <<'PY'
import platform
import sys

expected = ("CPython", "3.12.10", "darwin", "Darwin", sys.argv[1])
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
  echo "Install native CPython 3.12.10 for macOS $MACOS_ARCHITECTURE and make it available as python3."
  exit 1
fi

"$PYTHON_BIN" -I "$MACOS_GUI_VERIFIER" \
  --check-native-runtime \
  --expected-architecture "$MACOS_ARCHITECTURE"

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

BUILD_TEMP_ROOT="$(mktemp -d "${BUILD_TEMP_PARENT}/gm2godot-build-${MACOS_ARCHITECTURE}-XXXXXX")"
readonly BUILD_VENV="${BUILD_TEMP_ROOT}/venv"
readonly BOOTSTRAP_RECEIPT="${BUILD_TEMP_ROOT}/dependency-bootstrap-${BUILD_NAME}.json"
readonly BUILD_RECEIPT="${BUILD_TEMP_ROOT}/dependency-environment-${BUILD_NAME}.json"
readonly GUI_RECEIPT="${BUILD_TEMP_ROOT}/packaged-gui-${BUILD_NAME}.json"
readonly VENV_PYTHON="${BUILD_VENV}/bin/python"

"$PYTHON_BIN" "$DEPENDENCY_BOOTSTRAP_VERIFIER" \
  --source "$DEPENDENCY_BOOTSTRAP" \
  --policy stable \
  --constraint "$DEPENDENCY_CONSTRAINT" \
  --output "$BOOTSTRAP_RECEIPT"

echo "Creating isolated build environment..."
"$PYTHON_BIN" -m venv "$BUILD_VENV"
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "The isolated build environment did not create an executable Python interpreter."
  exit 1
fi

echo "Installing dependencies..."
"$VENV_PYTHON" -m pip --isolated --disable-pip-version-check --no-input install --no-cache-dir --only-binary=:all: \
  --constraint "$DEPENDENCY_CONSTRAINT" \
  pip
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
  --expected-machine "$MACOS_ARCHITECTURE" \
  --bootstrap "$DEPENDENCY_BOOTSTRAP" \
  --bootstrap-policy stable \
  --output "$BUILD_RECEIPT"

echo "Cleaning old build artifacts..."
rm -rf -- "$BUILD_DIRECTORY" "$DIST_DIRECTORY" "$RELEASE_DIRECTORY" "$DMG_DIRECTORY"
rm -f -- "$ZIP_ARTIFACT" "$DMG_ARTIFACT"

echo "Building macOS app bundle..."
"$VENV_PYTHON" -m PyInstaller --clean \
  --workpath "$BUILD_DIRECTORY" \
  --distpath "$DIST_DIRECTORY" \
  "$MACOS_BUNDLE_SPEC"

echo "Preparing release directory..."
mkdir -p "$RELEASE_DIRECTORY"
cp -R "$DIST_DIRECTORY/GM2Godot.app" "$RELEASE_DIRECTORY/"
cp README.md "$RELEASE_DIRECTORY/"

echo "Creating zip archive..."
(
  cd "$RELEASE_DIRECTORY"
  ditto -c -k --sequesterRsrc --keepParent GM2Godot.app "../../$ZIP_ARTIFACT"
)

echo "Creating DMG image..."
mkdir -p "$DMG_DIRECTORY"
cp -R "$RELEASE_DIRECTORY/GM2Godot.app" "$DMG_DIRECTORY/"
ln -s /Applications "$DMG_DIRECTORY/Applications"
hdiutil create \
  -volname "GM2Godot" \
  -srcfolder "$DMG_DIRECTORY" \
  -ov \
  -format UDZO \
  "$DMG_ARTIFACT"

echo "Verifying macOS bundle metadata..."
/usr/bin/plutil -lint "$DIST_DIRECTORY/GM2Godot.app/Contents/Info.plist"
"$VENV_PYTHON" -I "$MACOS_METADATA_VERIFIER" \
  --source-root "$SCRIPT_DIRECTORY" \
  --app "$SCRIPT_DIRECTORY/$DIST_DIRECTORY/GM2Godot.app" \
  --zip "$SCRIPT_DIRECTORY/$ZIP_ARTIFACT" \
  --dmg "$SCRIPT_DIRECTORY/$DMG_ARTIFACT" \
  --expected-architecture "$MACOS_ARCHITECTURE"

echo "Verifying the final ZIP's native macOS GUI..."
"$VENV_PYTHON" -I "$MACOS_GUI_VERIFIER" \
  --source-root "$SCRIPT_DIRECTORY" \
  --zip "$SCRIPT_DIRECTORY/$ZIP_ARTIFACT" \
  --expected-architecture "$MACOS_ARCHITECTURE" \
  --output "$GUI_RECEIPT"

cleanup_build_temp

echo "Build complete."
echo "App bundle: $DIST_DIRECTORY/GM2Godot.app"
echo "Zip: $ZIP_ARTIFACT"
echo "DMG: $DMG_ARTIFACT"
