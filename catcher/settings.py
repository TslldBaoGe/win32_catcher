# -*- coding: utf-8 -*-
"""应用设置（Python 解释器等）的读写。"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .paths import SETTINGS_FILE


@dataclass
class AppSettings:
    # 用于独立进程回放/验证的 Python 解释器；空串表示用当前解释器
    python_exe: str = ""

    def resolved_python(self) -> str:
        candidate = (self.python_exe or "").strip().strip('"')
        if candidate and Path(candidate).exists():
            return candidate
        # 源码运行：用当前解释器；exe 运行：返回空串，由调用方引导去设置里指定
        if not getattr(sys, "frozen", False):
            return sys.executable
        return ""


def load_settings(path: Optional[Path] = None) -> AppSettings:
    file = path or SETTINGS_FILE
    if not file.exists():
        return AppSettings()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except Exception:
        return AppSettings()
    if not isinstance(raw, dict):
        return AppSettings()
    settings = AppSettings()
    exe = raw.get("python_exe")
    if isinstance(exe, str):
        settings.python_exe = exe.strip().strip('"')
    return settings


def save_settings(settings: AppSettings, path: Optional[Path] = None) -> bool:
    file = path or SETTINGS_FILE
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        temp = file.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, file)
        # 供 run.bat 直接读取的纯文本路径（bat 解析 JSON 不可靠）
        try:
            sidecar = file.parent / "python_path.txt"
            sidecar.write_text(settings.python_exe.strip().strip('"'), encoding="utf-8")
        except Exception:
            pass
        return True
    except Exception:
        return False


def scan_python_envs(current: str = "") -> list:
    """扫描常见 Miniconda/Anaconda/当前解释器位置下的 python.exe。"""
    candidates: list = []
    seen: set = set()

    def add(path) -> None:
        try:
            resolved = str(Path(path).resolve())
        except Exception:
            return
        if resolved not in seen and Path(resolved).exists():
            seen.add(resolved)
            candidates.append(resolved)

    bases: list = []
    current = (current or "").strip().strip('"')
    if current:
        cur = Path(current)
        bases.append(cur.parent if cur.is_file() else cur)
    exe_dir = Path(sys.executable).parent
    bases.append(exe_dir)
    home = Path.home()
    bases.append(home / "miniconda3")
    bases.append(home / "anaconda3")

    for base in bases:
        try:
            add(base / "python.exe")
            for env_exe in base.glob("envs/*/python.exe"):
                add(env_exe)
        except Exception:
            continue
    return candidates
