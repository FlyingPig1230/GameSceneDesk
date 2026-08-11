"""Application resource and writable-data paths.

The source tree stays convenient for model development, while frozen builds
keep read-only resources inside the bundle and mutable feedback in the user's
application-data directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Ascent Map Recognizer"
APP_VERSION = "1.0.0"
APP_BUNDLE_ID = "local.gamescenedesk.ascent-map-recognizer"
DATA_DIR_ENV = "ASCENT_RECOGNIZER_DATA_DIR"

PROJECT_ROOT = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(
    getattr(sys, "_MEIPASS", PROJECT_ROOT)
).resolve()


def _platform_data_root() -> Path:
    override = os.environ.get(DATA_DIR_ENV)

    if override:
        return Path(override).expanduser().resolve()

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / APP_NAME
        )

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        return base / APP_NAME

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = (
        Path(xdg_data_home).expanduser()
        if xdg_data_home
        else Path.home() / ".local" / "share"
    )
    return base / "ascent-map-recognizer"


# Source runs intentionally keep the existing project layout so training and
# evaluation scripts remain usable. Frozen builds always use a writable,
# platform-native location. DATA_DIR_ENV can override either mode for testing.
if os.environ.get(DATA_DIR_ENV):
    APP_DATA_ROOT = _platform_data_root()
elif IS_FROZEN:
    APP_DATA_ROOT = _platform_data_root()
else:
    APP_DATA_ROOT = PROJECT_ROOT

ASSETS_DIR = RESOURCE_ROOT / "assets"
MODELS_DIR = RESOURCE_ROOT / "models"
SOURCE_DATA_DIR = RESOURCE_ROOT / "data"

DATA_DIR = APP_DATA_ROOT / "data"
FEEDBACK_DIR = DATA_DIR / "feedback"
REJECTION_DIR = DATA_DIR / "rejection"
EVALUATION_OUTPUT_DIR = APP_DATA_ROOT / "evaluation"


def ensure_app_data_root() -> Path:
    """Create and return the writable application-data directory."""

    APP_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return APP_DATA_ROOT
