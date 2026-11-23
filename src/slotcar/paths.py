"""Filesystem locations for bundled assets and user data.

Works both when running from source (``python -m slotcar``) and when frozen
with PyInstaller (assets are unpacked to ``sys._MEIPASS``; results are written
next to the executable).
"""

from __future__ import annotations

import sys
from pathlib import Path

_FROZEN = bool(getattr(sys, "frozen", False))

if _FROZEN:
    BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    DATA_ROOT = Path(sys.executable).resolve().parent
else:
    # src/slotcar/paths.py -> project root is two levels above the package.
    BUNDLE_ROOT = Path(__file__).resolve().parents[2]
    DATA_ROOT = BUNDLE_ROOT

ASSETS_DIR = BUNDLE_ROOT / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
RACE_MUSIC_FILE = ASSETS_DIR / "audio" / "race.mp3"
CHEERING_AUDIO_FILE = ASSETS_DIR / "audio" / "cheering.mp3"
APP_ICON_FILE = ASSETS_DIR / "app.ico"

RESULTS_DIR = DATA_ROOT / "results"
