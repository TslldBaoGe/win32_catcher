"""应用路径与常量。"""
from __future__ import annotations

import sys
from pathlib import Path

# 打包成 exe 后，数据目录放在 exe 旁边，而不是临时解压目录
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
THUMB_DIR = DATA_DIR / "thumbs"
LOG_DIR = DATA_DIR / "logs"
CAPTURES_FILE = DATA_DIR / "captures.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
CUSTOM_CODE_FILE = DATA_DIR / "custom_code.py"
APP_SCRIPT = APP_DIR / "app.py"

SEARCH_TIMEOUT = 5.0
VERIFY_TIMEOUT = 30.0


def ensure_dirs() -> None:
    for path in (DATA_DIR, THUMB_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
