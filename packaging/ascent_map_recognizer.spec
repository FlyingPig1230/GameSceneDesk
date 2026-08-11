# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path


PROJECT_ROOT = Path(SPECPATH).resolve().parent
APP_NAME = "Ascent Map Recognizer"
APP_VERSION = "1.0.0"
IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

RESOURCE_FILES = (
    "assets/app_icon_transparent.png",
    "assets/valorant_mark_transparent.png",
    "assets/riot_mark_transparent.png",
    "models/ascent_area_classifier.pt",
    "models/ascent_relevance_profile.pt",
    "models/split_area_classifier.pt",
    "models/split_relevance_profile.pt",
)

datas = [
    (
        str(PROJECT_ROOT / relative_path),
        str(Path(relative_path).parent),
    )
    for relative_path in RESOURCE_FILES
]

analysis = Analysis(
    [str(PROJECT_ROOT / "app.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cv2",
        "matplotlib",
        "scipy",
        "sklearn",
        "tqdm",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe_options = {
    "icon": (
        str(PROJECT_ROOT / "assets" / "app_icon_transparent.png")
        if IS_WINDOWS
        else None
    ),
}

if IS_MACOS:
    exe_options.update({
        "argv_emulation": False,
        "target_arch": "arm64",
        "codesign_identity": None,
        "entitlements_file": None,
    })

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    contents_directory="_internal",
    **exe_options,
)

collected = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if IS_MACOS:
    app_bundle = BUNDLE(
        collected,
        name=f"{APP_NAME}.app",
        icon=str(PROJECT_ROOT / "AppIcon.icns"),
        bundle_identifier=(
            "local.gamescenedesk.ascent-map-recognizer"
        ),
        version=APP_VERSION,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "15.0",
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
        },
    )
