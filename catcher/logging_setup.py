"""日志与全局异常处理。"""
from __future__ import annotations

import logging
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_LOGGER: Optional[logging.Logger] = None


def setup_logging(log_dir: Path) -> logging.Logger:
    global _LOGGER
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("element_catcher")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        _LOGGER = logger
        return logger

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=1_500_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        logger.addHandler(stream)

    _LOGGER = logger
    return logger


def get_logger() -> logging.Logger:
    return _LOGGER or logging.getLogger("element_catcher")


def install_exception_hooks(root, logger: logging.Logger) -> None:
    def show_error(title: str, message: str) -> None:
        try:
            from tkinter import messagebox

            messagebox.showerror(title, message, parent=root)
        except Exception:
            pass

    def handle_exception(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.error(
            "未处理异常\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        show_error(
            "发生未处理错误",
            f"{exc_type.__name__}: {exc_value}\n\n详细信息已写入 data/logs/app.log。",
        )

    sys.excepthook = handle_exception

    def thread_exception(args) -> None:
        logger.error(
            "线程未处理异常：%s\n%s",
            getattr(args.thread, "name", "thread"),
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )

    try:
        threading.excepthook = thread_exception
    except Exception:
        pass

    def tk_callback_exception(exc_type, exc_value, exc_tb) -> None:
        logger.error(
            "Tk 回调异常\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        show_error(
            "操作失败",
            f"{exc_type.__name__}: {exc_value}\n\n详细信息已写入 data/logs/app.log。",
        )

    root.report_callback_exception = tk_callback_exception
