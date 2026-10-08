"""Application-wide constants and paths.

User data (database, logs) is stored OUTSIDE the program folder so that
upgrading or reinstalling the application never touches it:

    Windows : %LOCALAPPDATA%\\PDFWorkbench\\
    Other   : ~/.pdfworkbench/
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "BRB PDF"
APP_ID = "PDFWorkbench"
APP_VERSION = "0.5.0"
APP_PHASE = "Viewer, OCR, pages, editing, comments and analysis"


def _data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_ID
    return Path.home() / ".pdfworkbench"


DATA_DIR: Path = _data_dir()
LOG_DIR: Path = DATA_DIR / "logs"
DB_PATH: Path = DATA_DIR / "workbench.sqlite3"


def resource_dir() -> Path:
    """Folder that holds bundled read-only resources (icons etc.).

    Works both when running from source and from a PyInstaller build.
    """
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base:
        return Path(frozen_base)
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Folder of PDFWorkbench.exe (built) or the project folder (from source).
    User-replaceable files such as OCR language data live here."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def asset_path(name: str) -> Path:
    return resource_dir() / "assets" / name


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


# Viewer defaults
DEFAULT_ZOOM = 1.0            # 1.0 == 100 %
MIN_ZOOM = 0.10
MAX_ZOOM = 8.00
ZOOM_STEPS = [0.10, 0.25, 0.33, 0.50, 0.67, 0.75, 0.90, 1.00, 1.10, 1.25,
              1.50, 1.75, 2.00, 2.50, 3.00, 4.00, 5.00, 6.00, 8.00]
PAGE_GAP = 12                 # pixels between pages in the viewer
RENDER_CACHE_MB = 300         # memory budget for rendered pages
THUMB_CACHE_MB = 120          # memory budget for thumbnails
THUMB_WIDTH = 110             # logical pixels
MAX_RECENT_FILES = 15
