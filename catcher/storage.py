"""捕获记录的本地持久化。"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from .codegen import normalize_capture
from .models import ElementCapture, SCHEMA_VERSION
from .paths import CAPTURES_FILE, DATA_DIR, THUMB_DIR


class CaptureStore:
    def __init__(self, data_dir: Path = DATA_DIR, captures_file: Path = CAPTURES_FILE) -> None:
        self.data_dir = data_dir
        self.path = captures_file
        self.thumb_dir = THUMB_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        self.last_error = ""

    def load(self) -> List[ElementCapture]:
        self.last_error = ""
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.last_error = f"读取捕获记录失败：{exc}"
            self._backup_corrupt()
            return []
        items = raw.get("captures") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            self.last_error = "捕获记录格式不正确，已忽略。"
            self._backup_corrupt()
            return []
        captures: List[ElementCapture] = []
        for item in items:
            try:
                if isinstance(item, dict):
                    captures.append(normalize_capture(ElementCapture.from_dict(item)))
            except Exception:
                continue
        captures.sort(key=lambda c: c.created_at, reverse=True)
        return captures

    def save(self, captures: Iterable[ElementCapture]) -> bool:
        payload = {
            "version": SCHEMA_VERSION,
            "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "captures": [c.to_dict() for c in captures],
        }
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
            return True
        except Exception as exc:
            self.last_error = f"保存捕获记录失败：{exc}"
            return False

    def add(self, capture: ElementCapture) -> None:
        captures = self.load()
        captures.insert(0, capture)
        self.save(captures)

    def delete(self, capture: ElementCapture) -> None:
        captures = [c for c in self.load() if c.id != capture.id]
        self.save(captures)
        self._remove_thumb(capture)

    def clear(self) -> None:
        self.save([])
        try:
            for path in self.thumb_dir.glob("*.png"):
                path.unlink(missing_ok=True)
        except Exception:
            pass

    def export_json(self, path: Path, captures: Iterable[ElementCapture]) -> bool:
        payload = {
            "version": SCHEMA_VERSION,
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "captures": [c.to_dict() for c in captures],
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except Exception as exc:
            self.last_error = f"导出失败：{exc}"
            return False

    def thumb_path(self, capture: ElementCapture) -> Optional[Path]:
        if not capture.screenshot:
            return None
        # 兼容历史记录里的绝对路径
        candidate = Path(capture.screenshot)
        if candidate.is_absolute() and candidate.exists():
            return candidate
        candidate = self.data_dir / capture.screenshot
        return candidate if candidate.exists() else None

    def _remove_thumb(self, capture: ElementCapture) -> None:
        path = self.thumb_path(capture)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    def _backup_corrupt(self) -> None:
        try:
            if self.path.exists():
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = self.path.with_name(f"captures.corrupt-{stamp}.json")
                shutil.copy2(self.path, backup)
        except Exception:
            pass
