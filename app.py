# -*- coding: utf-8 -*-
"""桌面元素捕获器入口。"""
from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _enable_dpi_awareness() -> None:
    """必须在创建 Tk 根窗口之前执行，保证 UIA 坐标与 Tk 坐标一致。"""
    try:
        user32 = ctypes.windll.user32
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
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()


def main() -> int:
    from catcher.logging_setup import install_exception_hooks, setup_logging
    from catcher.paths import LOG_DIR, ensure_dirs

    ensure_dirs()
    logger = setup_logging(LOG_DIR)
    logger.info("=" * 60)
    logger.info("启动桌面元素捕获器")
    try:
        import tkinter as tk

        from catcher.ui.app_ui import CatcherApp
        from catcher.ui.theme import Theme

        root = tk.Tk()
        theme = Theme(root)
        app = CatcherApp(root, theme)
        install_exception_hooks(root, logger)
        root.mainloop()
        return 0
    except Exception:
        logger.exception("应用启动失败")
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "启动失败",
                "桌面元素捕获器启动失败。\n\n"
                + traceback.format_exc(limit=4)
                + "\n详细信息已写入 data/logs/app.log。",
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
