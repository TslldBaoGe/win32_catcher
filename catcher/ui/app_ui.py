"""主界面与捕获/校验流程。"""
from __future__ import annotations

import ctypes
import queue
import os
import re
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageTk

from ..capture import CaptureError, HoverInfo
from ..logging_setup import get_logger
from ..models import ElementCapture, control_type_label
from ..paths import APP_DIR, APP_SCRIPT, CUSTOM_CODE_FILE, DATA_DIR, LOG_DIR, THUMB_DIR
from ..storage import CaptureStore
from ..verifier import CheckResult, VerifyResult, run_verification
from ..winutil import (
    create_app_icon,
    dpi_scale,
    get_cursor_pos,
    is_admin,
    monitor_work_area,
    open_folder,
    restart_as_admin,
    set_foreground_window,
    system_dpi,
    virtual_screen_rect,
)
from ..workers import PickerWorker
from ..settings import load_settings, save_settings
from .dialogs import ask_text, show_settings, show_value
from .overlay import ScreenOverlay
from .theme import Theme
from .widgets import (
    CodeViewer,
    DarkScrollbar,
    Pill,
    RoundedButton,
    ScrollableFrame,
    SegmentedControl,
    Tooltip,
    _round_rect,
)

user32 = ctypes.windll.user32
VK_F2 = 0x71
VK_ESCAPE = 0x1B

TYPE_GLYPHS: Dict[str, str] = {
    "ButtonControl": "◉",
    "SplitButtonControl": "◈",
    "CheckBoxControl": "☑",
    "RadioButtonControl": "◉",
    "ComboBoxControl": "▾",
    "EditControl": "▤",
    "DocumentControl": "▥",
    "TextControl": "T",
    "WindowControl": "▣",
    "PaneControl": "▢",
    "GroupControl": "▢",
    "MenuBarControl": "☰",
    "MenuControl": "☰",
    "MenuItemControl": "▸",
    "ListControl": "☷",
    "ListItemControl": "•",
    "TreeControl": "⌄",
    "TreeItemControl": "›",
    "TabControl": "▭",
    "TabItemControl": "▭",
    "ToolBarControl": "⚙",
    "TitleBarControl": "▔",
    "ImageControl": "▧",
    "HyperlinkControl": "↗",
    "DataGridControl": "▦",
    "TableControl": "▦",
    "ProgressBarControl": "▬",
    "SliderControl": "▬",
    "ScrollBarControl": "▮",
    "StatusBarControl": "▁",
    "CustomControl": "◇",
}


def _key_down(vk: int) -> bool:
    try:
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


class CatcherApp:
    def __init__(self, root: tk.Tk, theme: Theme) -> None:
        self.root = root
        self.theme = theme
        self.logger = get_logger()
        self.store = CaptureStore()
        self.settings = load_settings()
        self.captures: List[ElementCapture] = self.store.load()
        self._startup_error = self.store.last_error
        self._current: Optional[ElementCapture] = None
        self._current_id = ""
        self._filtered: List[ElementCapture] = []
        self._current_mode = "uiautomation"
        self._active_tab = "code"
        self._suppress_select = False
        self._picking = False
        self._capturing = False
        self._capture_timeout_job = None
        self._restore_state = "normal"
        self._last_cursor: Tuple[int, int] = (0, 0)
        self._last_hover_query = 0.0
        self._hover_seq = 0
        self._applied_hover_seq = -1
        self._prev_f2 = False
        self._prev_esc = False
        self._closing = False
        self._verify_running = False
        self._verify_generation = 0
        self._verify_result: Optional[VerifyResult] = None
        self._action_running = False
        self._action_kind = ""
        self._custom_running = False
        self._custom_save_job = None
        self._custom_run_count = 0
        self._action_timeout_job = None
        self._action_hid_window = False
        self._toast_frame: Optional[tk.Frame] = None
        self._toast_job = None
        self._thumb_photo = None
        self._icon_photo = None
        self._menu: Optional[tk.Menu] = None
        self._search_active = True
        self._search_placeholder = "搜索名称 / 类型 / 进程"

        self._events: "queue.Queue" = queue.Queue()
        self._picker = PickerWorker(self._events, THUMB_DIR)

        self._setup_window()
        self._build_ui()
        self._update_python_hint()
        # 启动时置顶一次，避免被其他窗口挡住导致以为启动失败
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.overlay = ScreenOverlay(root, theme)
        self._picker.start()
        self._refresh_tree()
        self._bind_events()
        self._schedule_loops()

        if self._startup_error:
            self.root.after(500, lambda: self._toast(self._startup_error, "error"))
        self.logger.info("应用启动，已加载 %d 条捕获记录", len(self.captures))

    # ------------------------------------------------------------------
    # 窗口与构建
    # ------------------------------------------------------------------
    def _setup_window(self) -> None:
        self.root.title("桌面元素捕获器 · Desktop Element Catcher")
        self.root.configure(bg=self.theme.bg)
        vx1, vy1, vx2, vy2 = virtual_screen_rect()
        work = monitor_work_area(vx1 + 10, vy1 + 10)
        avail_w = max(800, work[2] - work[0])
        avail_h = max(560, work[3] - work[1])
        width = min(self.theme.px(1180), avail_w - self.theme.px(40))
        height = min(self.theme.px(760), avail_h - self.theme.px(40))
        x = work[0] + (avail_w - width) // 2
        y = work[1] + (avail_h - height) // 2
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(
            min(self.theme.px(1000), avail_w),
            min(self.theme.px(660), avail_h),
        )

        try:
            icon_path = create_app_icon(DATA_DIR / "icon.png")
            if icon_path:
                image = Image.open(icon_path).convert("RGBA")
                self._icon_photo = ImageTk.PhotoImage(image)
                self.root.iconphoto(True, self._icon_photo)
        except Exception:
            self.logger.exception("加载应用图标失败")

    def _build_ui(self) -> None:
        self._build_topbar()
        self._build_statusbar()
        self._build_body()

    def _build_topbar(self) -> None:
        t = self.theme
        topbar = tk.Frame(self.root, bg=t.bg)
        topbar.pack(side="top", fill="x")
        inner = tk.Frame(topbar, bg=t.bg)
        inner.pack(fill="x", padx=t.px(18), pady=t.px(12))

        brand = tk.Frame(inner, bg=t.bg)
        brand.pack(side="left")
        logo = tk.Canvas(brand, width=t.px(40), height=t.px(40), bg=t.bg, highlightthickness=0)
        logo.pack(side="left", padx=(0, t.px(10)))
        _round_rect(logo, 1, 1, t.px(39), t.px(39), t.px(11), fill=t.surface_2, outline=t.border_light, width=1)
        cx, cy = t.px(20), t.px(20)
        logo.create_oval(cx - t.px(8), cy - t.px(8), cx + t.px(8), cy + t.px(8), outline=t.accent, width=t.px(2))
        logo.create_line(cx, t.px(5), cx, cy - t.px(8), fill=t.accent, width=t.px(2))
        logo.create_line(cx, cy + t.px(8), cx, t.px(35), fill=t.accent, width=t.px(2))
        logo.create_line(t.px(5), cy, cx - t.px(8), cy, fill=t.accent, width=t.px(2))
        logo.create_line(cx + t.px(8), cy, t.px(35), cy, fill=t.accent, width=t.px(2))
        logo.create_oval(cx - t.px(2), cy - t.px(2), cx + t.px(2), cy + t.px(2), fill=t.text, outline="")

        title_box = tk.Frame(brand, bg=t.bg)
        title_box.pack(side="left")
        tk.Label(
            title_box,
            text="元素捕获器",
            bg=t.bg,
            fg=t.text,
            font=t.font_brand,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="DESKTOP ELEMENT CATCHER  ·  LOCAL",
            bg=t.bg,
            fg=t.faint,
            font=t.font_tiny,
            anchor="w",
        ).pack(anchor="w")

        right = tk.Frame(inner, bg=t.bg)
        right.pack(side="right")
        self.more_btn = RoundedButton(
            right,
            t,
            "⋯",
            command=self._show_more_menu,
            kind="ghost",
            width=t.px(40),
            height=t.px(40),
            font=t.font_icon,
            tooltip="更多操作",
        )
        self.more_btn.pack(side="right", padx=(t.px(8), 0))
        self.settings_btn = RoundedButton(
            right,
            t,
            "⚙",
            command=self._open_settings,
            kind="ghost",
            width=t.px(40),
            height=t.px(40),
            font=t.font_icon,
            tooltip="设置（Python 环境等）",
        )
        self.settings_btn.pack(side="right")
        self.capture_btn = RoundedButton(
            right,
            t,
            "⌖  捕获元素  F2",
            command=self.start_picking,
            kind="primary",
            width=t.px(172),
            height=t.px(40),
            font=t.font_small_bold,
            tooltip="隐藏窗口，悬停选择元素；F2 锁定捕获，Esc 取消",
        )
        self.capture_btn.pack(side="right")

        self.uia_pill = Pill(right, t, "UIA 就绪", fg=t.green, bg=t.green_soft, height=t.px(24))
        self.uia_pill.pack(side="right", padx=(0, t.px(8)))
        admin = is_admin()
        self.admin_pill = Pill(
            right,
            t,
            "管理员" if admin else "标准权限",
            fg=t.green if admin else t.amber,
            bg=t.green_soft if admin else t.amber_soft,
            height=t.px(24),
        )
        self.admin_pill.pack(side="right", padx=(0, t.px(8)))
        Tooltip(self.admin_pill, t, "管理员权限可捕获以管理员身份运行的程序")

        tk.Frame(self.root, bg=t.border, height=1).pack(side="top", fill="x")

    def _build_statusbar(self) -> None:
        t = self.theme
        bar = tk.Frame(self.root, bg=t.bg)
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, bg=t.border, height=1).pack(fill="x")
        inner = tk.Frame(bar, bg=t.bg)
        inner.pack(fill="x", padx=t.px(18), pady=t.px(5))
        self.status_dot = tk.Canvas(inner, width=t.px(10), height=t.px(10), bg=t.bg, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, t.px(7)))
        self._dot = self.status_dot.create_oval(1, 1, t.px(9), t.px(9), fill=t.accent, outline="")
        self.status_label = tk.Label(
            inner,
            text="就绪 · 点击“捕获元素”或按 F2 开始",
            bg=t.bg,
            fg=t.muted,
            font=t.font_tiny,
            anchor="w",
        )
        self.status_label.pack(side="left")
        self.status_meta_label = tk.Label(
            inner,
            text="",
            bg=t.bg,
            fg=t.faint,
            font=t.font_tiny,
            anchor="e",
        )
        self.status_meta_label.pack(side="right")
        self._update_status_meta()

    def _build_body(self) -> None:
        t = self.theme
        self.paned = tk.PanedWindow(
            self.root,
            orient="horizontal",
            bg=t.bg,
            bd=0,
            sashwidth=t.px(8),
            sashrelief="flat",
            showhandle=False,
        )
        self.paned.pack(fill="both", expand=True, padx=t.px(16), pady=(t.px(4), t.px(8)))

        self.left = tk.Frame(
            self.paned,
            bg=t.surface,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        self.paned.add(self.left, minsize=t.px(280), width=t.px(330))

        self.right = tk.Frame(
            self.paned,
            bg=t.surface,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        self.paned.add(self.right, minsize=t.px(600))

        self._build_left()
        self._build_right()

    def _build_left(self) -> None:
        t = self.theme
        header = tk.Frame(self.left, bg=t.surface)
        header.pack(fill="x", padx=t.px(14), pady=(t.px(14), t.px(8)))
        title_row = tk.Frame(header, bg=t.surface)
        title_row.pack(fill="x")
        tk.Label(
            title_row,
            text="捕获记录",
            bg=t.surface,
            fg=t.text,
            font=t.font_h2,
            anchor="w",
        ).pack(side="left")
        self.count_pill = Pill(title_row, t, "0", fg=t.accent, bg=t.accent_soft, height=t.px(22))
        self.count_pill.pack(side="right")

        search_box = tk.Frame(
            header,
            bg=t.surface_2,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        search_box.pack(fill="x", pady=(t.px(10), 0))
        tk.Label(
            search_box,
            text="⌕",
            bg=t.surface_2,
            fg=t.faint,
            font=t.font_small,
            padx=t.px(8),
        ).pack(side="left")
        self.search_var = tk.StringVar(value=self._search_placeholder)
        self.search_entry = tk.Entry(
            search_box,
            textvariable=self.search_var,
            bg=t.surface_2,
            fg=t.faint,
            insertbackground=t.accent,
            selectbackground=t.selection,
            selectforeground=t.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=t.font_small,
        )
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=t.px(3))
        self.search_clear = tk.Label(
            search_box,
            text="×",
            bg=t.surface_2,
            fg=t.faint,
            font=t.font_small_bold,
            cursor="hand2",
            padx=t.px(8),
            pady=t.px(2),
        )
        self.search_clear.pack(side="right")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.search_entry.bind("<KeyRelease>", self._on_search_key)
        self.search_entry.bind("<Return>", lambda _e: self._refresh_tree())
        self.search_entry.bind("<Control-a>", self._select_all_search)
        self.search_clear.bind("<Button-1>", lambda _e: self._clear_search())
        self.search_clear.bind("<Enter>", lambda _e: self.search_clear.configure(fg=t.text))
        self.search_clear.bind("<Leave>", lambda _e: self.search_clear.configure(fg=t.faint))

        tree_box = tk.Frame(self.left, bg=t.surface)
        tree_box.pack(fill="both", expand=True, padx=t.px(8))
        self.tree = ttk.Treeview(
            tree_box,
            columns=("type", "name", "time"),
            show="headings",
            style="Catcher.Treeview",
            selectmode="browse",
        )
        self.tree.heading("type", text="类型", anchor="w")
        self.tree.heading("name", text="名称", anchor="w")
        self.tree.heading("time", text="时间", anchor="e")
        self.tree.column("type", width=t.px(64), minwidth=t.px(56), stretch=False, anchor="w")
        self.tree.column("name", width=t.px(188), minwidth=t.px(100), stretch=True, anchor="w")
        self.tree.column("time", width=t.px(46), minwidth=t.px(40), stretch=False, anchor="e")
        tree_scroll = DarkScrollbar(
            tree_box,
            t,
            command=self.tree.yview,
            orient="vertical",
            bg=t.surface,
        )
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background=t.surface)
        self.tree.tag_configure("even", background="#0D1624")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        footer = tk.Frame(self.left, bg=t.surface)
        footer.pack(fill="x", padx=t.px(14), pady=t.px(10))
        self.clear_btn = RoundedButton(
            footer,
            t,
            "清空",
            command=self._clear_all,
            kind="ghost",
            width=t.px(58),
            height=t.px(30),
            font=t.font_tiny_bold,
        )
        self.clear_btn.pack(side="left")
        self.export_btn = RoundedButton(
            footer,
            t,
            "导出 JSON",
            command=self._export_json,
            kind="ghost",
            width=t.px(84),
            height=t.px(30),
            font=t.font_tiny_bold,
        )
        self.export_btn.pack(side="right")

    def _build_right(self) -> None:
        t = self.theme
        self.right.grid_rowconfigure(0, weight=1)
        self.right.grid_columnconfigure(0, weight=1)
        self._build_empty_state()
        self._build_detail()

    def _build_empty_state(self) -> None:
        t = self.theme
        self.empty_frame = tk.Frame(self.right, bg=t.surface)
        self.empty_frame.grid(row=0, column=0, sticky="nsew")
        center = tk.Frame(self.empty_frame, bg=t.surface)
        center.place(relx=0.5, rely=0.46, anchor="center")

        icon = tk.Canvas(center, width=t.px(128), height=t.px(128), bg=t.surface, highlightthickness=0)
        icon.pack(pady=(0, t.px(16)))
        _round_rect(icon, t.px(6), t.px(6), t.px(122), t.px(122), t.px(24), fill=t.surface_2, outline=t.border_light, width=1)
        icon.create_rectangle(
            t.px(28), t.px(28), t.px(100), t.px(100),
            outline=t.border, width=1, dash=(t.px(3), t.px(3)),
        )
        cx = cy = t.px(64)
        icon.create_oval(cx - t.px(25), cy - t.px(25), cx + t.px(25), cy + t.px(25), outline=t.accent, width=t.px(2))
        icon.create_line(cx, t.px(18), cx, cy - t.px(25), fill=t.accent, width=t.px(2))
        icon.create_line(cx, cy + t.px(25), cx, t.px(110), fill=t.accent, width=t.px(2))
        icon.create_line(t.px(18), cy, cx - t.px(25), cy, fill=t.accent, width=t.px(2))
        icon.create_line(cx + t.px(25), cy, t.px(110), cy, fill=t.accent, width=t.px(2))
        icon.create_oval(cx - t.px(4), cy - t.px(4), cx + t.px(4), cy + t.px(4), fill=t.accent, outline="")

        self.empty_title = tk.Label(
            center,
            text="捕获任意桌面元素",
            bg=t.surface,
            fg=t.text,
            font=t.font_title,
        )
        self.empty_title.pack()
        self.empty_subtitle = tk.Label(
            center,
            text="将鼠标悬停在按钮、输入框、菜单等控件上，按 F2 锁定捕获。\n生成的 Python 代码可以直接调用，并能在独立进程中回放校验。",
            bg=t.surface,
            fg=t.muted,
            font=t.font_body,
            justify="center",
            wraplength=t.px(560),
        )
        self.empty_subtitle.pack(pady=(t.px(8), t.px(14)))

        features = tk.Frame(center, bg=t.surface)
        features.pack(pady=(0, t.px(18)))
        for text, fg, bg in (
            ("UI Automation", t.accent, t.accent_soft),
            ("Win32 / WPF / Electron", t.cyan, "#112E45"),
            ("独立进程回放", t.green, t.green_soft),
            ("不抢焦点高亮", t.amber, t.amber_soft),
        ):
            Pill(features, t, text, fg=fg, bg=bg, height=t.px(24)).pack(side="left", padx=t.px(4))

        self.empty_btn = RoundedButton(
            center,
            t,
            "开始捕获  F2",
            command=self.start_picking,
            kind="primary",
            width=t.px(156),
            height=t.px(40),
            font=t.font_small_bold,
        )
        self.empty_btn.pack()
        tk.Label(
            center,
            text="支持多显示器 · 自动 DPI 适配 · 无需注入目标进程",
            bg=t.surface,
            fg=t.faint,
            font=t.font_tiny,
        ).pack(pady=(t.px(12), 0))

    def _build_detail(self) -> None:
        t = self.theme
        self.detail = tk.Frame(self.right, bg=t.surface)
        self.detail.grid(row=0, column=0, sticky="nsew")
        self.detail.grid_remove()
        self.detail.grid_columnconfigure(0, weight=1)
        self.detail.grid_rowconfigure(3, weight=1)

        header = tk.Frame(self.detail, bg=t.surface)
        header.grid(row=0, column=0, sticky="ew", padx=t.px(16), pady=(t.px(14), 0))
        header.grid_columnconfigure(0, weight=1)
        left = tk.Frame(header, bg=t.surface)
        left.grid(row=0, column=0, sticky="nsew")

        title_row = tk.Frame(left, bg=t.surface)
        title_row.pack(fill="x")
        self.type_icon = tk.Canvas(title_row, width=t.px(46), height=t.px(46), bg=t.surface, highlightthickness=0)
        self.type_icon.pack(side="left", padx=(0, t.px(10)))
        name_box = tk.Frame(title_row, bg=t.surface)
        name_box.pack(side="left", fill="x", expand=True)
        self.detail_name = tk.Label(
            name_box,
            text="",
            bg=t.surface,
            fg=t.text,
            font=t.font_h2,
            anchor="w",
            justify="left",
            wraplength=t.px(700),
        )
        self.detail_name.pack(fill="x")
        self.detail_meta = tk.Label(
            name_box,
            text="",
            bg=t.surface,
            fg=t.muted,
            font=t.font_small,
            anchor="w",
            justify="left",
            wraplength=t.px(700),
        )
        self.detail_meta.pack(fill="x", pady=(t.px(3), 0))

        right = tk.Frame(header, bg=t.surface)
        right.grid(row=0, column=1, sticky="ne", padx=(t.px(14), 0))
        thumb_border = tk.Frame(
            right,
            bg=t.surface_2,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
            width=t.px(222),
            height=t.px(126),
        )
        thumb_border.pack()
        thumb_border.pack_propagate(False)
        self.thumb_label = tk.Label(
            thumb_border,
            text="无预览",
            bg=t.surface_2,
            fg=t.faint,
            font=t.font_tiny,
        )
        self.thumb_label.pack(fill="both", expand=True)

        self.header_pills = tk.Frame(header, bg=t.surface)
        self.header_pills.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_action_bar(header)

        tabs_row = tk.Frame(self.detail, bg=t.surface)
        tabs_row.grid(row=1, column=0, sticky="ew", padx=t.px(16), pady=(t.px(10), 0))
        self.tab_control = SegmentedControl(
            tabs_row,
            t,
            [("code", "Python 代码"), ("details", "元素详情")],
            "code",
            self._switch_tab,
        )
        self.tab_control.pack(side="left")
        self.path_count_pill = Pill(tabs_row, t, "0 级", fg=t.muted, bg=t.surface_2, height=t.px(24))
        self.path_count_pill.pack(side="right")

        tk.Frame(self.detail, bg=t.border, height=1).grid(row=2, column=0, sticky="ew", pady=(t.px(10), 0))

        self.tab_container = tk.Frame(self.detail, bg=t.surface)
        self.tab_container.grid(row=3, column=0, sticky="nsew", padx=t.px(16), pady=(t.px(8), t.px(12)))
        self.tab_container.grid_rowconfigure(0, weight=1)
        self.tab_container.grid_columnconfigure(0, weight=1)

        self.code_tab = tk.Frame(self.tab_container, bg=t.surface)
        self.details_tab = tk.Frame(self.tab_container, bg=t.surface)
        for frame in (self.code_tab, self.details_tab):
            frame.grid(row=0, column=0, sticky="nsew")
        self.code_tab.grid_rowconfigure(1, weight=1)
        self.code_tab.grid_columnconfigure(0, weight=1)
        self._build_code_tab()
        self._build_details_tab()
        self.code_tab.tkraise()

    def _build_action_bar(self, parent: tk.Frame) -> None:
        t = self.theme
        bar = tk.Frame(
            parent,
            bg=t.surface_2,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(t.px(8), 0))
        inner = tk.Frame(bar, bg=t.surface_2)
        inner.pack(fill="x", padx=t.px(9), pady=t.px(6))
        tk.Label(
            inner,
            text="元素操作",
            bg=t.surface_2,
            fg=t.faint,
            font=t.font_tiny,
        ).pack(side="left", padx=(0, t.px(8)))

        self.click_btn = RoundedButton(
            inner,
            t,
            "▶  点击",
            command=self._click_current,
            kind="secondary",
            width=t.px(76),
            height=t.px(31),
            font=t.font_tiny_bold,
            tooltip="重新定位元素并点击（Ctrl+1）",
        )
        self.click_btn.pack(side="left", padx=(0, t.px(5)))
        self.input_btn = RoundedButton(
            inner,
            t,
            "⌨  输入",
            command=self._input_current,
            kind="secondary",
            width=t.px(76),
            height=t.px(31),
            font=t.font_tiny_bold,
            tooltip="向输入框/文档控件写入文本（Ctrl+2）",
        )
        self.input_btn.pack(side="left", padx=(0, t.px(5)))
        self.value_btn = RoundedButton(
            inner,
            t,
            "≡  取值",
            command=self._get_value_current,
            kind="secondary",
            width=t.px(78),
            height=t.px(31),
            font=t.font_tiny_bold,
            tooltip="读取当前值（Ctrl+3）",
        )
        self.value_btn.pack(side="left", padx=(0, t.px(5)))

        self.delete_btn = RoundedButton(
            inner,
            t,
            "✕  删除",
            command=self._delete_current,
            kind="danger",
            width=t.px(76),
            height=t.px(31),
            font=t.font_tiny_bold,
        )
        self.delete_btn.pack(side="right")
        self.highlight_btn = RoundedButton(
            inner,
            t,
            "◎  仅高亮",
            command=self._highlight_current,
            kind="ghost",
            width=t.px(88),
            height=t.px(31),
            font=t.font_tiny_bold,
            tooltip="不做任何操作，只显示一次高亮边框",
        )
        self.highlight_btn.pack(side="right", padx=(0, t.px(5)))

    def _set_action_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            getattr(self, "click_btn", None),
            getattr(self, "input_btn", None),
            getattr(self, "value_btn", None),
            getattr(self, "highlight_btn", None),
            getattr(self, "delete_btn", None),
        ):
            if button is not None:
                button.set_enabled(enabled)

    def _build_code_tab(self) -> None:
        t = self.theme
        toolbar = tk.Frame(self.code_tab, bg=t.surface)
        toolbar.grid(row=0, column=0, sticky="ew")
        self.mode_control = SegmentedControl(
            toolbar,
            t,
            [
                ("uiautomation", "uiautomation"),
                ("uiautomation_compact", "uia 精简"),
                ("pywinauto", "pywinauto"),
                ("pywinauto_compact", "pwa 精简"),
                ("pywinauto_relative", "pwa 相对"),
                ("custom", "自定义"),
            ],
            self._current_mode,
            self._set_mode,
        )
        self.mode_control.pack(side="left")
        self.code_file_label = tk.Label(
            toolbar,
            text="locator.py · UTF-8",
            bg=t.surface,
            fg=t.faint,
            font=t.font_tiny,
        )
        self.code_file_label.pack(side="left", padx=(t.px(10), 0))
        self.save_btn = RoundedButton(
            toolbar,
            t,
            "保存 .py",
            command=self._save_code,
            kind="ghost",
            width=t.px(78),
            height=t.px(30),
            font=t.font_tiny_bold,
        )
        self.save_btn.pack(side="right")
        self.copy_btn = RoundedButton(
            toolbar,
            t,
            "复制代码",
            command=self._copy_code,
            kind="ghost",
            width=t.px(76),
            height=t.px(30),
            font=t.font_tiny_bold,
        )
        self.copy_btn.pack(side="right", padx=(0, t.px(4)))

        self.code_viewer = CodeViewer(self.code_tab, t)
        self.code_viewer.grid(row=1, column=0, sticky="nsew", pady=(t.px(8), t.px(8)))
        self._build_custom_tab()

        self.verify_bar = tk.Frame(
            self.code_tab,
            bg=t.surface_2,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        self.verify_bar.grid(row=2, column=0, sticky="ew")
        self.verify_bar.grid_columnconfigure(0, weight=1)

        action_row = tk.Frame(self.verify_bar, bg=t.surface_2)
        action_row.pack(fill="x", padx=t.px(10), pady=(t.px(9), t.px(5)))
        self.verify_btn = RoundedButton(
            action_row,
            t,
            "✓  验证并高亮",
            command=self._verify_current,
            kind="primary",
            width=t.px(148),
            height=t.px(36),
            font=t.font_small_bold,
        )
        self.verify_btn.pack(side="left")
        self.verify_progress = ttk.Progressbar(
            action_row,
            mode="indeterminate",
            length=t.px(110),
            style="Catcher.Horizontal.TProgressbar",
        )
        self.verify_result_label = tk.Label(
            action_row,
            text="尚未校验",
            bg=t.surface_2,
            fg=t.muted,
            font=t.font_small_bold,
            anchor="w",
        )
        self.verify_result_label.pack(side="left", padx=(t.px(12), 0))
        self.verify_hint = tk.Label(
            action_row,
            text="Ctrl+Enter · 独立进程回放",
            bg=t.surface_2,
            fg=t.faint,
            font=t.font_tiny,
        )
        self.verify_hint.pack(side="right")

        self.checks_frame = tk.Frame(self.verify_bar, bg=t.surface_2)
        self.checks_frame.pack(fill="x", padx=t.px(10), pady=(0, t.px(9)))
        self._show_checks_hint()

        self.verify_error_box = tk.Text(
            self.verify_bar,
            height=4,
            bg=t.red_soft,
            fg=t.red,
            font=t.font_tiny,
            wrap="word",
            bd=0,
            highlightthickness=0,
            padx=t.px(8),
            pady=t.px(6),
            state="disabled",
        )

    def _build_custom_tab(self) -> None:
        t = self.theme
        self.custom_frame = tk.Frame(self.code_tab, bg=t.surface)
        self.custom_frame.grid(row=1, column=0, rowspan=2, sticky="nsew", pady=(t.px(8), 0))
        self.custom_frame.grid_remove()
        self.custom_frame.grid_rowconfigure(1, weight=3)
        self.custom_frame.grid_rowconfigure(3, weight=2)
        self.custom_frame.grid_columnconfigure(0, weight=1)

        top = tk.Frame(self.custom_frame, bg=t.surface)
        top.grid(row=0, column=0, sticky="ew", pady=(0, t.px(6)))
        tk.Label(
            top,
            text="自定义测试代码 · 自动保存 · 用设置里的解释器在独立进程中运行",
            bg=t.surface,
            fg=t.faint,
            font=t.font_tiny,
        ).pack(side="left")
        self.custom_run_btn = RoundedButton(
            top,
            t,
            "▶  运行  F5",
            command=self._run_custom_code,
            kind="primary",
            width=t.px(104),
            height=t.px(32),
            font=t.font_small_bold,
        )
        self.custom_run_btn.pack(side="right")

        editor_wrap = tk.Frame(
            self.custom_frame,
            bg=t.code_bg,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        editor_wrap.grid(row=1, column=0, sticky="nsew")
        self.custom_editor = CodeViewer(
            editor_wrap,
            t,
            editable=True,
            on_change=self._on_custom_code_changed,
        )
        self.custom_editor.pack(fill="both", expand=True)
        self.custom_editor.set_code(self._load_custom_code())

        tk.Label(
            self.custom_frame,
            text="运行输出",
            bg=t.surface,
            fg=t.faint,
            font=t.font_tiny,
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", pady=(t.px(6), t.px(2)))

        out_wrap = tk.Frame(
            self.custom_frame,
            bg=t.code_bg,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        out_wrap.grid(row=3, column=0, sticky="nsew")
        out_wrap.grid_columnconfigure(0, weight=1)
        out_wrap.grid_rowconfigure(0, weight=1)
        self.custom_output = tk.Text(
            out_wrap,
            bg=t.code_bg,
            fg=t.code_text,
            selectbackground=t.selection,
            selectforeground=t.text,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=t.font_code_small,
            wrap="none",
            state="disabled",
            padx=t.px(8),
            pady=t.px(6),
        )
        self.custom_output.grid(row=0, column=0, sticky="nsew")
        self.custom_output.tag_configure("footer", foreground=t.faint)
        self.custom_output.tag_configure("ok", foreground=t.green)
        self.custom_output.tag_configure("err", foreground=t.red)
        out_vbar = DarkScrollbar(
            out_wrap,
            t,
            command=self.custom_output.yview,
            orient="vertical",
            bg=t.code_bg,
        )
        out_vbar.grid(row=0, column=1, sticky="ns")
        self.custom_output.configure(yscrollcommand=out_vbar.set)

    def _load_custom_code(self) -> str:
        try:
            if CUSTOM_CODE_FILE.exists():
                return CUSTOM_CODE_FILE.read_text(encoding="utf-8")
        except Exception:
            self.logger.exception("读取自定义代码失败")
        return ""

    def _on_custom_code_changed(self) -> None:
        if self._custom_save_job is not None:
            try:
                self.root.after_cancel(self._custom_save_job)
            except Exception:
                pass
        self._custom_save_job = self.root.after(600, self._save_custom_code)

    def _save_custom_code(self) -> None:
        self._custom_save_job = None
        try:
            CUSTOM_CODE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CUSTOM_CODE_FILE.write_text(self.custom_editor.get_code(), encoding="utf-8")
        except Exception:
            self.logger.exception("保存自定义代码失败")

    def _run_custom_code(self) -> None:
        if self._closing or self._custom_running or self._picking or self._capturing:
            return
        if self._verify_running or self._action_running:
            return
        code = self.custom_editor.get_code()
        if not code.strip():
            self._toast("先在编辑器里写点代码再运行", "info")
            return
        self._save_custom_code()
        self._custom_running = True
        self.custom_run_btn.set_enabled(False)
        self.custom_run_btn.set_text("运行中…")
        self._set_status("正在运行自定义代码…", "info")
        self._append_custom_output(f"—— 运行 #{self._custom_run_count + 1} ——", "footer")
        threading.Thread(
            target=self._custom_run_thread,
            args=(code,),
            name="custom-run",
            daemon=True,
        ).start()

    def _custom_run_thread(self, code: str) -> None:
        started = time.perf_counter()
        temp_dir = None
        try:
            exe = self.settings.resolved_python()
            if not exe:
                self._events.put((
                    "custom_run_error",
                    "exe 模式下需要单独的 Python 来运行代码：请点右上角 ⚙ 设置，指定一个已安装 uiautomation 和 pywinauto 的 python.exe。",
                    time.perf_counter() - started,
                ))
                return
            import tempfile

            temp_dir = Path(tempfile.mkdtemp(prefix="element_catcher_run_"))
            script = temp_dir / "custom_run.py"
            script.write_text(code, encoding="utf-8")
            env = os.environ.copy()
            env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
            proc = subprocess.run(
                [exe, str(script)],
                cwd=str(APP_DIR),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            duration = time.perf_counter() - started
            output = (proc.stdout or "") + (proc.stderr or "")
            self._events.put(("custom_run_done", output, proc.returncode, duration))
        except subprocess.TimeoutExpired:
            self._events.put(("custom_run_error", "运行超时（120 秒），已终止。", time.perf_counter() - started))
        except Exception as exc:
            self._events.put(("custom_run_error", f"无法启动运行进程：{exc}", time.perf_counter() - started))
        except BaseException as exc:
            self.logger.exception("自定义运行线程异常")
            self._events.put(("custom_run_error", f"运行线程异常：{exc}", time.perf_counter() - started))
        finally:
            if temp_dir:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)

    def _append_custom_output(self, text: str, tag: str = "") -> None:
        try:
            self.custom_output.configure(state="normal")
            self.custom_output.insert("end", text, (tag,) if tag else ())
            self.custom_output.see("end")
            content = self.custom_output.get("1.0", "end")
            if len(content) > 60000:
                self.custom_output.delete("1.0", f"{len(content) - 40000}c")
            self.custom_output.configure(state="disabled")
        except Exception:
            pass

    def _on_custom_run_done(self, output: str, returncode: int, duration: float) -> None:
        self._custom_running = False
        self.custom_run_btn.set_enabled(True)
        self.custom_run_btn.set_text("▶  运行  F5")
        self._custom_run_count += 1
        if output:
            self._append_custom_output(output if output.endswith(chr(10)) else output + chr(10))
        self._append_custom_output(f"[退出码 {returncode} · {duration:.2f}s]", "ok" if returncode == 0 else "err")
        self._append_custom_output(chr(10))
        if returncode == 0:
            self._set_status(f"自定义代码运行完成 · {duration:.2f}s", "success")
        else:
            self._set_status(f"自定义代码运行失败 · 退出码 {returncode}", "error")

    def _on_custom_run_error(self, message: str, duration: float = 0.0) -> None:
        self._custom_running = False
        self.custom_run_btn.set_enabled(True)
        self.custom_run_btn.set_text("▶  运行  F5")
        self._append_custom_output(f"{message} · {duration:.2f}s" + chr(10), "err")
        self._set_status("自定义代码运行出错", "error")
        self.logger.warning("自定义代码运行失败: %s", message)

    def _build_details_tab(self) -> None:
        t = self.theme
        self.details_scroll = ScrollableFrame(self.details_tab, t, bg=t.surface)
        self.details_scroll.pack(fill="both", expand=True)
        self.details_inner = self.details_scroll.inner

    # ------------------------------------------------------------------
    # 事件与循环
    # ------------------------------------------------------------------
    def _bind_events(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<F2>", lambda _e: self.start_picking())
        self.root.bind("<Control-Return>", lambda _e: self._on_ctrl_enter())
        self.root.bind("<Control-f>", lambda _e: self._focus_search())
        self.root.bind("<Control-Key-1>", lambda _e: self._click_current())
        self.root.bind("<Control-Key-2>", lambda _e: self._input_current())
        self.root.bind("<Control-Key-3>", lambda _e: self._get_value_current())
        self.root.bind("<F5>", lambda _e: self._run_custom_code() if self._current_mode == "custom" else None)
        self.root.bind("<Escape>", self._on_escape)

    def _schedule_loops(self) -> None:
        self.root.after(35, self._poll_events)
        self.root.after(25, self._poll_keys)
        self.root.after(30, self._poll_cursor)

    def _poll_events(self) -> None:
        if self._closing:
            return
        try:
            for _ in range(60):
                event = self._events.get_nowait()
                kind = event[0]
                if kind == "hover":
                    _, info, seq = event
                    if self._picking and not self._capturing and seq >= self._applied_hover_seq:
                        self._applied_hover_seq = seq
                        if info is not None:
                            self.overlay.show(info.rect, info)
                elif kind == "captured":
                    self._on_captured(event[1])
                elif kind == "capture_error":
                    self._on_capture_error(event[1])
                elif kind == "verify_done":
                    _, result, capture_id, mode, generation = event
                    self._on_verify_done(result, capture_id, mode, generation)
                elif kind == "action_done":
                    _, action_kind, message = event
                    self._on_action_done(action_kind, message)
                elif kind == "action_error":
                    _, action_kind, message, hint = event
                    self._on_action_error(action_kind, message, hint)
                elif kind == "action_value":
                    _, action_kind, value, source = event
                    self._on_action_value(action_kind, value, source)
                elif kind == "custom_run_done":
                    _, output, returncode, duration = event
                    self._on_custom_run_done(output, returncode, duration)
                elif kind == "custom_run_error":
                    _, message, duration = event
                    self._on_custom_run_error(message, duration)
        except queue.Empty:
            pass
        except Exception:
            self.logger.exception("处理事件失败")
        if not self._closing:
            self.root.after(35, self._poll_events)

    def _poll_keys(self) -> None:
        if self._closing:
            return
        if self._picking:
            f2 = _key_down(VK_F2)
            esc = _key_down(VK_ESCAPE)
            if f2 and not self._prev_f2:
                self._capture_now()
            if esc and not self._prev_esc:
                self._cancel_picking()
            self._prev_f2 = f2
            self._prev_esc = esc
        else:
            self._prev_f2 = False
            self._prev_esc = False
        self.root.after(25, self._poll_keys)

    def _poll_cursor(self) -> None:
        if self._closing:
            return
        if self._picking and not self._capturing:
            x, y = get_cursor_pos()
            now = time.monotonic()
            moved = (x, y) != self._last_cursor
            if moved or now - self._last_hover_query >= 0.6:
                self._request_hover()
        self.root.after(30, self._poll_cursor)

    def _request_hover(self, force: bool = False) -> None:
        if not self._picking or self._capturing:
            return
        x, y = get_cursor_pos()
        now = time.monotonic()
        if not force and (x, y) == self._last_cursor and now - self._last_hover_query < 0.55:
            return
        if now - self._last_hover_query < 0.045:
            return
        self._last_cursor = (x, y)
        self._last_hover_query = now
        self._hover_seq += 1
        self._picker.hover(x, y, self._hover_seq)

    # ------------------------------------------------------------------
    # 捕获流程
    # ------------------------------------------------------------------
    def start_picking(self) -> None:
        if self._closing or self._picking or self._capturing or self._action_running or self._custom_running:
            return
        try:
            self.overlay.hide()
            self._restore_state = self.root.state()
            self._picking = True
            self._capturing = False
            self._prev_f2 = True
            self._prev_esc = False
            self._last_cursor = get_cursor_pos()
            self._last_hover_query = 0.0
            self._hover_seq = 0
            self._applied_hover_seq = -1
            self.root.withdraw()
            self._set_status("捕获模式：移动鼠标选择元素，F2 锁定，Esc 取消", "info")
            self.root.after(90, lambda: self._request_hover(force=True))
            self.logger.info("进入捕获模式")
        except Exception:
            self.logger.exception("进入捕获模式失败")
            self._picking = False
            self._restore_window()
            self._toast("进入捕获模式失败，请重试", "error")

    def _capture_now(self) -> None:
        if not self._picking or self._capturing:
            return
        x, y = get_cursor_pos()
        self._picking = False
        self._capturing = True
        self.overlay.hide()
        self._set_status("正在读取元素并生成代码…", "info")
        self._capture_timeout_job = self.root.after(12000, self._capture_timeout)
        self._picker.capture(x, y)
        self.logger.info("请求捕获 (%d, %d)", x, y)

    def _capture_timeout(self) -> None:
        self._capture_timeout_job = None
        if not self._capturing:
            return
        self._capturing = False
        self._restore_window()
        self._set_status("捕获超时", "error")
        messagebox.showwarning(
            "捕获超时",
            "目标程序可能无响应，或 UI Automation 调用被阻塞。\n请稍后重试；若目标程序以管理员身份运行，请使用管理员权限重启捕获器。",
            parent=self.root,
        )

    def _on_captured(self, capture: ElementCapture) -> None:
        if not self._capturing:
            # 超时后的迟到结果，清理缩略图
            try:
                if capture.screenshot:
                    (DATA_DIR / capture.screenshot).unlink(missing_ok=True)
            except Exception:
                pass
            return
        self._capturing = False
        if self._capture_timeout_job is not None:
            try:
                self.root.after_cancel(self._capture_timeout_job)
            except Exception:
                pass
            self._capture_timeout_job = None
        self._restore_window()
        self.captures.insert(0, capture)
        if not self.store.save(self.captures):
            self._toast(self.store.last_error or "保存捕获记录失败", "error")
        self._current_id = capture.id
        self._refresh_tree()
        self._set_status(f"已捕获 {capture.type_label} · {capture.display_name}", "success")
        self._toast(f"已捕获 {capture.type_label}：{capture.display_name}", "success")
        self.logger.info(
            "捕获成功: %s %r pid=%s rect=%s steps=%d",
            capture.control_type_name,
            capture.name,
            capture.process_id,
            capture.rect,
            len(capture.steps),
        )

    def _on_capture_error(self, exc: CaptureError) -> None:
        if not self._capturing:
            return
        self._capturing = False
        if self._capture_timeout_job is not None:
            try:
                self.root.after_cancel(self._capture_timeout_job)
            except Exception:
                pass
            self._capture_timeout_job = None
        self._restore_window()
        self._set_status("捕获失败", "error")
        message = str(exc)
        hint = getattr(exc, "hint", "")
        if hint:
            message += "\n\n" + hint
        self.logger.warning("捕获失败: %s | hint=%s", exc, hint)
        messagebox.showerror("捕获失败", message, parent=self.root)
        if hint and "管理员" in hint and not is_admin():
            if messagebox.askyesno(
                "权限不足",
                "是否以管理员身份重启捕获器？",
                parent=self.root,
            ):
                self._restart_admin()

    def _cancel_picking(self) -> None:
        if not self._picking:
            return
        self._picking = False
        self._capturing = False
        self.overlay.hide()
        self._restore_window()
        self._set_status("已取消捕获", "info")
        self._toast("已取消捕获", "info")
        self.logger.info("用户取消捕获")

    def _restore_window(self) -> None:
        try:
            self.root.deiconify()
            if self._restore_state == "zoomed":
                self.root.state("zoomed")
            else:
                self.root.state("normal")
            self.root.lift()
            self.root.after(60, self._focus_root)
        except Exception:
            self.logger.exception("恢复窗口失败")

    def _focus_root(self) -> None:
        if self._closing:
            return
        try:
            self.root.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 记录列表与详情
    # ------------------------------------------------------------------
    def _find_capture(self, capture_id: str) -> Optional[ElementCapture]:
        for capture in self.captures:
            if capture.id == capture_id:
                return capture
        return None

    def _query(self) -> str:
        if self._search_active:
            return ""
        return self.search_var.get().strip()

    def _refresh_tree(self, select_id: Optional[str] = None) -> None:
        query = self._query().lower()
        if query:
            self._filtered = [
                c
                for c in self.captures
                if query in c.name.lower()
                or query in c.automation_id.lower()
                or query in c.class_name.lower()
                or query in c.type_label.lower()
                or query in c.control_type_name.lower()
                or query in c.process_name.lower()
                or query in c.window_title.lower()
            ]
        else:
            self._filtered = list(self.captures)

        self.count_pill.set(
            str(len(self.captures)) if not query else f"{len(self._filtered)}/{len(self.captures)}"
        )
        self._suppress_select = True
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, capture in enumerate(self._filtered):
            name = capture.display_name.replace("\n", " ")
            if len(name) > 34:
                name = name[:33] + "…"
            self.tree.insert(
                "",
                "end",
                iid=capture.id,
                values=(capture.type_label, name, capture.time_label),
                tags=("even" if index % 2 == 0 else "odd",),
            )
        self._suppress_select = False

        if self._filtered:
            target_id = select_id or self._current_id
            if target_id not in {c.id for c in self._filtered}:
                target_id = self._filtered[0].id
            self.tree.selection_set(target_id)
            self.tree.see(target_id)
            self._on_tree_select()
        else:
            self._current = None
            self._current_id = ""
            if self.captures:
                self._show_empty("没有匹配的捕获记录")
            else:
                self._show_empty(None)

    def _on_tree_select(self, _event=None) -> None:
        if self._suppress_select:
            return
        selection = self.tree.selection()
        if not selection:
            return
        capture = self._find_capture(selection[0])
        if capture is not None:
            self._show_capture(capture)

    def _show_capture(self, capture: ElementCapture) -> None:
        self._current = capture
        self._current_id = capture.id
        self.empty_frame.grid_remove()
        self.detail.grid()
        self.detail_name.configure(text=capture.display_name)
        window_title = capture.window_title.replace("\n", " ")
        if len(window_title) > 70:
            window_title = window_title[:69] + "…"
        meta = f"{capture.process_name or '未知进程'} · PID {capture.process_id}"
        if window_title:
            meta += f"  ·  {window_title}"
        self.detail_meta.configure(text=meta)
        self._set_type_icon(capture)
        self._update_header_pills(capture)
        self._load_thumbnail(capture)
        self.path_count_pill.set(f"{len(capture.steps)} 级" if capture.steps else "根节点")
        self._render_details(capture)
        self._update_code()
        self._reset_verify()
        self.overlay.hide()

    def _show_empty(self, message: Optional[str]) -> None:
        self.detail.grid_remove()
        self.empty_frame.grid()
        if message:
            self.empty_title.configure(text=message)
            self.empty_subtitle.configure(
                text="换个关键词试试，或点击搜索框右侧的 × 清空筛选。\n也可以按 F2 重新捕获一个元素。"
            )
        elif self.captures:
            self.empty_title.configure(text="选择左侧记录查看代码")
            self.empty_subtitle.configure(
                text="捕获记录已保存在本地，重新打开捕获器仍然可用。\n选择一条记录即可查看 Python 代码并校验高亮。"
            )
        else:
            self.empty_title.configure(text="捕获任意桌面元素")
            self.empty_subtitle.configure(
                text="将鼠标悬停在按钮、输入框、菜单等控件上，按 F2 锁定捕获。\n生成的 Python 代码可以直接调用，并能在独立进程中回放校验。"
            )

    def _set_type_icon(self, capture: ElementCapture) -> None:
        t = self.theme
        self.type_icon.delete("all")
        _round_rect(
            self.type_icon,
            1,
            1,
            t.px(45),
            t.px(45),
            t.px(12),
            fill=t.accent_soft,
            outline=t.border_light,
            width=1,
        )
        glyph = TYPE_GLYPHS.get(capture.control_type_name, "◇")
        self.type_icon.create_text(
            t.px(23),
            t.px(23),
            text=glyph,
            fill=t.accent,
            font=t.font_icon_large,
        )

    def _update_header_pills(self, capture: ElementCapture) -> None:
        t = self.theme
        for child in self.header_pills.winfo_children():
            child.destroy()
        items: List[Tuple[str, str, str, str]] = []
        if capture.automation_id:
            items.append(
                (f"AID  {self._truncate(capture.automation_id, 30)}", t.accent, t.accent_soft, capture.automation_id)
            )
        if capture.class_name:
            items.append(
                (f"Class  {self._truncate(capture.class_name, 30)}", t.muted, t.surface_2, capture.class_name)
            )
        if capture.framework_id:
            items.append((capture.framework_id, t.cyan, "#112E45", f"FrameworkId: {capture.framework_id}"))
        items.append((f"{capture.width} × {capture.height}", t.muted, t.surface_2, str(capture.rect)))
        if capture.is_password:
            items.append(("密码框", t.amber, t.amber_soft, "该控件是密码输入框"))
        if capture.is_offscreen:
            items.append(("离屏", t.red, t.red_soft, "该控件当前不在屏幕可见区域"))
        for text, fg, bg, tip in items:
            pill = Pill(self.header_pills, t, text, fg=fg, bg=bg, height=t.px(23))
            pill.pack(side="left", padx=(0, t.px(6)), pady=(t.px(7), 0))
            if tip:
                Tooltip(pill, t, tip)

    def _load_thumbnail(self, capture: ElementCapture) -> None:
        self._thumb_photo = None
        path = self.store.thumb_path(capture)
        if path is None:
            self.thumb_label.configure(image="", text="无预览", fg=self.theme.faint)
            return
        try:
            image = Image.open(path).convert("RGBA")
            image.thumbnail((self.theme.px(220), self.theme.px(124)), Image.Resampling.LANCZOS)
            self._thumb_photo = ImageTk.PhotoImage(image)
            self.thumb_label.configure(image=self._thumb_photo, text="")
        except Exception:
            self.logger.exception("加载缩略图失败")
            self.thumb_label.configure(image="", text="预览加载失败", fg=self.theme.faint)

    def _switch_tab(self, key: str) -> None:
        self._active_tab = key
        if key == "details":
            self.details_tab.tkraise()
        else:
            self.code_tab.tkraise()

    def _render_details(self, capture: ElementCapture) -> None:
        t = self.theme
        for child in self.details_inner.winfo_children():
            child.destroy()

        section = self._section("元素属性")
        rows = [
            ("控件类型", f"{capture.control_type_name} · {capture.type_label}"),
            ("名称", capture.name),
            ("AutomationId", capture.automation_id),
            ("ClassName", capture.class_name),
            ("FrameworkId", capture.framework_id),
            ("矩形", f"({capture.rect[0]}, {capture.rect[1]}) → ({capture.rect[2]}, {capture.rect[3]})    {capture.width} × {capture.height}"),
            ("中心点", f"({capture.center[0]}, {capture.center[1]})"),
            (
                "状态",
                "可用" if capture.is_enabled else "禁用"
                + (" · 离屏" if capture.is_offscreen else "")
                + (" · 密码框" if capture.is_password else ""),
            ),
        ]
        if capture.value_preview:
            rows.append(("值预览", capture.value_preview))
        if capture.help_text:
            rows.append(("帮助文本", capture.help_text))
        if capture.accelerator_key:
            rows.append(("快捷键", capture.accelerator_key))
        if capture.access_key:
            rows.append(("访问键", capture.access_key))
        if capture.item_status:
            rows.append(("ItemStatus", capture.item_status))
        if capture.item_type:
            rows.append(("ItemType", capture.item_type))
        if capture.runtime_id:
            rows.append(("Runtime ID", ", ".join(str(v) for v in capture.runtime_id)))
        rows.append(("捕获时间", capture.date_label))
        for index, (key, value) in enumerate(rows):
            self._add_property(section, key, value, index)

        path_section = self._section("定位路径")
        if not capture.steps:
            tk.Label(
                path_section,
                text="捕获的是桌面根节点，代码直接返回 auto.GetRootControl()。",
                bg=t.surface,
                fg=t.muted,
                font=t.font_small,
                anchor="w",
            ).pack(fill="x")
        else:
            for index, step in enumerate(capture.steps, start=1):
                self._add_path_step(path_section, step, index)

        window_section = self._section("窗口与进程")
        window_rows = [
            ("进程", f"{capture.process_name or '未知'} (PID {capture.process_id})"),
            ("进程路径", capture.process_exe),
            ("窗口标题", capture.window_title),
            ("窗口类名", capture.window_class),
            ("原生句柄", hex(capture.window_handle) if capture.window_handle else ""),
        ]
        for index, (key, value) in enumerate(window_rows):
            self._add_property(window_section, key, value, index)

        self.details_inner.update_idletasks()
        self.details_scroll.canvas.configure(scrollregion=self.details_scroll.canvas.bbox("all"))
        self.details_scroll.canvas.yview_moveto(0)

    def _section(self, title: str) -> tk.Frame:
        t = self.theme
        section = tk.Frame(self.details_inner, bg=t.surface)
        section.pack(fill="x", pady=(0, t.px(14)))
        header = tk.Frame(section, bg=t.surface)
        header.pack(fill="x", pady=(0, t.px(6)))
        tk.Frame(header, bg=t.accent, width=t.px(3), height=t.px(14)).pack(side="left", padx=(0, t.px(8)))
        tk.Label(
            header,
            text=title,
            bg=t.surface,
            fg=t.text,
            font=t.font_small_bold,
            anchor="w",
        ).pack(side="left")
        return section

    def _add_property(self, parent: tk.Frame, key: str, value: str, index: int) -> None:
        t = self.theme
        bg = t.surface if index % 2 == 0 else "#0D1624"
        row = tk.Frame(parent, bg=bg)
        row.pack(fill="x")
        row.grid_columnconfigure(0, minsize=t.px(118))
        row.grid_columnconfigure(1, weight=1)
        key_label = tk.Label(
            row,
            text=key,
            bg=bg,
            fg=t.faint,
            font=t.font_small,
            anchor="nw",
            padx=t.px(8),
            pady=t.px(5),
        )
        key_label.grid(row=0, column=0, sticky="nw")
        display = value if value not in (None, "") else "—"
        value_label = tk.Label(
            row,
            text=display,
            bg=bg,
            fg=t.text if value else t.faint,
            font=t.font_small,
            anchor="nw",
            justify="left",
            wraplength=t.px(720),
            padx=t.px(8),
            pady=t.px(5),
        )
        value_label.grid(row=0, column=1, sticky="nw")

        if value:
            menu = tk.Menu(self.root, tearoff=0)
            menu.add_command(label="复制值", command=lambda v=value: self._copy_value(v))
            for widget in (key_label, value_label):
                widget.bind("<Button-3>", lambda e, m=menu: m.tk_popup(e.x_root, e.y_root))

    def _add_path_step(self, parent: tk.Frame, step, index: int) -> None:
        t = self.theme
        card = tk.Frame(
            parent,
            bg=t.surface_2,
            highlightbackground=t.border,
            highlightthickness=1,
            bd=0,
        )
        card.pack(fill="x", pady=(0, t.px(6)))
        top = tk.Frame(card, bg=t.surface_2)
        top.pack(fill="x", padx=t.px(9), pady=(t.px(7), t.px(2)))
        Pill(top, t, str(index), fg=t.accent, bg=t.accent_soft, height=t.px(20), padx=t.px(7)).pack(side="left")
        tk.Label(
            top,
            text=step.control_type_name,
            bg=t.surface_2,
            fg=t.text,
            font=t.font_small_bold,
        ).pack(side="left", padx=(t.px(7), t.px(6)))
        display = step.name or step.automation_id or step.class_name or ""
        if display:
            tk.Label(
                top,
                text=self._truncate(display, 46),
                bg=t.surface_2,
                fg=t.muted,
                font=t.font_small,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
        if step.is_top_level:
            Pill(top, t, "顶层", fg=t.cyan, bg="#112E45", height=t.px(20), padx=t.px(7)).pack(side="right")

        chips = tk.Frame(card, bg=t.surface_2)
        chips.pack(fill="x", padx=t.px(9), pady=(0, t.px(7)))
        chip_items: List[Tuple[str, str, str]] = []
        if step.automation_id:
            chip_items.append((f"AutomationId: {self._truncate(step.automation_id, 28)}", t.accent, t.accent_soft))
        if step.class_name:
            chip_items.append((f"Class: {self._truncate(step.class_name, 28)}", t.muted, t.surface_3))
        if step.name:
            chip_items.append((f"Name: {self._truncate(step.name, 28)}", t.muted, t.surface_3))
        if step.match_count > 1:
            chip_items.append((f"{step.match_count} 个匹配 → 第 {step.found_index} 个", t.amber, t.amber_soft))
        if step.fallback:
            chip_items.append(("标题变化 → ClassName 兜底", t.faint, t.surface_3))
        for text, fg, bg in chip_items:
            Pill(chips, t, text, fg=fg, bg=bg, height=t.px(21), padx=t.px(7), font=t.font_tiny).pack(
                side="left", padx=(0, t.px(5)), pady=(t.px(3), 0)
            )

    def _truncate(self, text: str, limit: int) -> str:
        text = (text or "").replace("\n", " ")
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _copy_value(self, value: str) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self._toast("已复制", "success")
        except Exception:
            self.logger.exception("复制失败")

    # ------------------------------------------------------------------
    # 代码与校验
    # ------------------------------------------------------------------
    def _code_for_mode(self) -> str:
        capture = self._current
        if capture is None:
            return ""
        return {
            "uiautomation": capture.uia_code,
            "pywinauto": capture.pywinauto_code,
            "uiautomation_compact": capture.uia_compact_code,
            "pywinauto_compact": capture.pywinauto_compact_code,
            "pywinauto_relative": capture.pwa_rel_code,
        }.get(self._current_mode, capture.uia_code)

    def _update_code(self) -> None:
        if self._current_mode == "custom":
            self.custom_frame.grid()
            self.code_viewer.grid_remove()
            self.verify_bar.grid_remove()
            self.mode_control.set_active("custom")
            self.code_file_label.configure(text="custom.py · 可编辑 · 独立进程运行")
            return
        self.custom_frame.grid_remove()
        self.code_viewer.grid(row=1, column=0, sticky="nsew", pady=(self.theme.px(8), self.theme.px(8)))
        self.verify_bar.grid(row=2, column=0, sticky="ew")
        if self._current is None:
            return
        code = self._code_for_mode()
        self.code_viewer.set_code(code or "")
        if self._current_mode.endswith("_compact"):
            variant = "精简"
        elif self._current_mode == "pywinauto_relative":
            variant = "相对"
        else:
            variant = "完整"
        self.code_file_label.configure(text=f"locator.py · UTF-8 · {self._current_mode} · {variant}")
        self.mode_control.set_active(self._current_mode)

    def _set_mode(self, mode: str) -> None:
        if mode == self._current_mode:
            return
        self._current_mode = mode
        self._update_code()
        self._reset_verify()

    def _copy_code(self) -> None:
        code = self.custom_editor.get_code() if self._current_mode == "custom" else self.code_viewer.get_code()
        if not code:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self._toast("代码已复制到剪贴板", "success")
            self._set_status("代码已复制", "success")
        except Exception:
            self.logger.exception("复制代码失败")
            self._toast("复制失败", "error")

    def _save_code(self) -> None:
        if self._current_mode == "custom":
            code = self.custom_editor.get_code()
            default = "custom_code.py"
        elif self._current is not None:
            code = self.code_viewer.get_code()
            default = f"locate_{self._current.type_short.lower()}_{self._current.id[-6:]}.py"
        else:
            return
        if not code:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="保存 Python 代码",
            defaultextension=".py",
            initialfile=default,
            filetypes=[("Python 文件", "*.py"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(code, encoding="utf-8")
            self._toast("代码已保存", "success")
            self._set_status(f"已保存到 {path}", "success")
        except Exception as exc:
            self.logger.exception("保存代码失败")
            messagebox.showerror("保存失败", str(exc), parent=self.root)

    def _reset_verify(self) -> None:
        self._verify_generation += 1
        self._verify_running = False
        self._verify_result = None
        self.verify_btn.set_enabled(True)
        self.verify_progress.stop()
        self.verify_progress.pack_forget()
        self.verify_result_label.configure(text="尚未校验", fg=self.theme.muted)
        self._clear_checks()
        self._show_checks_hint()
        self._hide_verify_error()

    def _show_checks_hint(self) -> None:
        for child in self.checks_frame.winfo_children():
            child.destroy()
        tk.Label(
            self.checks_frame,
            text="校验会在独立 Python 进程中回放当前代码，确认可重新定位后高亮元素。",
            bg=self.theme.surface_2,
            fg=self.theme.faint,
            font=self.theme.font_tiny,
            anchor="w",
        ).pack(side="left")

    def _clear_checks(self) -> None:
        for child in self.checks_frame.winfo_children():
            child.destroy()

    def _on_ctrl_enter(self) -> None:
        if self._current_mode == "custom":
            self._run_custom_code()
        else:
            self._verify_current()

    def _verify_current(self) -> None:
        if self._current is None or self._verify_running or self._picking or self._capturing or self._action_running or self._custom_running:
            return
        capture = self._current
        mode = self._current_mode
        code = self._code_for_mode()
        if not code.strip():
            messagebox.showwarning("没有代码", "当前模式没有生成可执行代码。", parent=self.root)
            return
        self.overlay.hide()
        self._verify_generation += 1
        generation = self._verify_generation
        self._verify_running = True
        self.verify_btn.set_enabled(False)
        self.verify_result_label.configure(text="正在独立进程中回放…", fg=self.theme.muted)
        self._clear_checks()
        self._hide_verify_error()
        self.verify_progress.pack(side="left", padx=(self.theme.px(12), 0))
        self.verify_progress.start(12)
        self._set_status("正在验证生成的代码…", "info")
        thread = threading.Thread(
            target=self._verify_thread,
            args=(capture, mode, generation),
            name="verify-worker",
            daemon=True,
        )
        thread.start()

    def _verify_thread(self, capture: ElementCapture, mode: str, generation: int) -> None:
        python_exe = self.settings.resolved_python()
        try:
            result = run_verification(capture, mode, python_exe=python_exe)
        except Exception as exc:
            self.logger.exception("验证线程异常")
            result = VerifyResult(
                ok=False,
                checks=[CheckResult("playback", "代码回放", "fail", str(exc))],
                error=f"{type(exc).__name__}: {exc}",
                mode=mode,
            )
        self._events.put(("verify_done", result, capture.id, mode, generation))

    def _on_verify_done(self, result: VerifyResult, capture_id: str, mode: str, generation: int) -> None:
        if generation != self._verify_generation:
            return
        if self._current is None or self._current.id != capture_id or self._current_mode != mode:
            return
        self._verify_running = False
        self.verify_btn.set_enabled(True)
        self.verify_progress.stop()
        self.verify_progress.pack_forget()

        checks = list(result.checks)
        type_check = next((c for c in checks if c.key == "type"), None)
        rect = result.data.get("rect") if result.data else None
        rect_ok = isinstance(rect, (list, tuple)) and len(rect) == 4 and int(rect[2]) > int(rect[0]) and int(rect[3]) > int(rect[1])
        can_highlight = bool(result.data) and rect_ok and (type_check is None or type_check.status != "fail")

        warnings = any(c.status == "warn" for c in checks)
        if can_highlight:
            info = self._hover_info_from_capture(self._current)
            visual_mode = "warn" if (warnings or not result.ok) else "verify"
            highlighted = self.overlay.flash(
                (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])),
                info,
                duration_ms=2600,
                mode=visual_mode,
            )
            checks.append(
                CheckResult(
                    "highlight",
                    "高亮显示",
                    "pass" if highlighted else "fail",
                    "已显示 2.6 秒" if highlighted else "无法显示高亮覆盖层",
                )
            )
            if not highlighted:
                result.ok = False
                if not result.error:
                    result.error = "高亮覆盖层创建失败。"
        else:
            checks.append(
                CheckResult(
                    "highlight",
                    "高亮显示",
                    "fail" if not result.ok else "warn",
                    "未能取得可高亮的有效矩形",
                )
            )

        result.checks = checks
        self._verify_result = result
        self._render_checks(checks)

        if not result.ok:
            self.verify_result_label.configure(
                text=f"校验失败 · {result.duration:.2f}s",
                fg=self.theme.red,
            )
            self._set_status("代码校验失败", "error")
            details = "\n".join(
                f"{c.label}: {c.detail}" for c in checks if c.status in ("fail", "warn") and c.detail
            )
            if result.error:
                details = (details + "\n" if details else "") + result.error
            if result.stderr:
                details = (details + "\n" if details else "") + result.stderr
            self._show_verify_error(details)
            self.logger.warning("验证失败: %s", details[:1200])
        elif warnings:
            self.verify_result_label.configure(
                text=f"通过（有警告） · {result.duration:.2f}s",
                fg=self.theme.amber,
            )
            self._set_status("代码校验通过，但属性有变化", "warning")
            self._hide_verify_error()
            self.logger.info("验证通过（有警告）: %s", [c.detail for c in checks if c.status == "warn"])
        else:
            self.verify_result_label.configure(
                text=f"校验通过 · {result.duration:.2f}s",
                fg=self.theme.green,
            )
            self._set_status("代码校验通过，元素已高亮", "success")
            self._hide_verify_error()
            self.logger.info("验证通过: %s", capture_id)

    def _render_checks(self, checks: List[CheckResult]) -> None:
        t = self.theme
        for child in self.checks_frame.winfo_children():
            child.destroy()
        if not checks:
            self._show_checks_hint()
            return
        icons = {"pass": "✓", "warn": "!", "fail": "✗", "skip": "–"}
        colors = {
            "pass": (t.green, t.green_soft),
            "warn": (t.amber, t.amber_soft),
            "fail": (t.red, t.red_soft),
            "skip": (t.faint, t.surface_3),
        }
        for check in checks:
            fg, bg = colors.get(check.status, (t.muted, t.surface_3))
            pill = Pill(
                self.checks_frame,
                t,
                f"{icons.get(check.status, '·')} {check.label}",
                fg=fg,
                bg=bg,
                height=t.px(23),
                font=t.font_tiny_bold,
            )
            pill.pack(side="left", padx=(0, t.px(5)), pady=(t.px(2), 0))
            if check.detail:
                Tooltip(pill, t, check.detail)

    def _show_verify_error(self, text: str) -> None:
        if not text:
            self._hide_verify_error()
            return
        if len(text) > 2200:
            text = text[:2197] + "..."
        self.verify_error_box.configure(state="normal")
        self.verify_error_box.delete("1.0", "end")
        self.verify_error_box.insert("1.0", text)
        self.verify_error_box.configure(state="disabled")
        self.verify_error_box.pack(fill="x", padx=self.theme.px(10), pady=(0, self.theme.px(9)))

    def _hide_verify_error(self) -> None:
        try:
            self.verify_error_box.pack_forget()
        except Exception:
            pass

    def _hover_info_from_capture(self, capture: ElementCapture) -> HoverInfo:
        return HoverInfo(
            control_type_name=capture.control_type_name,
            localized_type=capture.localized_control_type,
            name=capture.name,
            automation_id=capture.automation_id,
            class_name=capture.class_name,
            rect=capture.rect,
            process_id=capture.process_id,
            process_name=capture.process_name,
            framework_id=capture.framework_id,
        )

    def _highlight_current(self) -> None:
        if self._current is None:
            return
        capture = self._current
        if capture.width <= 0 or capture.height <= 0:
            messagebox.showwarning("无法高亮", "该元素当前没有有效的屏幕矩形。", parent=self.root)
            return
        if self.overlay.flash(capture.rect, self._hover_info_from_capture(capture), duration_ms=2600):
            self._set_status("已高亮元素 2.6 秒", "success")
        else:
            messagebox.showwarning("无法高亮", "高亮覆盖层创建失败。", parent=self.root)

    # ------------------------------------------------------------------
    # 元素操作：点击 / 输入 / 获取值
    # ------------------------------------------------------------------
    def _action_label(self, kind: str) -> str:
        return {"click": "点击", "input": "输入", "get_value": "获取值"}.get(kind, kind)

    def _click_current(self) -> None:
        self._start_action("click")

    def _input_current(self) -> None:
        if self._current is None:
            return
        text = ask_text(
            self.root,
            self.theme,
            "输入文本",
            f"将文本输入到：{self._current.display_name}",
            "",
        )
        if text is None:
            return
        self._start_action("input", text)

    def _get_value_current(self) -> None:
        self._start_action("get_value", hide_window=False)

    def _start_action(self, kind: str, payload=None, hide_window: bool = True) -> None:
        if self._current is None or self._action_running:
            return
        try:
            if self.root.grab_current() is not None:
                return
        except Exception:
            pass
        if self._picking or self._capturing or self._verify_running:
            return
        capture = self._current
        self._action_running = True
        self._action_kind = kind
        self._action_hid_window = bool(hide_window)
        self.overlay.hide()
        self._set_action_buttons_enabled(False)
        if hide_window:
            self._restore_state = self.root.state()
            self.root.withdraw()
        self._set_status(f"正在{self._action_label(kind)}元素…", "info")
        self._action_timeout_job = self.root.after(12000, self._action_timeout)
        self._picker.action(kind, payload, capture)
        self.logger.info("请求元素操作: %s %r steps=%d", kind, capture.name, len(capture.steps))

    def _finish_action(self) -> None:
        if self._action_timeout_job is not None:
            try:
                self.root.after_cancel(self._action_timeout_job)
            except Exception:
                pass
            self._action_timeout_job = None
        if self._action_hid_window:
            self._restore_window()
            self._action_hid_window = False
        self._action_running = False
        self._action_kind = ""
        self._custom_running = False
        self._custom_save_job = None
        self._custom_run_count = 0
        self._set_action_buttons_enabled(True)

    def _action_timeout(self) -> None:
        self._action_timeout_job = None
        if not self._action_running:
            return
        kind = self._action_kind
        self._finish_action()
        self._set_status(f"{self._action_label(kind)}超时", "error")
        messagebox.showwarning(
            f"{self._action_label(kind)}超时",
            "目标程序可能无响应，或该控件不支持此操作。",
            parent=self.root,
        )

    def _on_action_done(self, kind: str, message: str) -> None:
        if not self._action_running or kind != self._action_kind:
            return
        self._finish_action()
        self._toast(f"{self._action_label(kind)}成功：{message}", "success")
        self._set_status(f"{self._action_label(kind)}成功：{message}", "success")
        self.logger.info("元素操作成功: %s %s", kind, message)

    def _on_action_error(self, kind: str, message: str, hint: str = "") -> None:
        if not self._action_running or kind != self._action_kind:
            return
        self._finish_action()
        text = message
        if hint:
            text += "\n\n" + hint
        self._set_status(f"{self._action_label(kind)}失败", "error")
        self.logger.warning("元素操作失败: %s %s | hint=%s", kind, message, hint)
        messagebox.showerror(f"{self._action_label(kind)}失败", text, parent=self.root)
        if hint and "管理员" in hint and not is_admin():
            if messagebox.askyesno("权限不足", "是否以管理员身份重启捕获器？", parent=self.root):
                self._restart_admin()

    def _on_action_value(self, kind: str, value: str, source: str) -> None:
        if not self._action_running or kind != self._action_kind:
            return
        self._finish_action()
        self._set_status(f"已读取元素值（{source}）", "success")
        self.logger.info("读取元素值: source=%s length=%d", source, len(value or ""))
        show_value(self.root, self.theme, "元素当前值", value, source)

    # ------------------------------------------------------------------
    # 搜索与菜单
    # ------------------------------------------------------------------
    def _focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def _on_search_focus_in(self, _event=None) -> None:
        if self._search_active:
            self.search_var.set("")
            self.search_entry.configure(fg=self.theme.text)
            self._search_active = False

    def _on_search_focus_out(self, _event=None) -> None:
        if not self.search_var.get().strip():
            self.search_var.set(self._search_placeholder)
            self.search_entry.configure(fg=self.theme.faint)
            self._search_active = True

    def _on_search_key(self, _event=None) -> None:
        if self._search_active:
            return
        self._refresh_tree()

    def _select_all_search(self, _event=None) -> str:
        self.search_entry.select_range(0, "end")
        self.search_entry.icursor("end")
        return "break"

    def _clear_search(self) -> None:
        if self._search_active:
            return
        self.search_var.set("")
        self.search_entry.configure(fg=self.theme.text)
        self._search_active = False
        self._refresh_tree()
        self.search_entry.focus_set()

    def _show_more_menu(self) -> None:
        t = self.theme
        menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=t.surface_2,
            fg=t.text,
            activebackground=t.surface_3,
            activeforeground=t.accent,
            bd=0,
            relief="flat",
            font=t.font_small,
        )
        menu.add_command(label="打开数据目录", command=self._open_data_dir)
        menu.add_command(label="打开日志目录", command=self._open_log_dir)
        menu.add_separator()
        menu.add_command(label="Python 环境设置", command=self._open_settings)
        menu.add_command(label="以管理员身份重启", command=self._restart_admin)
        menu.add_separator()
        menu.add_command(label="关于捕获器", command=self._about)
        self._menu = menu
        try:
            x = self.more_btn.winfo_rootx()
            y = self.more_btn.winfo_rooty() + self.more_btn.winfo_height() + t.px(4)
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _open_data_dir(self) -> None:
        open_folder(DATA_DIR)

    def _open_settings(self) -> None:
        if self._closing:
            return
        result = show_settings(self.root, self.theme, self.settings.resolved_python())
        if not result:
            return
        self.settings.python_exe = result
        if save_settings(self.settings):
            self._update_python_hint()
            self._update_status_meta()
            self._toast(f"已保存 Python 环境：{Path(result).name}", "success")
            self._set_status(f"回放解释器已切换为 {Path(result).name}", "success")
            self.logger.info("Python 环境设置已保存: %s", result)
        else:
            self._toast("设置保存失败", "error")

    def _update_python_hint(self) -> None:
        label = getattr(self, "verify_hint", None)
        if label is None:
            return
        try:
            exe = self.settings.resolved_python()
            if exe:
                label.configure(text=f"{Path(exe).name} · Ctrl+Enter 回放")
            else:
                label.configure(text="未指定 Python · 点右上角 ⚙ 设置")
        except Exception:
            pass

    def _update_status_meta(self) -> None:
        label = getattr(self, "status_meta_label", None)
        if label is None:
            return
        try:
            scale = dpi_scale()
            python_name = Path(self.settings.resolved_python()).name
            label.configure(
                text=(
                    f"UI Automation · {system_dpi()} DPI ({int(round(scale * 100))}%) · "
                    f"{'管理员' if is_admin() else '标准权限'} · {python_name}"
                )
            )
        except Exception:
            pass

    def _open_log_dir(self) -> None:
        open_folder(LOG_DIR)

    def _restart_admin(self) -> None:
        if is_admin():
            self._toast("当前已经是管理员权限", "info")
            return
        if restart_as_admin(APP_SCRIPT, APP_DIR):
            self._on_close()
        else:
            messagebox.showerror("重启失败", "无法以管理员身份启动，可能取消了 UAC 授权。", parent=self.root)

    def _about(self) -> None:
        messagebox.showinfo(
            "关于桌面元素捕获器",
            "桌面元素捕获器 1.0.0\n\n"
            "基于 Windows UI Automation 捕获任意桌面程序控件。\n"
            "可生成 uiautomation / pywinauto 两套可运行代码，\n"
            "并在独立 Python 进程中回放定位、校验高亮。\n\n"
            "快捷键：F2 捕获 · F2 锁定 · Esc 取消 · Ctrl+Enter 验证\n"
            "Ctrl+1 点击 · Ctrl+2 输入 · Ctrl+3 取值 · Ctrl+F 搜索",
            parent=self.root,
        )

    # ------------------------------------------------------------------
    # 记录操作
    # ------------------------------------------------------------------
    def _clear_all(self) -> None:
        if not self.captures:
            self._toast("没有可清空的记录", "info")
            return
        if not messagebox.askyesno("清空记录", f"确定删除全部 {len(self.captures)} 条捕获记录吗？", parent=self.root):
            return
        self.store.clear()
        self.captures = []
        self._current = None
        self._current_id = ""
        self._refresh_tree()
        self._toast("已清空全部记录", "success")
        self._set_status("记录已清空", "info")

    def _delete_current(self) -> None:
        if self._current is None:
            return
        capture = self._current
        if not messagebox.askyesno(
            "删除记录",
            f"确定删除这条捕获记录吗？\n\n{capture.type_label}：{capture.display_name}",
            parent=self.root,
        ):
            return
        self.captures = [c for c in self.captures if c.id != capture.id]
        self.store.save(self.captures)
        try:
            path = self.store.thumb_path(capture)
            if path:
                path.unlink(missing_ok=True)
        except Exception:
            pass
        self._current = None
        self._current_id = ""
        self._refresh_tree()
        self._toast("记录已删除", "success")

    def _export_json(self) -> None:
        if not self.captures:
            self._toast("没有可导出的记录", "info")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出捕获记录",
            defaultextension=".json",
            initialfile=f"elements-{time.strftime('%Y%m%d')}.json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        if self.store.export_json(Path(path), self.captures):
            self._toast("记录已导出", "success")
            self._set_status(f"已导出到 {path}", "success")
        else:
            messagebox.showerror("导出失败", self.store.last_error, parent=self.root)

    # ------------------------------------------------------------------
    # 状态与关闭
    # ------------------------------------------------------------------
    def _set_status(self, text: str, kind: str = "info") -> None:
        colors = {
            "info": self.theme.accent,
            "success": self.theme.green,
            "warning": self.theme.amber,
            "error": self.theme.red,
        }
        try:
            self.status_label.configure(text=text)
            self.status_dot.itemconfigure(self._dot, fill=colors.get(kind, self.theme.accent))
        except Exception:
            pass

    def _toast(self, message: str, kind: str = "info") -> None:
        if self._closing:
            return
        t = self.theme
        if self._toast_frame is not None:
            try:
                self._toast_frame.destroy()
            except Exception:
                pass
            self._toast_frame = None
        if self._toast_job is not None:
            try:
                self.root.after_cancel(self._toast_job)
            except Exception:
                pass
            self._toast_job = None
        color = {
            "success": t.green,
            "warning": t.amber,
            "error": t.red,
        }.get(kind, t.accent)
        frame = tk.Frame(
            self.root,
            bg=t.surface_2,
            highlightbackground=t.border_light,
            highlightthickness=1,
            bd=0,
        )
        accent = tk.Frame(frame, bg=color, width=t.px(4))
        accent.pack(side="left", fill="y")
        tk.Label(
            frame,
            text=message,
            bg=t.surface_2,
            fg=t.text,
            font=t.font_small,
            padx=t.px(12),
            pady=t.px(8),
            justify="left",
            wraplength=t.px(420),
        ).pack(side="left")
        frame.place(relx=1.0, rely=1.0, x=-t.px(24), y=-t.px(44), anchor="se")
        frame.lift()
        self._toast_frame = frame
        self._toast_job = self.root.after(2800, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast_job = None
        if self._toast_frame is not None:
            try:
                self._toast_frame.destroy()
            except Exception:
                pass
            self._toast_frame = None

    def _on_escape(self, _event=None) -> None:
        if self._picking:
            self._cancel_picking()
        elif self.overlay.visible:
            self.overlay.hide()

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self._save_custom_code()
        except Exception:
            pass
        try:
            self.overlay.destroy()
        except Exception:
            pass
        try:
            self._picker.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
