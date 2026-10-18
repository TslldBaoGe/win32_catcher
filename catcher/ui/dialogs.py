"""与暗色主题一致的输入/取值/设置对话框。"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Optional

from ..winutil import monitor_work_area
from .widgets import RoundedButton


class _ModalDialog:
    def __init__(self, parent: tk.Misc, theme, title: str, width: int, height: int) -> None:
        self.parent = parent
        self.theme = theme
        self.result = None
        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=theme.border)
        outer = tk.Frame(self.win, bg=theme.border)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        self.body = tk.Frame(outer, bg=theme.surface)
        self.body.pack(fill="both", expand=True)
        header = tk.Frame(self.body, bg=theme.surface_2)
        header.pack(fill="x")
        header.bind("<Button-1>", self._start_drag)
        header.bind("<B1-Motion>", self._drag)
        tk.Label(
            header,
            text=title,
            bg=theme.surface_2,
            fg=theme.text,
            font=theme.font_small_bold,
            anchor="w",
        ).pack(side="left", padx=theme.px(12), pady=theme.px(8))
        close = tk.Label(
            header,
            text="✕",
            bg=theme.surface_2,
            fg=theme.faint,
            font=theme.font_small_bold,
            cursor="hand2",
            padx=theme.px(10),
            pady=theme.px(7),
        )
        close.pack(side="right")
        close.bind("<Button-1>", lambda _e: self._cancel())
        close.bind("<Enter>", lambda _e: close.configure(fg=theme.red))
        close.bind("<Leave>", lambda _e: close.configure(fg=theme.faint))

        self.content = tk.Frame(self.body, bg=theme.surface)
        self.content.pack(fill="both", expand=True, padx=theme.px(14), pady=(theme.px(12), theme.px(6)))
        self.footer = tk.Frame(self.body, bg=theme.surface)
        self.footer.pack(fill="x", padx=theme.px(14), pady=(0, theme.px(12)))

        self._width = width
        self._height = height
        self._drag_origin = (0, 0)

    def _start_drag(self, event) -> None:
        self._drag_origin = (event.x_root - self.win.winfo_x(), event.y_root - self.win.winfo_y())

    def _drag(self, event) -> None:
        x = event.x_root - self._drag_origin[0]
        y = event.y_root - self._drag_origin[1]
        self.win.geometry(f"+{x}+{y}")

    def _center(self) -> None:
        self.win.update_idletasks()
        width = max(self._width, self.win.winfo_reqwidth())
        height = max(self._height, self.win.winfo_reqheight())
        try:
            px = self.parent.winfo_rootx()
            py = self.parent.winfo_rooty()
            pw = self.parent.winfo_width()
            ph = self.parent.winfo_height()
        except Exception:
            px = py = 0
            pw = ph = 1
        x = px + (pw - width) // 2
        y = py + (ph - height) // 2
        work = monitor_work_area(x + width // 2, y + height // 2)
        margin = self.theme.px(8)
        x = max(work[0] + margin, min(x, work[2] - width - margin))
        y = max(work[1] + margin, min(y, work[3] - height - margin))
        self.win.geometry(f"{width}x{height}+{x}+{y}")

    def show(self):
        self._center()
        self.win.deiconify()
        self.win.lift()
        try:
            self.win.grab_set()
        except Exception:
            pass
        self.win.focus_force()
        self.parent.wait_window(self.win)
        return self.result

    def _cancel(self) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass


def ask_text(
    parent: tk.Misc,
    theme,
    title: str,
    prompt: str,
    initial: str = "",
) -> Optional[str]:
    dialog = _ModalDialog(parent, theme, title, theme.px(420), theme.px(190))
    tk.Label(
        dialog.content,
        text=prompt,
        bg=theme.surface,
        fg=theme.muted,
        font=theme.font_small,
        anchor="w",
        justify="left",
        wraplength=theme.px(380),
    ).pack(fill="x", pady=(0, theme.px(8)))

    entry = tk.Entry(
        dialog.content,
        bg=theme.surface_2,
        fg=theme.text,
        insertbackground=theme.accent,
        selectbackground=theme.selection,
        selectforeground=theme.text,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=theme.border,
        highlightcolor=theme.accent,
        font=theme.font_body,
    )
    entry.pack(fill="x", ipady=theme.px(6))
    entry.insert(0, initial)
    entry.select_range(0, "end")
    entry.focus_set()

    hint = tk.Label(
        dialog.content,
        text="提示：支持 ValuePattern 的控件会直接写入；否则会聚焦控件并发送按键。",
        bg=theme.surface,
        fg=theme.faint,
        font=theme.font_tiny,
        anchor="w",
        justify="left",
        wraplength=theme.px(380),
    )
    hint.pack(fill="x", pady=(theme.px(8), 0))

    def confirm(_event=None) -> None:
        dialog.result = entry.get()
        dialog._close()

    RoundedButton(
        dialog.footer,
        theme,
        "取消",
        command=dialog._cancel,
        kind="ghost",
        width=theme.px(72),
        height=theme.px(34),
        font=theme.font_small_bold,
    ).pack(side="right", padx=(theme.px(8), 0))
    RoundedButton(
        dialog.footer,
        theme,
        "确定",
        command=confirm,
        kind="primary",
        width=theme.px(72),
        height=theme.px(34),
        font=theme.font_small_bold,
    ).pack(side="right")

    dialog.win.bind("<Return>", confirm)
    dialog.win.bind("<Escape>", lambda _e: dialog._cancel())
    return dialog.show()


def show_value(
    parent: tk.Misc,
    theme,
    title: str,
    value: str,
    source: str = "",
) -> None:
    dialog = _ModalDialog(parent, theme, title, theme.px(560), theme.px(320))
    if source:
        tk.Label(
            dialog.content,
            text=f"来源：{source}",
            bg=theme.surface,
            fg=theme.faint,
            font=theme.font_tiny,
            anchor="w",
        ).pack(fill="x", pady=(0, theme.px(6)))

    text = tk.Text(
        dialog.content,
        bg=theme.code_bg,
        fg=theme.code_text,
        insertbackground=theme.accent,
        selectbackground=theme.selection,
        selectforeground=theme.text,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=theme.border,
        highlightcolor=theme.border,
        font=theme.font_code,
        wrap="word",
        height=8,
        padx=theme.px(8),
        pady=theme.px(8),
    )
    text.pack(fill="both", expand=True)
    text.insert("1.0", value if value else "（空值）")
    text.configure(state="disabled")

    status = tk.Label(
        dialog.footer,
        text="",
        bg=theme.surface,
        fg=theme.green,
        font=theme.font_tiny,
        anchor="w",
    )
    status.pack(side="left")

    def copy_value() -> None:
        try:
            dialog.win.clipboard_clear()
            dialog.win.clipboard_append(value)
            status.configure(text="已复制到剪贴板")
        except Exception:
            status.configure(text="复制失败", fg=theme.red)

    RoundedButton(
        dialog.footer,
        theme,
        "关闭",
        command=dialog._close,
        kind="ghost",
        width=theme.px(72),
        height=theme.px(34),
        font=theme.font_small_bold,
    ).pack(side="right", padx=(theme.px(8), 0))
    RoundedButton(
        dialog.footer,
        theme,
        "复制",
        command=copy_value,
        kind="primary",
        width=theme.px(72),
        height=theme.px(34),
        font=theme.font_small_bold,
    ).pack(side="right")

    dialog.win.bind("<Escape>", lambda _e: dialog._close())
    dialog.show()


def show_settings(parent: tk.Misc, theme, python_exe: str = "") -> Optional[str]:
    """设置对话框：指定独立进程回放使用的 Python/Miniconda 解释器。

    返回保存后的解释器路径；取消返回 None。
    """
    import subprocess
    import sys
    import threading
    import tkinter.filedialog as filedialog
    import tkinter.ttk as ttk

    from ..settings import scan_python_envs

    dialog = _ModalDialog(parent, theme, "设置 · Python 环境", theme.px(660), theme.px(400))

    tk.Label(
        dialog.content,
        text="独立进程回放（验证 / 元素操作定位）使用的 Python 解释器：",
        bg=theme.surface,
        fg=theme.muted,
        font=theme.font_small,
        anchor="w",
        justify="left",
        wraplength=theme.px(600),
    ).pack(fill="x", pady=(0, theme.px(6)))

    entry_row = tk.Frame(dialog.content, bg=theme.surface)
    entry_row.pack(fill="x")
    entry = tk.Entry(
        entry_row,
        bg=theme.surface_2,
        fg=theme.text,
        insertbackground=theme.accent,
        selectbackground=theme.selection,
        selectforeground=theme.text,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=theme.border,
        highlightcolor=theme.accent,
        font=theme.font_small,
    )
    entry.pack(side="left", fill="x", expand=True, ipady=theme.px(5))
    entry.insert(0, python_exe)

    def current_value() -> str:
        return entry.get().strip().strip('"')

    def set_entry(value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)

    env_row = tk.Frame(dialog.content, bg=theme.surface)
    env_row.pack(fill="x", pady=(theme.px(8), 0))
    tk.Label(
        env_row,
        text="检测到的环境",
        bg=theme.surface,
        fg=theme.faint,
        font=theme.font_tiny,
    ).pack(side="left", padx=(0, theme.px(8)))

    style = ttk.Style(dialog.win)
    style.configure(
        "Settings.TCombobox",
        fieldbackground=theme.surface_2,
        background=theme.surface_2,
        foreground=theme.text,
        arrowcolor=theme.text,
        bordercolor=theme.border,
        lightcolor=theme.border,
        darkcolor=theme.border,
    )
    style.map(
        "Settings.TCombobox",
        fieldbackground=[("readonly", theme.surface_2)],
        foreground=[("readonly", theme.text)],
    )
    dialog.win.option_add("*TCombobox*Listbox.background", theme.surface_2)
    dialog.win.option_add("*TCombobox*Listbox.foreground", theme.text)
    dialog.win.option_add("*TCombobox*Listbox.selectBackground", theme.selection)
    dialog.win.option_add("*TCombobox*Listbox.selectForeground", theme.text)

    env_combo = ttk.Combobox(env_row, values=[], state="readonly", style="Settings.TCombobox", font=theme.font_tiny)
    env_combo.pack(side="left", fill="x", expand=True)
    env_combo.bind("<<ComboboxSelected>>", lambda _e: set_entry(env_combo.get()))

    status = tk.Label(
        dialog.content,
        text="",
        bg=theme.surface,
        fg=theme.muted,
        font=theme.font_tiny,
        anchor="w",
        justify="left",
        wraplength=theme.px(600),
    )

    def scan_envs() -> None:
        found = scan_python_envs(current_value())
        if not found:
            status.configure(text="未扫描到环境，可直接填写 python.exe 路径", fg=theme.amber)
            return
        env_combo.configure(values=found)
        if len(found) == 1:
            set_entry(found[0])
        status.configure(text=f"扫描到 {len(found)} 个环境，下拉选择或直接填写", fg=theme.green)

    def browse() -> None:
        initial_dir = ""
        value = current_value()
        if value:
            value_path = Path(value)
            initial_dir = str(value_path.parent if value_path.is_file() else value_path)
        chosen = filedialog.askopenfilename(
            parent=dialog.win,
            title="选择 python.exe",
            initialdir=initial_dir or None,
            filetypes=[("python", "python*.exe"), ("所有文件", "*.*")],
        )
        if chosen:
            set_entry(chosen)

    def check_deps() -> None:
        exe = current_value()
        if not exe or not Path(exe).exists():
            status.configure(text="路径不存在，请先填写有效的 python.exe", fg=theme.red)
            return
        if "python" not in Path(exe).name.lower():
            status.configure(text="所选文件看起来不是 Python 解释器", fg=theme.amber)
            return
        status.configure(text="正在检测依赖…", fg=theme.muted)

        def worker() -> None:
            packages = (
                ("uiautomation", "uiautomation"),
                ("pywinauto", "pywinauto"),
                ("PIL", "Pillow"),
                ("psutil", "psutil"),
            )
            results = []
            for import_name, display in packages:
                try:
                    proc = subprocess.run(
                        [exe, "-c", f"import {import_name}"],
                        capture_output=True,
                        timeout=30,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    ok = proc.returncode == 0
                except Exception as exc:
                    ok = False
                    display = f"{display}({exc})"
                results.append((display, ok))
            marks = "  ".join(f"{'OK' if ok else '缺'} {name}" for name, ok in results)
            all_ok = all(ok for _name, ok in results)

            def update() -> None:
                try:
                    status.configure(
                        text=(f"依赖齐全：{marks}" if all_ok else f"依赖缺失：{marks}"),
                        fg=theme.green if all_ok else theme.amber,
                    )
                except Exception:
                    pass

            dialog.win.after(0, update)

        threading.Thread(target=worker, name="dep-check", daemon=True).start()

    buttons_row = tk.Frame(dialog.content, bg=theme.surface)
    buttons_row.pack(fill="x", pady=(theme.px(10), 0))
    RoundedButton(
        buttons_row,
        theme,
        "浏览…",
        command=browse,
        kind="secondary",
        width=theme.px(70),
        height=theme.px(30),
        font=theme.font_tiny_bold,
    ).pack(side="left", padx=(0, theme.px(5)))
    RoundedButton(
        buttons_row,
        theme,
        "扫描环境",
        command=scan_envs,
        kind="secondary",
        width=theme.px(80),
        height=theme.px(30),
        font=theme.font_tiny_bold,
        tooltip="扫描当前/常见 Miniconda 位置下的环境",
    ).pack(side="left", padx=(0, theme.px(5)))
    RoundedButton(
        buttons_row,
        theme,
        "检测依赖",
        command=check_deps,
        kind="secondary",
        width=theme.px(80),
        height=theme.px(30),
        font=theme.font_tiny_bold,
    ).pack(side="left", padx=(0, theme.px(5)))

    status.pack(fill="x", pady=(theme.px(8), 0))

    def save() -> None:
        exe = current_value()
        if not exe or not Path(exe).exists():
            status.configure(text="路径不存在，无法保存", fg=theme.red)
            return
        if "python" not in Path(exe).name.lower():
            status.configure(text="所选文件看起来不是 Python 解释器，无法保存", fg=theme.red)
            return
        dialog.result = exe
        dialog._close()

    def reset_default() -> None:
        set_entry(sys.executable)

    RoundedButton(
        dialog.footer,
        theme,
        "恢复默认",
        command=reset_default,
        kind="ghost",
        width=theme.px(80),
        height=theme.px(34),
        font=theme.font_small_bold,
        tooltip="使用正在运行捕获器的解释器",
    ).pack(side="left")
    RoundedButton(
        dialog.footer,
        theme,
        "取消",
        command=dialog._cancel,
        kind="ghost",
        width=theme.px(72),
        height=theme.px(34),
        font=theme.font_small_bold,
    ).pack(side="right", padx=(theme.px(8), 0))
    RoundedButton(
        dialog.footer,
        theme,
        "保存",
        command=save,
        kind="primary",
        width=theme.px(72),
        height=theme.px(34),
        font=theme.font_small_bold,
    ).pack(side="right")

    dialog.win.bind("<Escape>", lambda _e: dialog._cancel())
    dialog.win.bind("<Return>", lambda _e: save())
    return dialog.show()
