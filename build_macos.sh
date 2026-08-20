#!/bin/zsh

set -euo pipefail

ROOT_DIR="${0:A:h}"
APP_VERSION="1.0.0"
BUILD_VENV="$ROOT_DIR/.build-venv-macos"
SPEC_FILE="$ROOT_DIR/packaging/ascent_map_recognizer.spec"
DIST_DIR="$ROOT_DIR/dist/macos"
WORK_DIR="$ROOT_DIR/build/macos"
export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/build/pyinstaller-cache/macos"
APP_PATH="$DIST_DIR/Ascent Map Recognizer.app"
ZIP_PATH="$DIST_DIR/Ascent-Map-Recognizer-Public-Tester-v${APP_VERSION}-macOS-arm64.zip"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script must run on macOS."
    exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
    echo "This release target requires an Apple Silicon build host."
    exit 1
fi

required_files=(
    "AppIcon.icns"
    "assets/app_icon_transparent.png"
    "assets/valorant_mark_transparent.png"
    "assets/riot_mark_transparent.png"
    "models/ascent_area_classifier.pt"
    "models/ascent_classes.json"
    "models/ascent_relevance_profile.pt"
    "models/split_area_classifier.pt"
    "models/split_classes.json"
    "models/split_relevance_profile.pt"
)

for relative_path in "${required_files[@]}"; do
    if [[ ! -f "$ROOT_DIR/$relative_path" ]]; then
        echo "Missing required file: $relative_path"
        exit 1
    fi
done

bootstrap_python="${PYTHON_BOOTSTRAP:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$bootstrap_python" ]]; then
    bootstrap_python="$(command -v python3 || true)"
fi

if [[ -z "$bootstrap_python" ]]; then
    echo "Python 3 was not found."
    exit 1
fi

if [[ ! -x "$BUILD_VENV/bin/python" ]]; then
    "$bootstrap_python" -m venv "$BUILD_VENV"
fi

build_python="$BUILD_VENV/bin/python"

"$build_python" -m pip install --upgrade pip
"$build_python" -m pip install -r "$ROOT_DIR/requirements-build.txt"
"$build_python" -c \
    'import platform, struct; assert platform.machine() == "arm64"; assert struct.calcsize("P") * 8 == 64'

"$build_python" -m PyInstaller \
    --noconfirm \
    --clean \
    --distpath "$DIST_DIR" \
    --workpath "$WORK_DIR" \
    "$SPEC_FILE"

if [[ ! -d "$APP_PATH" ]]; then
    echo "Build finished without producing the expected app bundle."
    exit 1
fi

# Ad-hoc signing is enough for local testing. Public distribution still needs
# a Developer ID signature and Apple notarization.
/usr/bin/codesign \
    --force \
    --deep \
    --sign - \
    "$APP_PATH"
/usr/bin/codesign \
    --verify \
    --deep \
    --strict \
    --verbose=2 \
    "$APP_PATH"

ASCENT_RECOGNIZER_SMOKE_TEST=1 \
ASCENT_RECOGNIZER_SMOKE_IMAGE="$ROOT_DIR/assets/app_icon_transparent.png" \
QT_QPA_PLATFORM=offscreen \
    "$APP_PATH/Contents/MacOS/Ascent Map Recognizer"

/usr/bin/ditto \
    -c \
    -k \
    --keepParent \
    "$APP_PATH" \
    "$ZIP_PATH"

echo "macOS app: $APP_PATH"
echo "macOS archive: $ZIP_PATH"
