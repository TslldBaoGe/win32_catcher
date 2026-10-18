"""Windows 平台相关的小工具。"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Optional, Tuple

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MONITOR_DEFAULTTONEAREST = 2


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def enable_dpi_awareness() -> None:
    """必须在创建任何 Tk 窗口之前调用。"""
    try:
        # PER_MONITOR_AWARE_V2 = -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def system_dpi() -> int:
    try:
        dpi = int(user32.GetDpiForSystem())
        if dpi > 0:
            return dpi
    except Exception:
        pass
    try:
        hdc = user32.GetDC(0)
        dpi = int(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))  # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        return dpi or 96
    except Exception:
        return 96


def dpi_scale() -> float:
    return max(1.0, system_dpi() / 96.0)


def get_cursor_pos() -> Tuple[int, int]:
    pt = POINT()
    if user32.GetCursorPos(ctypes.byref(pt)):
        return int(pt.x), int(pt.y)
    return (0, 0)


def set_cursor_pos(x: int, y: int) -> None:
    try:
        user32.SetCursorPos(int(x), int(y))
    except Exception:
        pass


def virtual_screen_rect() -> Tuple[int, int, int, int]:
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    if width <= 0 or height <= 0:
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
        left, top = 0, 0
    return left, top, left + width, top + height


def intersects_virtual_screen(rect: Tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    vx1, vy1, vx2, vy2 = virtual_screen_rect()
    return right > vx1 and bottom > vy1 and left < vx2 and top < vy2


def monitor_work_area(x: int, y: int) -> Tuple[int, int, int, int]:
    try:
        monitor = user32.MonitorFromPoint(POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcWork
            return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:
        pass
    return virtual_screen_rect()


def get_window_text(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        user32.GetWindowTextW(int(hwnd), buf, len(buf))
        return buf.value
    except Exception:
        return ""


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def set_foreground_window(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        if user32.IsIconic(int(hwnd)):
            user32.ShowWindow(int(hwnd), 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(int(hwnd)))
    except Exception:
        return False


def restart_as_admin(script_path: Path, cwd: Path) -> bool:
    """以管理员身份重启。返回 True 表示已启动。"""
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = ""
        else:
            exe = sys.executable
            params = f'"{script_path}"'
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, str(cwd), 1
        )
        return int(result) > 32
    except Exception:
        return False


def open_folder(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        pass


def create_app_icon(path: Path, size: int = 64) -> Optional[Path]:
    """生成一个简单的十字准星应用图标。"""
    try:
        from PIL import Image, ImageDraw

        path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        margin = max(1, size // 16)
        draw.rounded_rectangle(
            (margin, margin, size - margin, size - margin),
            radius=size // 5,
            fill="#0B1220",
            outline="#2DD4BF",
            width=max(1, size // 24),
        )
        center = size / 2
        ring = size * 0.23
        line = max(2, size // 16)
        draw.ellipse(
            (center - ring, center - ring, center + ring, center + ring),
            outline="#2DD4BF",
            width=line,
        )
        draw.line((center, size * 0.18, center, center - ring), fill="#2DD4BF", width=line)
        draw.line((center, center + ring, center, size * 0.82), fill="#2DD4BF", width=line)
        draw.line((size * 0.18, center, center - ring, center), fill="#2DD4BF", width=line)
        draw.line((center + ring, center, size * 0.82, center), fill="#2DD4BF", width=line)
        draw.ellipse(
            (center - line, center - line, center + line, center + line),
            fill="#E6FFFA",
        )
        image.save(path, "PNG")
        return path
    except Exception:
        return None
