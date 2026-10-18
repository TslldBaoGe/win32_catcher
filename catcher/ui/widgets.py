"""自绘控件与代码查看器。"""
from __future__ import annotations

import re
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Dict, Iterable, Optional, Tuple


def _parent_bg(widget: tk.Misc, fallback: str) -> str:
    try:
        return str(widget.cget("bg"))
    except Exception:
        return fallback


def _round_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs):
    radius = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent,
        theme,
        text: str,
        command: Optional[Callable[[], None]] = None,
        kind: str = "primary",
        width: Optional[int] = None,
        height: Optional[int] = None,
        font=None,
        radius: Optional[int] = None,
        tooltip: str = "",
    ) -> None:
        self.theme = theme
        self.text = text
        self.command = command
        self.kind = kind
        self._fixed_width = width
        self._font = font or theme.font_small_bold
        self._height = height or theme.px(36)
        self._radius = radius if radius is not None else theme.px(8)
        self._enabled = True
        self._hover = False
        self._pressed = False
        self._focused = False
        self._bg = _parent_bg(parent, theme.bg)
        font_obj = tkfont.Font(font=self._font)
        self._text_w = font_obj.measure(text)
        w = width or (self._text_w + theme.px(30))
        super().__init__(
            parent,
            width=w,
            height=self._height,
            bg=self._bg,
            highlightthickness=0,
            bd=0,
            takefocus=1,
            cursor="hand2",
        )
        self._width = w
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Return>", self._on_key)
        self.bind("<space>", self._on_key)
        if tooltip:
            Tooltip(self, theme, tooltip)

    def _palette(self) -> Tuple[str, str, str]:
        t = self.theme
        if not self._enabled:
            return t.surface_2, t.faint, t.border
        if self.kind == "primary":
            fill = t.accent_active if self._pressed else (t.accent_hover if self._hover else t.accent)
            return fill, "#06211E", fill
        if self.kind == "secondary":
            fill = t.surface_3 if (self._hover or self._pressed) else t.surface_2
            return fill, t.text, t.border_light
        if self.kind == "danger":
            fill = "#4A2020" if self._hover else t.red_soft
            return fill, t.red, "#5A2A2A"
        if self.kind == "ghost":
            fill = t.surface_2 if (self._hover or self._pressed) else self._bg
            return fill, t.text if self._hover else t.muted, fill
        fill = t.surface_2
        return fill, t.text, t.border

    def _draw(self) -> None:
        self.delete("all")
        fill, fg, outline = self._palette()
        border = self.theme.accent if self._focused and self._enabled else outline
        _round_rect(
            self,
            0,
            0,
            self._width - 1,
            self._height - 1,
            self._radius,
            fill=fill,
            outline=border,
            width=1,
        )
        self.create_text(
            self._width // 2,
            self._height // 2,
            text=self.text,
            fill=fg,
            font=self._font,
            anchor="center",
        )

    def _recalc_width(self) -> None:
        if self._fixed_width is not None:
            return
        font_obj = tkfont.Font(font=self._font)
        self._text_w = font_obj.measure(self.text)
        self._width = self._text_w + self.theme.px(30)
        self.configure(width=self._width)

    def set_text(self, text: str) -> None:
        self.text = text
        self._recalc_width()
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self._draw()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._pressed = False
        self._draw()

    def _on_press(self, event) -> None:
        if not self._enabled:
            return
        self.focus_set()
        self._pressed = True
        self._draw()

    def _on_release(self, event) -> None:
        if not self._enabled:
            return
        inside = 0 <= event.x < self._width and 0 <= event.y < self._height
        was_pressed = self._pressed
        self._pressed = False
        self._draw()
        if was_pressed and inside and self.command:
            self.command()

    def _on_key(self, _event=None) -> str:
        if self._enabled and self.command:
            self.command()
        return "break"

    def _on_focus_in(self, _event=None) -> None:
        self._focused = True
        self._draw()

    def _on_focus_out(self, _event=None) -> None:
        self._focused = False
        self._draw()


class Pill(tk.Canvas):
    def __init__(
        self,
        parent,
        theme,
        text: str,
        fg: Optional[str] = None,
        bg: Optional[str] = None,
        outline: str = "",
        font=None,
        height: Optional[int] = None,
        padx: Optional[int] = None,
    ) -> None:
        self.theme = theme
        self.text = text
        self.fg = fg or theme.muted
        self.bg = bg or theme.surface_2
        self.outline = outline
        self.font = font or theme.font_tiny_bold
        self._padx = padx if padx is not None else theme.px(9)
        self._height = height or theme.px(24)
        self._parent_bg = _parent_bg(parent, theme.surface)
        font_obj = tkfont.Font(font=self.font)
        self._width = font_obj.measure(text) + self._padx * 2
        super().__init__(
            parent,
            width=self._width,
            height=self._height,
            bg=self._parent_bg,
            highlightthickness=0,
            bd=0,
        )
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        _round_rect(
            self,
            0,
            0,
            self._width - 1,
            self._height - 1,
            self._height // 2,
            fill=self.bg,
            outline=self.outline or self.bg,
            width=1,
        )
        self.create_text(
            self._width // 2,
            self._height // 2,
            text=self.text,
            fill=self.fg,
            font=self.font,
            anchor="center",
        )

    def set(self, text: Optional[str] = None, fg: Optional[str] = None, bg: Optional[str] = None, outline: Optional[str] = None) -> None:
        if text is not None:
            self.text = text
        if fg is not None:
            self.fg = fg
        if bg is not None:
            self.bg = bg
        if outline is not None:
            self.outline = outline
        font_obj = tkfont.Font(font=self.font)
        self._width = font_obj.measure(self.text) + self._padx * 2
        self.configure(width=self._width)
        self._draw()


class SegmentedControl(tk.Frame):
    def __init__(
        self,
        parent,
        theme,
        options: Iterable[Tuple[str, str]],
        active: str,
        command: Callable[[str], None],
    ) -> None:
        self.theme = theme
        self.options = list(options)
        self.active = active
        self.command = command
        self._labels: Dict[str, tk.Label] = {}
        super().__init__(
            parent,
            bg=theme.surface_2,
            highlightbackground=theme.border,
            highlightthickness=1,
            bd=0,
        )
        for key, label in self.options:
            lbl = tk.Label(
                self,
                text=label,
                bg=theme.accent_soft if key == active else theme.surface_2,
                fg=theme.accent if key == active else theme.muted,
                font=theme.font_small_bold,
                padx=theme.px(12),
                pady=theme.px(5),
                cursor="hand2",
            )
            lbl.pack(side="left", fill="both", expand=True)
            lbl.bind("<Button-1>", lambda _e, k=key: self.set_active(k, notify=True))
            lbl.bind("<Enter>", lambda _e, k=key: self._hover(k, True))
            lbl.bind("<Leave>", lambda _e, k=key: self._hover(k, False))
            self._labels[key] = lbl

    def _hover(self, key: str, entering: bool) -> None:
        if key == self.active:
            return
        lbl = self._labels[key]
        lbl.configure(bg=self.theme.surface_3 if entering else self.theme.surface_2)

    def set_active(self, key: str, notify: bool = False) -> None:
        if key not in self._labels:
            return
        self.active = key
        for k, lbl in self._labels.items():
            lbl.configure(
                bg=self.theme.accent_soft if k == key else self.theme.surface_2,
                fg=self.theme.accent if k == key else self.theme.muted,
            )
        if notify:
            self.command(key)


class ScrollableFrame(tk.Frame):
    def __init__(self, parent, theme, bg: Optional[str] = None) -> None:
        self.theme = theme
        self._bg = bg or theme.surface
        super().__init__(parent, bg=self._bg, bd=0, highlightthickness=0)
        self.canvas = tk.Canvas(
            self,
            bg=self._bg,
            highlightthickness=0,
            bd=0,
        )
        self.vbar = DarkScrollbar(
            self,
            theme,
            command=self.canvas.yview,
            orient="vertical",
            bg=self._bg,
        )
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar.pack(side="right", fill="y")
        self.inner = tk.Frame(self.canvas, bg=self._bg, bd=0, highlightthickness=0)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        self._wheel_bound = False

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _event=None) -> None:
        if not self._wheel_bound:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
            self.canvas.bind_all("<Button-4>", self._on_wheel)
            self.canvas.bind_all("<Button-5>", self._on_wheel)
            self._wheel_bound = True

    def _unbind_wheel(self, _event=None) -> None:
        if self._wheel_bound:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")
            self._wheel_bound = False

    def _on_wheel(self, event) -> str:
        if getattr(event, "num", None) == 4:
            delta = 1
        elif getattr(event, "num", None) == 5:
            delta = -1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")
        return "break"


class CodeViewer(tk.Frame):
    _TOKEN_RE = re.compile(
        r"(?P<comment>#[^\n]*)"
        r"|(?P<string>(?i:[rubf]{0,2})(?:\"\"\"(?:\\.|.)*?\"\"\"|'''(?:\\.|.)*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'))"
        r"|(?P<decorator>@[A-Za-z_][\w.]*)"
        r"|(?P<keyword>\b(?:False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b)"
        r"|(?P<builtin>\b(?:print|len|str|int|float|bool|list|dict|tuple|set|getattr|hasattr|range|enumerate|Exception|LookupError|Path)\b)"
        r"|(?P<number>\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?)\b)"
        r"|(?P<function>\b[A-Za-z_]\w*(?=\())",
        re.MULTILINE | re.DOTALL,
    )

    def __init__(self, parent, theme, editable: bool = False, on_change=None) -> None:
        self.theme = theme
        self._editable = bool(editable)
        self._on_change = on_change
        self._highlight_job = None
        super().__init__(
            parent,
            bg=theme.code_bg,
            highlightbackground=theme.border,
            highlightthickness=1,
            bd=0,
        )
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.gutter = tk.Text(
            self,
            width=4,
            bg=theme.code_bg,
            fg=theme.faint,
            bd=0,
            highlightthickness=0,
            padx=theme.px(6),
            pady=theme.px(10),
            font=theme.font_code_small,
            state="disabled",
            takefocus=0,
            cursor="arrow",
        )
        self.gutter.grid(row=0, column=0, sticky="ns")

        self.text = tk.Text(
            self,
            bg=theme.code_bg,
            fg=theme.code_text,
            insertbackground=theme.accent,
            selectbackground=theme.selection,
            selectforeground=theme.text,
            bd=0,
            highlightthickness=0,
            padx=theme.px(10),
            pady=theme.px(10),
            font=theme.font_code,
            wrap="none",
            undo=False,
            state="disabled",
            spacing1=theme.px(1),
            spacing3=theme.px(1),
            tabs=(theme.px(28),),
        )
        self.text.grid(row=0, column=1, sticky="nsew")

        self.vbar = DarkScrollbar(
            self,
            theme,
            command=self._yview,
            orient="vertical",
            bg=theme.code_bg,
        )
        self.vbar.grid(row=0, column=2, sticky="ns")
        self.hbar = DarkScrollbar(
            self,
            theme,
            command=self.text.xview,
            orient="horizontal",
            bg=theme.code_bg,
        )
        self.hbar.grid(row=1, column=1, sticky="ew")
        self.text.configure(xscrollcommand=self.hbar.set, yscrollcommand=self._on_yscroll)

        italic = tkfont.Font(family=theme.mono_family, size=10, slant="italic")
        self.text.tag_configure("comment", foreground=theme.code_comment, font=italic)
        self.text.tag_configure("string", foreground=theme.code_string)
        self.text.tag_configure("decorator", foreground=theme.code_decorator)
        self.text.tag_configure("keyword", foreground=theme.code_keyword)
        self.text.tag_configure("builtin", foreground=theme.code_builtin)
        self.text.tag_configure("number", foreground=theme.code_number)
        self.text.tag_configure("function", foreground=theme.code_function)

        self.text.bind("<Control-c>", self._copy)
        self.text.bind("<Control-a>", self._select_all)
        if self._editable:
            self.text.configure(state="normal", undo=True, maxundo=-1, autoseparators=True)
            self.text.bind("<KeyRelease>", self._on_edited, add="+")
            self.text.bind("<<Paste>>", self._on_edited, add="+")
            self.text.bind("<<Cut>>", self._on_edited, add="+")
        self.gutter.bind("<MouseWheel>", self._wheel)
        self.gutter.bind("<Button-4>", self._wheel)
        self.gutter.bind("<Button-5>", self._wheel)

    def _on_yscroll(self, first, last) -> None:
        self.vbar.set(first, last)
        try:
            self.gutter.yview_moveto(first)
        except Exception:
            pass

    def _yview(self, *args) -> None:
        self.text.yview(*args)
        try:
            self.gutter.yview_moveto(self.text.yview()[0])
        except Exception:
            pass

    def _wheel(self, event) -> str:
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.text.yview_scroll(delta, "units")
        return "break"

    def _copy(self, _event=None) -> str:
        try:
            selected = self.text.get("sel.first", "sel.last")
        except Exception:
            selected = self.text.get("1.0", "end-1c")
        if selected:
            self.text.clipboard_clear()
            self.text.clipboard_append(selected)
        return "break"

    def _select_all(self, _event=None) -> str:
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def set_code(self, code: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", code)
        for tag in ("comment", "string", "decorator", "keyword", "builtin", "number", "function"):
            self.text.tag_remove(tag, "1.0", "end")
        for match in self._TOKEN_RE.finditer(code):
            group = match.lastgroup
            if not group:
                continue
            self.text.tag_add(group, f"1.0+{match.start()}c", f"1.0+{match.end()}c")
        if not self._editable:
            self.text.configure(state="disabled")
        else:
            self.text.configure(state="normal")

        line_count = max(1, code.count("\n") + (0 if code.endswith("\n") else 1))
        numbers = "\n".join(str(i) for i in range(1, line_count + 1))
        self.gutter.configure(state="normal")
        self.gutter.delete("1.0", "end")
        self.gutter.insert("1.0", numbers)
        self.gutter.configure(state="disabled")
        self.text.yview_moveto(0)
        self.gutter.yview_moveto(0)

    def get_code(self) -> str:
        return self.text.get("1.0", "end-1c")


    def _on_edited(self, _event=None) -> None:
        if self._highlight_job is not None:
            try:
                self.after_cancel(self._highlight_job)
            except Exception:
                pass
        self._highlight_job = self.after(250, self._refresh_edited)

    def _refresh_edited(self) -> None:
        self._highlight_job = None
        code = self.text.get("1.0", "end-1c")
        self.text.configure(state="normal")
        self._apply_highlight(code)
        self._update_gutter(code)
        self.text.mark_set("insert", "insert")
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    def _apply_highlight(self, code: str) -> None:
        for tag in ("comment", "string", "decorator", "keyword", "builtin", "number", "function"):
            self.text.tag_remove(tag, "1.0", "end")
        for match in self._TOKEN_RE.finditer(code):
            group = match.lastgroup
            if not group:
                continue
            self.text.tag_add(group, f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def _update_gutter(self, code: str) -> None:
        newline = chr(10)
        line_count = max(1, code.count(newline) + (0 if code.endswith(newline) else 1))
        numbers = newline.join(str(i) for i in range(1, line_count + 1))
        self.gutter.configure(state="normal")
        self.gutter.delete("1.0", "end")
        self.gutter.insert("1.0", numbers)
        self.gutter.configure(state="disabled")


class Tooltip:
    def __init__(self, widget: tk.Misc, theme, text: str, delay: int = 450) -> None:
        self.widget = widget
        self.theme = theme
        self.text = text
        self.delay = delay
        self._job = None
        self._window: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._job = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _show(self) -> None:
        if self._window is not None:
            return
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.theme.px(6)
            win = tk.Toplevel(self.widget)
            win.withdraw()
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            frame = tk.Frame(
                win,
                bg=self.theme.surface_2,
                highlightbackground=self.theme.border_light,
                highlightthickness=1,
                bd=0,
            )
            frame.pack(fill="both", expand=True)
            tk.Label(
                frame,
                text=self.text,
                bg=self.theme.surface_2,
                fg=self.theme.text,
                font=self.theme.font_tiny,
                padx=self.theme.px(8),
                pady=self.theme.px(5),
                justify="left",
            ).pack()
            win.update_idletasks()
            win.geometry(f"+{x}+{y}")
            win.deiconify()
            self._window = win
        except Exception:
            self._window = None

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None


class DarkScrollbar(tk.Canvas):
    """与暗色主题一致的自绘滚动条。"""

    def __init__(
        self,
        parent,
        theme,
        command,
        orient: str = "vertical",
        bg: Optional[str] = None,
        thickness: Optional[int] = None,
    ) -> None:
        self.theme = theme
        self.command = command
        self.orient = orient
        self._bg = bg or _parent_bg(parent, theme.surface)
        self._thickness = thickness or theme.px(10)
        self._first = 0.0
        self._last = 1.0
        self._hover = False
        self._dragging = False
        self._drag_offset = 0.0
        self._thumb_start = 0.0
        self._thumb_len = 0.0
        if orient == "vertical":
            super().__init__(
                parent,
                width=self._thickness,
                bg=self._bg,
                highlightthickness=0,
                bd=0,
                takefocus=0,
                cursor="arrow",
            )
        else:
            super().__init__(
                parent,
                height=self._thickness,
                bg=self._bg,
                highlightthickness=0,
                bd=0,
                takefocus=0,
                cursor="arrow",
            )
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def set(self, first, last) -> None:
        try:
            self._first = max(0.0, min(1.0, float(first)))
            self._last = max(self._first, min(1.0, float(last)))
        except Exception:
            self._first, self._last = 0.0, 1.0
        self._draw()

    def _pad(self) -> int:
        return self.theme.px(2)

    def _track(self) -> Tuple[int, int]:
        pad = self._pad()
        if self.orient == "vertical":
            return pad, max(0, self.winfo_height() - pad)
        return pad, max(0, self.winfo_width() - pad)

    def _draw(self) -> None:
        self.delete("all")
        if self._last - self._first >= 0.999:
            return
        pad = self._pad()
        start, end = self._track()
        length = end - start
        if length <= 2:
            return
        span = max(0.0001, self._last - self._first)
        thumb_len = max(self.theme.px(22), int(length * span))
        thumb_len = min(length, thumb_len)
        thumb_start = start + int((length - thumb_len) * (self._first / max(0.0001, 1.0 - span)))
        thumb_start = max(start, min(thumb_start, end - thumb_len))
        self._thumb_start = float(thumb_start)
        self._thumb_len = float(thumb_len)
        color = self.theme.border_light if (self._hover or self._dragging) else self.theme.surface_3
        if self.orient == "vertical":
            x1 = pad
            x2 = max(pad + 1, self.winfo_width() - pad)
            _round_rect(self, x1, thumb_start, x2, thumb_start + thumb_len, (x2 - x1) // 2, fill=color, outline=color)
        else:
            y1 = pad
            y2 = max(pad + 1, self.winfo_height() - pad)
            _round_rect(self, thumb_start, y1, thumb_start + thumb_len, y2, (y2 - y1) // 2, fill=color, outline=color)

    def _coord(self, event) -> float:
        return float(event.y) if self.orient == "vertical" else float(event.x)

    def _on_press(self, event) -> None:
        coord = self._coord(event)
        start, end = self._track()
        length = max(1, end - start)
        if self._thumb_start <= coord <= self._thumb_start + self._thumb_len:
            self._drag_offset = coord - self._thumb_start
        else:
            self._drag_offset = self._thumb_len / 2
            fraction = (coord - start - self._drag_offset) / length
            self.command("moveto", max(0.0, min(1.0, fraction)))
        self._dragging = True
        self._draw()

    def _on_drag(self, event) -> None:
        if not self._dragging:
            return
        # 双保险：若释放事件丢失，通过按键掩码发现松开并复位
        if not (int(getattr(event, "state", 0)) & 0x0100):
            self._dragging = False
            self._draw()
            return
        coord = self._coord(event)
        start, end = self._track()
        length = max(1, end - start)
        fraction = (coord - start - self._drag_offset) / length
        self.command("moveto", max(0.0, min(1.0, fraction)))

    def _on_release(self, _event) -> None:
        self._dragging = False
        self._draw()

    def _on_enter(self, _event) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _event) -> None:
        # 拖动中移出区域是正常操作：保持拖动状态，直到 ButtonRelease-1
        self._hover = False
        if not self._dragging:
            self._draw()
