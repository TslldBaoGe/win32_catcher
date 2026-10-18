"""屏幕高亮覆盖层：悬停提示与校验闪烁。"""
from __future__ import annotations

import ctypes
import tkinter as tk
from ctypes import wintypes
from typing import Optional, Tuple

from ..capture import HoverInfo
from ..winutil import get_cursor_pos, monitor_work_area

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4

user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL


def _top_hwnd(win: tk.Toplevel) -> int:
    hwnd = int(win.winfo_id())
    root = int(user32.GetAncestor(hwnd, 2) or 0)
    return root or hwnd


def _make_click_through(win: tk.Toplevel) -> int:
    win.update_idletasks()
    hwnd = _top_hwnd(win)
    ex = int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))
    ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    return hwnd


def _show(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        int(x),
        int(y),
        max(1, int(w)),
        max(1, int(h)),
        SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_NOOWNERZORDER,
    )
    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)


def _hide(hwnd: int) -> None:
    user32.ShowWindow(hwnd, SW_HIDE)


class ScreenOverlay:
    def __init__(self, root: tk.Tk, theme) -> None:
        self.root = root
        self.theme = theme
        self._jobs = []
        self._visible = False
        self._last_rect: Optional[Tuple[int, int, int, int]] = None
        self._last_info: Optional[HoverInfo] = None
        self._mode = "hover"

        self.strips = []
        for _ in range(4):
            win = tk.Toplevel(root)
            win.withdraw()
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.96)
            win.configure(bg=theme.accent)
            win.update_idletasks()
            hwnd = _make_click_through(win)
            win._overlay_hwnd = hwnd  # type: ignore[attr-defined]
            self.strips.append(win)

        self.card = tk.Toplevel(root)
        self.card.withdraw()
        self.card.overrideredirect(True)
        self.card.attributes("-topmost", True)
        self.card.attributes("-alpha", 0.97)
        self.card.configure(bg=theme.surface_2)
        self.card.update_idletasks()
        card_hwnd = _make_click_through(self.card)
        self.card._overlay_hwnd = card_hwnd  # type: ignore[attr-defined]

        self.card_frame = tk.Frame(
            self.card,
            bg=theme.surface_2,
            highlightbackground=theme.border_light,
            highlightthickness=1,
            bd=0,
        )
        self.card_frame.pack(fill="both", expand=True)
        self.card_accent = tk.Frame(self.card_frame, bg=theme.accent, width=theme.px(4))
        self.card_accent.pack(side="left", fill="y")
        self.card_body = tk.Frame(self.card_frame, bg=theme.surface_2)
        self.card_body.pack(side="left", fill="both", expand=True, padx=theme.px(12), pady=theme.px(9))

        top_line = tk.Frame(self.card_body, bg=theme.surface_2)
        top_line.pack(fill="x")
        self.card_type = tk.Label(
            top_line,
            text="",
            bg=theme.surface_2,
            fg=theme.accent,
            font=theme.font_small_bold,
            anchor="w",
        )
        self.card_type.pack(side="left")
        self.card_pid = tk.Label(
            top_line,
            text="",
            bg=theme.surface_2,
            fg=theme.faint,
            font=theme.font_tiny,
            anchor="e",
        )
        self.card_pid.pack(side="right")

        self.card_name = tk.Label(
            self.card_body,
            text="",
            bg=theme.surface_2,
            fg=theme.text,
            font=theme.font_body_bold,
            anchor="w",
            justify="left",
            wraplength=theme.px(330),
        )
        self.card_name.pack(fill="x", pady=(theme.px(3), theme.px(1)))

        self.card_meta = tk.Label(
            self.card_body,
            text="",
            bg=theme.surface_2,
            fg=theme.muted,
            font=theme.font_tiny,
            anchor="w",
            justify="left",
            wraplength=theme.px(330),
        )
        self.card_meta.pack(fill="x")

        self.card_hint = tk.Label(
            self.card_body,
            text="",
            bg=theme.surface_2,
            fg=theme.accent,
            font=theme.font_tiny,
            anchor="w",
        )
        self.card_hint.pack(fill="x", pady=(theme.px(5), 0))

        self._card_width = theme.px(360)

    # ---------- 对外接口 ----------
    def show(self, rect: Tuple[int, int, int, int], info: Optional[HoverInfo] = None, mode: str = "hover") -> bool:
        left, top, right, bottom = (int(v) for v in rect)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            self.hide()
            return False
        self._cancel_jobs()
        self._visible = True
        self._last_rect = (left, top, right, bottom)
        self._last_info = info
        self._mode = mode
        if mode == "verify":
            color = self.theme.green
        elif mode == "warn":
            color = self.theme.amber
        else:
            color = self.theme.accent
        thickness = self.theme.px(4 if mode == "verify" else 3)
        thickness = max(1, min(thickness, width, height))

        for strip in self.strips:
            strip.configure(bg=color)
        self.card_accent.configure(bg=color)
        self.card_type.configure(fg=color)
        self.card_hint.configure(fg=color)

        self._update_card(info, mode)
        self.card.update_idletasks()
        card_w = self._card_width
        card_h = max(self.theme.px(96), self.card_body.winfo_reqheight() + self.theme.px(22))

        # 边框四条
        geometry = (
            (left, top, width, thickness),
            (left, bottom - thickness, width, thickness),
            (left, top, thickness, height),
            (right - thickness, top, thickness, height),
        )
        for strip, (x, y, w, h) in zip(self.strips, geometry):
            _show(int(strip._overlay_hwnd), x, y, w, h)  # type: ignore[attr-defined]

        # 悬停卡片跟随鼠标；校验卡片贴着目标元素，避免遮挡应用界面。
        if mode in ("verify", "warn"):
            anchor_x, anchor_y = left, top
            work = monitor_work_area((left + right) // 2, (top + bottom) // 2)
        else:
            anchor_x, anchor_y = get_cursor_pos()
            work = monitor_work_area(anchor_x, anchor_y)
        margin = self.theme.px(8)
        if mode in ("verify", "warn"):
            # 优先放在目标上方，其次右侧、左侧、下方，尽量不遮挡应用。
            above_x = max(work[0] + margin, min(left, work[2] - card_w - margin))
            above_y = top - card_h - self.theme.px(8)
            if above_y >= work[1] + margin:
                card_x, card_y = above_x, above_y
            else:
                card_x = right + self.theme.px(12)
                card_y = top
                if card_x + card_w > work[2] - margin:
                    card_x = left - card_w - self.theme.px(12)
                if card_y + card_h > work[3] - margin:
                    card_y = bottom - card_h
                if card_y < work[1] + margin:
                    card_y = work[1] + margin
        else:
            card_x = anchor_x + self.theme.px(18)
            card_y = anchor_y + self.theme.px(22)
            if card_x + card_w > work[2] - margin:
                card_x = anchor_x - card_w - self.theme.px(18)
            if card_y + card_h > work[3] - margin:
                card_y = anchor_y - card_h - self.theme.px(22)
        card_x = max(work[0] + margin, min(card_x, work[2] - card_w - margin))
        card_y = max(work[1] + margin, min(card_y, work[3] - card_h - margin))
        _show(int(self.card._overlay_hwnd), card_x, card_y, card_w, card_h)  # type: ignore[attr-defined]
        return True

    def flash(
        self,
        rect: Tuple[int, int, int, int],
        info: Optional[HoverInfo] = None,
        duration_ms: int = 2600,
        mode: str = "verify",
    ) -> bool:
        ok = self.show(rect, info, mode=mode)
        if ok:
            job = self.root.after(int(duration_ms), self.hide)
            self._jobs.append(job)
        return ok

    def hide(self) -> None:
        self._cancel_jobs()
        for strip in self.strips:
            try:
                _hide(int(strip._overlay_hwnd))  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            _hide(int(self.card._overlay_hwnd))  # type: ignore[attr-defined]
        except Exception:
            pass
        self._visible = False

    def destroy(self) -> None:
        self.hide()
        for win in self.strips:
            try:
                win.destroy()
            except Exception:
                pass
        try:
            self.card.destroy()
        except Exception:
            pass

    @property
    def visible(self) -> bool:
        return self._visible

    # ---------- 内部 ----------
    def _cancel_jobs(self) -> None:
        for job in self._jobs:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass
        self._jobs.clear()

    def _update_card(self, info: Optional[HoverInfo], mode: str) -> None:
        if mode in ("verify", "warn"):
            if mode == "warn":
                self.card_type.configure(text="! 校验警告")
                self.card_hint.configure(text="定位成功，但部分属性与捕获时不同")
            else:
                self.card_type.configure(text="✓ 校验高亮")
                self.card_hint.configure(text="独立进程定位通过 · 高亮验证中")
            self.card_pid.configure(text="")
            if info is not None:
                self.card_name.configure(text=info.display_name)
            else:
                self.card_name.configure(text="元素已重新定位")
            if self.card_meta.winfo_manager():
                self.card_meta.pack_forget()
            return
        if not self.card_meta.winfo_manager():
            self.card_meta.pack(fill="x", before=self.card_hint)

        if info is None:
            self.card_type.configure(text="移动鼠标选择元素")
            self.card_pid.configure(text="")
            self.card_name.configure(text="等待目标…")
            self.card_meta.configure(text="")
            self.card_hint.configure(text="F2 捕获 · Esc 取消")
            return

        type_text = f"{info.type_label} · {info.control_type_name or 'Control'}"
        self.card_type.configure(text=type_text)
        self.card_pid.configure(text=f"PID {info.process_id}" if info.process_id else "")
        name = info.display_name.replace("\n", " ")
        if len(name) > 80:
            name = name[:77] + "..."
        self.card_name.configure(text=name)
        meta_bits = []
        if info.automation_id:
            meta_bits.append(f"AutomationId: {info.automation_id[:48]}")
        if info.class_name:
            meta_bits.append(f"Class: {info.class_name[:48]}")
        if not meta_bits:
            meta_bits.append(info.process_name or f"PID {info.process_id}")
        self.card_meta.configure(text=" · ".join(meta_bits))
        self.card_hint.configure(text="F2 捕获 · Esc 取消")
