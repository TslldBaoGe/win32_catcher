"""后台工作线程：悬停查询、捕获与元素操作。"""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Optional

import uiautomation as auto

from .actions import ActionError, element_click, element_input, element_value, locate_capture
from .capture import CaptureError, HoverInfo, capture_from_point, hover_from_point
from .logging_setup import get_logger


class PickerWorker(threading.Thread):
    def __init__(self, events: "queue.Queue", thumb_dir: Path) -> None:
        super().__init__(name="picker-worker", daemon=True)
        self.events = events
        self.thumb_dir = thumb_dir
        self._cond = threading.Condition()
        self._hover = None  # (x, y, seq)
        self._capture = None  # (x, y)
        self._action = None  # (kind, payload, capture)
        self._stop = False
        self.logger = get_logger()

    def hover(self, x: int, y: int, seq: int) -> None:
        with self._cond:
            if self._capture is None and self._action is None:
                self._hover = (int(x), int(y), int(seq))
                self._cond.notify()

    def capture(self, x: int, y: int) -> None:
        with self._cond:
            self._capture = (int(x), int(y))
            self._hover = None
            self._cond.notify()

    def action(self, kind: str, payload, capture) -> None:
        with self._cond:
            self._action = (kind, payload, capture)
            self._hover = None
            self._capture = None
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()

    def _run_action(self, kind: str, payload, capture) -> None:
        try:
            ctrl = locate_capture(capture, timeout=5.0)
            if kind == "click":
                message = element_click(ctrl)
                self.events.put(("action_done", kind, message))
            elif kind == "input":
                message = element_input(ctrl, "" if payload is None else str(payload))
                self.events.put(("action_done", kind, message))
            elif kind == "get_value":
                value, source = element_value(ctrl)
                self.events.put(("action_value", kind, value, source))
            else:
                self.events.put(("action_error", kind, f"未知操作：{kind}", ""))
        except ActionError as exc:
            self.events.put(("action_error", kind, str(exc), exc.hint))
        except Exception as exc:
            self.logger.exception("元素操作失败")
            self.events.put(("action_error", kind, f"操作失败：{exc}", ""))

    def run(self) -> None:
        try:
            with auto.UIAutomationInitializerInThread():
                self.logger.info("PickerWorker UIA 初始化完成")
                while True:
                    with self._cond:
                        while not self._stop and not self._hover and not self._capture and not self._action:
                            self._cond.wait(timeout=0.5)
                        if self._stop:
                            break
                        hover_req = self._hover
                        capture_req = self._capture
                        action_req = self._action
                        self._hover = None
                        self._capture = None
                        self._action = None

                    if action_req is not None:
                        self._run_action(*action_req)
                        continue

                    if capture_req is not None:
                        x, y = capture_req
                        try:
                            capture = capture_from_point(x, y, self.thumb_dir)
                            self.events.put(("captured", capture))
                        except CaptureError as exc:
                            self.events.put(("capture_error", exc))
                        except Exception as exc:
                            self.logger.exception("捕获元素失败")
                            self.events.put(("capture_error", CaptureError(f"捕获失败：{exc}")))
                        continue

                    if hover_req is not None:
                        x, y, seq = hover_req
                        try:
                            info = hover_from_point(x, y)
                        except Exception:
                            self.logger.exception("悬停查询失败")
                            info = None
                        self.events.put(("hover", info, seq))
        except Exception:
            self.logger.exception("PickerWorker 异常退出")
        finally:
            self.logger.info("PickerWorker 退出")
