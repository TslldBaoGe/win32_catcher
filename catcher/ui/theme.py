"""暗色主题与字体/尺寸标尺。"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from ..winutil import dpi_scale


class Theme:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.scale = dpi_scale()

        self.bg = "#0A101A"
        self.surface = "#101927"
        self.surface_2 = "#142033"
        self.surface_3 = "#1B2A41"
        self.border = "#22334D"
        self.border_light = "#2E4666"
        self.text = "#E8F0FB"
        self.muted = "#93A8C4"
        self.faint = "#607894"
        self.accent = "#2DD4BF"
        self.accent_hover = "#5EEAD4"
        self.accent_active = "#14B8A6"
        self.accent_soft = "#123B3A"
        self.cyan = "#38BDF8"
        self.green = "#34D399"
        self.green_soft = "#12352C"
        self.amber = "#FBBF24"
        self.amber_soft = "#3A2E12"
        self.red = "#F87171"
        self.red_soft = "#3A1A1A"
        self.code_bg = "#0A121F"
        self.code_text = "#D7E3F4"
        self.code_comment = "#5F7694"
        self.code_string = "#A7D8A0"
        self.code_keyword = "#7DD3FC"
        self.code_builtin = "#C4B5FD"
        self.code_number = "#FCA5A5"
        self.code_function = "#93C5FD"
        self.code_decorator = "#FBBF24"
        self.selection = "#1E3A5F"

        families = set(tkfont.families(root))
        self.ui_family = self._pick(
            families, ["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "Arial"]
        )
        self.mono_family = self._pick(
            families, ["Cascadia Code", "JetBrains Mono", "Consolas", "Courier New"]
        )

        self.font_tiny = (self.ui_family, 8)
        self.font_tiny_bold = (self.ui_family, 8, "bold")
        self.font_small = (self.ui_family, 9)
        self.font_small_bold = (self.ui_family, 9, "bold")
        self.font_body = (self.ui_family, 10)
        self.font_body_bold = (self.ui_family, 10, "bold")
        self.font_h2 = (self.ui_family, 12, "bold")
        self.font_title = (self.ui_family, 18, "bold")
        self.font_brand = (self.ui_family, 13, "bold")
        self.font_code = (self.mono_family, 10)
        self.font_code_small = (self.mono_family, 9)
        self.font_icon = (self.ui_family, 12)
        self.font_icon_large = (self.ui_family, 22)

        self._init_ttk()

    @staticmethod
    def _pick(families: set, candidates) -> str:
        for name in candidates:
            if name in families:
                return name
        return "Segoe UI"

    def px(self, value: float) -> int:
        return max(1, int(round(float(value) * self.scale)))

    def _init_ttk(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Catcher.Treeview",
            background=self.surface,
            fieldbackground=self.surface,
            foreground=self.text,
            borderwidth=0,
            rowheight=self.px(34),
            font=self.font_body,
        )
        style.layout("Catcher.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Catcher.Treeview.Heading",
            background=self.surface_2,
            foreground=self.muted,
            relief="flat",
            borderwidth=0,
            font=self.font_small_bold,
            padding=(self.px(8), self.px(7)),
        )
        style.map(
            "Catcher.Treeview.Heading",
            background=[("active", self.surface_3)],
            foreground=[("active", self.text)],
        )
        style.map(
            "Catcher.Treeview",
            background=[("selected", self.selection)],
            foreground=[("selected", self.text)],
        )
        style.configure(
            "Catcher.Horizontal.TProgressbar",
            troughcolor=self.surface_3,
            background=self.accent,
            bordercolor=self.surface_3,
            lightcolor=self.accent,
            darkcolor=self.accent,
            thickness=self.px(4),
        )

        self.root.option_add("*Menu.background", self.surface_2)
        self.root.option_add("*Menu.foreground", self.text)
        self.root.option_add("*Menu.activeBackground", self.surface_3)
        self.root.option_add("*Menu.activeForeground", self.accent)
        self.root.option_add("*Menu.borderWidth", 0)
        self.root.option_add("*Menu.relief", "flat")
        self.root.option_add("*Menu.font", self.font_small)
