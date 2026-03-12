"""Path resolution for frozen (PyInstaller) and dev modes.

Key distinction for frozen mode:
  - EXE_DIR: where the .exe lives (for .env, data/, logs/)
  - BUNDLE_DIR: where PyInstaller extracts bundled files (templates/, static/, services/)
    For --onedir this is _internal/ subfolder (sys._MEIPASS)
    For --onefile this is a temp dir (sys._MEIPASS)
"""

import sys
import os
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # EXE_DIR = directory containing the .exe (user-facing files: .env, logs, data)
    EXE_DIR = Path(sys.executable).resolve().parent
    # BUNDLE_DIR = where PyInstaller puts bundled datas (templates, static, services)
    # In --onedir mode this is <exe_dir>/_internal/
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", EXE_DIR))
    APP_DIR = EXE_DIR
    ENV_PATH = EXE_DIR / ".env"
    PROJECT_ROOT = EXE_DIR
    TEMPLATE_DIR = BUNDLE_DIR / "templates"
    STATIC_DIR = BUNDLE_DIR / "static"
else:
    # Dev mode: dashboard/ is the app dir
    APP_DIR = Path(__file__).resolve().parent
    ENV_PATH = APP_DIR.parent / ".env"
    PROJECT_ROOT = APP_DIR.parent
    TEMPLATE_DIR = APP_DIR / "templates"
    STATIC_DIR = APP_DIR / "static"

DATA_DIR = APP_DIR / "data"
LOG_DIR = APP_DIR / "logs"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
