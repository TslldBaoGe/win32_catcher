"""从捕获快照生成可运行的 Python 定位代码。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import ElementCapture, SelectorStep, short_type


def _q(value: Any) -> str:
    return repr(value)


def _uia_control_type_expr(step: SelectorStep) -> str:
    name = step.control_type_name or ""
    if name:
        return f"auto.ControlType.{name}"
    return str(int(step.control_type or 0))


def _step_title(step: SelectorStep) -> str:
    bits = [step.control_type_name or "Control"]
    if step.name:
        bits.append(_q(step.name))
    elif step.automation_id:
        bits.append(_q(step.automation_id))
    elif step.class_name:
        bits.append(f"[{step.class_name}]")
    return " ".join(bits)


def _uia_top_args(step: SelectorStep) -> List[Tuple[str, str]]:
    args: List[Tuple[str, str]] = [("searchDepth", "1")]
    if step.control_type_name != "WindowControl":
        args.append(("ControlType", _uia_control_type_expr(step)))
    if step.name:
        args.append(("Name", _q(step.name)))
    if step.class_name:
        args.append(("ClassName", _q(step.class_name)))
    if step.automation_id:
        args.append(("AutomationId", _q(step.automation_id)))
    if step.found_index > 1:
        args.append(("foundIndex", str(step.found_index)))
    return args


def _uia_child_args(step: SelectorStep) -> List[Tuple[str, str]]:
    args: List[Tuple[str, str]] = [
        ("searchFromControl", "ctrl"),
        ("searchDepth", "1"),
        ("ControlType", _uia_control_type_expr(step)),
    ]
    if step.automation_id:
        args.append(("AutomationId", _q(step.automation_id)))
    if step.name:
        args.append(("Name", _q(step.name)))
    if step.class_name:
        args.append(("ClassName", _q(step.class_name)))
    if step.found_index > 1:
        args.append(("foundIndex", str(step.found_index)))
    return args


def _call_block(prefix: str, args: List[Tuple[str, str]], indent: int = 4) -> List[str]:
    pad = " " * indent
    lines = [f"{pad}{prefix}("]
    for key, value in args:
        lines.append(f"{pad}    {key}={value},")
    lines.append(f"{pad})")
    return lines


def _uia_top_call(step: SelectorStep, fallback: Optional[Dict[str, Any]] = None, indent: int = 4) -> List[str]:
    if fallback is None:
        args = _uia_top_args(step)
    else:
        args = [("searchDepth", "1")]
        if step.control_type_name != "WindowControl":
            args.append(("ControlType", _uia_control_type_expr(step)))
        if fallback.get("Name"):
            args.append(("Name", _q(fallback["Name"])))
        if fallback.get("ClassName"):
            args.append(("ClassName", _q(fallback["ClassName"])))
        if int(fallback.get("found_index") or 1) > 1:
            args.append(("foundIndex", str(int(fallback["found_index"]))))
    factory = "auto.WindowControl" if step.control_type_name == "WindowControl" else "auto.Control"
    return _call_block(f"ctrl = {factory}", args, indent)


def generate_uiautomation(capture: ElementCapture) -> str:
    lines: List[str] = []
    lines.append("# -*- coding: utf-8 -*-")
    lines.append('"""')
    lines.append("由 桌面元素捕获器 生成 · uiautomation")
    lines.append(f"目标: {capture.control_type_name} {capture.name!r}")
    lines.append(f"窗口: {capture.window_title!r}")
    lines.append(f"进程: {capture.process_name or '未知'} (PID {capture.process_id})")
    lines.append(f"捕获时间: {capture.date_label}")
    lines.append("依赖: pip install uiautomation")
    lines.append('"""')
    lines.append("")
    lines.append("import uiautomation as auto")
    lines.append("")
    lines.append("")
    lines.append("def locate(timeout: float = 5.0):")
    lines.append('    """按捕获时的 UI Automation 属性逐级重新定位控件。"""')
    lines.append("    auto.SetGlobalSearchTimeout(timeout)")
    lines.append("")

    if not capture.steps:
        lines.append("    ctrl = auto.GetRootControl()")
        lines.append("    return ctrl")
    else:
        total = len(capture.steps)
        top = capture.steps[0]
        lines.append(f"    # [1/{total}] 顶层: {_step_title(top)}")
        lines.extend(_uia_top_call(top))
        if top.fallback:
            lines.append("    if not ctrl.Exists(0, 0):")
            lines.append("        # 窗口标题可能变化，按窗口类名兜底")
            lines.extend(_uia_top_call(top, top.fallback, indent=8))
        lines.append("    if not ctrl.Exists(0, 0):")
        lines.append(f"        raise LookupError({_q('未找到顶层窗口: ' + _step_title(top))})")
        lines.append("")

        for index, step in enumerate(capture.steps[1:], start=2):
            lines.append(f"    # [{index}/{total}] {_step_title(step)}")
            lines.extend(_call_block("ctrl = auto.Control", _uia_child_args(step), 4))
            lines.append("    if not ctrl.Exists(0, 0):")
            lines.append(f"        raise LookupError({_q(f'未找到第 {index} 级控件: ' + _step_title(step))})")
            lines.append("")
        lines.append("    return ctrl")

    lines.append("")
    lines.append("")
    lines.append(_UIA_HIGHLIGHT_HELPER.rstrip())
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    control = locate()")
    lines.append("    rect = control.BoundingRectangle")
    lines.append('    print(f"已定位: {control.ControlTypeName} {control.Name!r}")')
    lines.append('    print(f"矩形: {rect}")')
    lines.append("    highlight(control, seconds=2.5)")
    lines.append("    # control.Click()  # 按需启用")
    lines.append("")
    return "\n".join(lines)


def _pywinauto_control_type(step: SelectorStep) -> str:
    name = (step.control_type_name or "").strip()
    if name.endswith("Control"):
        name = name[:-7]
    return name


def _pwa_top_args(step: SelectorStep, fallback: Optional[Dict[str, Any]] = None) -> List[Tuple[str, str]]:
    args: List[Tuple[str, str]] = []
    if fallback is None:
        if step.name:
            args.append(("title", _q(step.name)))
        if step.class_name:
            args.append(("class_name", _q(step.class_name)))
        found = step.found_index
    else:
        if fallback.get("Name"):
            args.append(("title", _q(fallback["Name"])))
        if fallback.get("ClassName"):
            args.append(("class_name", _q(fallback["ClassName"])))
        found = int(fallback.get("found_index") or 1)
    ctype = _pywinauto_control_type(step)
    if ctype:
        args.append(("control_type", _q(ctype)))
    args.append(("found_index", str(max(0, found - 1))))
    return args


def _pwa_child_args(step: SelectorStep) -> List[Tuple[str, str]]:
    args: List[Tuple[str, str]] = []
    if step.automation_id:
        args.append(("auto_id", _q(step.automation_id)))
    if step.name and step.window_text and step.window_text == step.name:
        args.append(("title", _q(step.name)))
    if step.class_name:
        args.append(("class_name", _q(step.class_name)))
    ctype = _pywinauto_control_type(step)
    if ctype:
        args.append(("control_type", _q(ctype)))
    args.append(("depth", "1"))
    args.append(("found_index", str(max(0, step.found_index - 1))))
    return args


def generate_pywinauto(capture: ElementCapture) -> str:
    lines: List[str] = []
    lines.append("# -*- coding: utf-8 -*-")
    lines.append('"""')
    lines.append("由 桌面元素捕获器 生成 · pywinauto")
    lines.append(f"目标: {capture.control_type_name} {capture.name!r}")
    lines.append(f"窗口: {capture.window_title!r}")
    lines.append(f"进程: {capture.process_name or '未知'} (PID {capture.process_id})")
    lines.append(f"捕获时间: {capture.date_label}")
    lines.append("依赖: pip install pywinauto")
    lines.append('"""')
    lines.append("")
    lines.append("from pywinauto import Desktop")
    lines.append("")
    lines.append("")
    lines.append("def locate(timeout: float = 5.0):")
    lines.append('    """按捕获时的 UI Automation 属性逐级重新定位控件。"""')
    lines.append("    backend = 'uia'")
    if not capture.steps:
        lines.append("    return Desktop(backend=backend).window(control_type='Desktop')")
    else:
        total = len(capture.steps)
        top = capture.steps[0]
        lines.append(f"    # [1/{total}] 顶层: {_step_title(top)}")
        lines.extend(_call_block("win = Desktop(backend=backend).window", _pwa_top_args(top), 4))
        if top.fallback:
            lines.append("    try:")
            lines.append("        win.wait('exists', timeout=timeout)")
            lines.append("    except Exception:")
            lines.append("        # 窗口标题可能变化，按窗口类名兜底")
            lines.extend(_call_block("win = Desktop(backend=backend).window", _pwa_top_args(top, top.fallback), 8))
            lines.append("        win.wait('exists', timeout=timeout)")
        else:
            lines.append("    win.wait('exists', timeout=timeout)")
        lines.append("    ctrl = win")
        lines.append("")

        anchor_lines = _anchor_locator_lines(capture)
        if anchor_lines:
            lines.extend(anchor_lines)
        else:
            for index, step in enumerate(capture.steps[1:], start=2):
                lines.append(f"    # [{index}/{total}] {_step_title(step)}")
                lines.extend(_call_block("ctrl = ctrl.child_window", _pwa_child_args(step), 4))
                lines.append("    ctrl.wait('exists', timeout=timeout)")
                lines.append("")
            lines.append("    return ctrl")

    lines.append("")
    lines.append("")
    lines.append(_PWA_HIGHLIGHT_HELPER.rstrip())
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    control = locate()")
    lines.append("    rect = control.rectangle()")
    lines.append('    name = control.window_text() or control.element_info.name')
    lines.append('    print(f"已定位: {control.element_info.control_type} {name!r}")')
    lines.append('    print(f"矩形: {rect}")')
    lines.append("    highlight(control, seconds=2.5)")
    lines.append("    # control.click_input()  # 按需启用")
    lines.append("")
    return "\n".join(lines)


def build_verify_harness(code_path: Path) -> str:
    """生成一个独立进程脚本：导入生成的模块，调用 locate() 并输出 JSON。"""
    return f'''# -*- coding: utf-8 -*-
import importlib.util
import json
import sys
from pathlib import Path

LOCATOR = Path(r"{str(code_path)}")
spec = importlib.util.spec_from_file_location("captured_locator", str(LOCATOR))
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def emit(payload):
    print("__ELEMENT_CATCHER_JSON__" + json.dumps(payload, ensure_ascii=False))


def main():
    try:
        ctrl = module.locate(5.0)
    except Exception as exc:
        print("__ELEMENT_CATCHER_ERROR__" + json.dumps(
            {{"error": f"{{type(exc).__name__}}: {{exc}}"}}, ensure_ascii=False))
        raise

    try:
        if not ctrl.__class__.__module__.startswith("pywinauto"):
            r = ctrl.BoundingRectangle
            payload = {{
                "mode": "uiautomation",
                "control_type": ctrl.ControlTypeName,
                "name": ctrl.Name or "",
                "automation_id": ctrl.AutomationId or "",
                "class_name": ctrl.ClassName or "",
                "process_id": int(ctrl.ProcessId),
                "rect": [int(r.left), int(r.top), int(r.right), int(r.bottom)],
            }}
        else:
            r = ctrl.rectangle()
            info = ctrl.element_info
            payload = {{
                "mode": "pywinauto",
                "control_type": info.control_type,
                "name": info.name or ctrl.window_text() or "",
                "automation_id": getattr(info, "automation_id", "") or "",
                "class_name": getattr(info, "class_name", "") or "",
                "process_id": int(getattr(info, "process_id", 0) or 0),
                "rect": [int(r.left), int(r.top), int(r.right), int(r.bottom)],
            }}
        emit(payload)
    except Exception as exc:
        print("__ELEMENT_CATCHER_ERROR__" + json.dumps(
            {{"error": f"{{type(exc).__name__}}: {{exc}}"}}, ensure_ascii=False))
        raise


if __name__ == "__main__":
    main()
'''


_UIA_HIGHLIGHT_HELPER = '''
def highlight(control, seconds: float = 2.5, color: str = "#2DD4BF") -> bool:
    """在屏幕上显示控件边框；置顶、鼠标穿透、不抢焦点。"""
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    import tkinter as tk

    rect = control.BoundingRectangle
    left, top, right, bottom = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return False
    user32 = ctypes.windll.user32
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    key = "#010101"
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=key)
    root.attributes("-transparentcolor", key)
    canvas = tk.Canvas(root, bg=key, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_rectangle(0, 0, width - 1, height - 1, outline=color, width=4)
    root.geometry(f"{width}x{height}+0+0")
    root.update_idletasks()
    hwnd = user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()
    ex = int(user32.GetWindowLongW(hwnd, -20))
    ex |= 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080
    user32.SetWindowLongW(hwnd, -20, ex)
    user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), left, top, width, height, 0x0010 | 0x0040 | 0x0200)
    root.after(int(seconds * 1000), root.destroy)
    root.mainloop()
    return True
'''


def _is_desktop_root_step(step: SelectorStep) -> bool:
    if step.control_type_name != "PaneControl":
        return False
    if step.class_name in ("#32769", "Progman"):
        return True
    name = (step.name or "").strip()
    return name in ("桌面 1", "Desktop 1", "Program Manager") or name.startswith("桌面 ")


def normalize_capture(capture: ElementCapture) -> ElementCapture:
    """修复旧记录里的桌面根节点，并用最新生成器重写代码。"""
    steps = list(capture.steps)
    if len(steps) > 1 and _is_desktop_root_step(steps[0]):
        steps = steps[1:]
        for index, step in enumerate(steps):
            step.is_top_level = index == 0
        if steps and steps[0].control_type_name == "WindowControl":
            if steps[0].name:
                capture.window_title = steps[0].name
            if steps[0].class_name:
                capture.window_class = steps[0].class_name
            if steps[0].is_top_level:
                capture.steps = steps
    if len(steps) != len(capture.steps):
        capture.steps = steps
    try:
        capture.uia_code = generate_uiautomation(capture)
        capture.pywinauto_code = generate_pywinauto(capture)
        capture.uia_compact_code = generate_uiautomation_compact(capture)
        capture.pywinauto_compact_code = generate_pywinauto_compact(capture)
        capture.pwa_rel_code = generate_pywinauto_relative(capture)
    except Exception:
        pass
    return capture


_PWA_HIGHLIGHT_HELPER = _UIA_HIGHLIGHT_HELPER.replace(
    "rect = control.BoundingRectangle",
    "rect = control.rectangle()",
)


def _compact_uia_target(capture: ElementCapture) -> Tuple[str, Dict[str, Any]]:
    """返回 (控件工厂方法名, 搜索属性)。"""
    last = capture.steps[-1]
    type_name = last.control_type_name or "Control"
    props: Dict[str, Any] = {}
    if last.automation_id:
        props["AutomationId"] = last.automation_id
    elif last.name and not _looks_like_volatile_name(last.name):
        props["Name"] = last.name
        if last.class_name:
            props["ClassName"] = last.class_name
    elif last.class_name:
        props["ClassName"] = last.class_name
    elif last.name:
        props["Name"] = last.name
    return type_name, props


def _looks_like_volatile_name(name: str) -> bool:
    import re as _re

    if len(name) > 80:
        return True
    if _re.search(r"\d{2,}", name):
        return True
    if _re.search(r"\d+%|\d+:\d+|https?://|www\.", name, _re.I):
        return True
    if _re.search(r"\b(line|column|position|index|item|row|cell)\b", name, _re.I):
        return True
    return False


def _pwa_compact_target(capture: ElementCapture) -> Dict[str, Any]:
    last = capture.steps[-1]
    props: Dict[str, Any] = {}
    ctype = _pywinauto_control_type(last)
    if ctype:
        props["control_type"] = _q(ctype)
    if last.automation_id:
        props["auto_id"] = _q(last.automation_id)
    elif last.name and last.window_text and last.window_text == last.name and not _looks_like_volatile_name(last.name):
        props["title"] = _q(last.name)
        if last.class_name:
            props["class_name"] = _q(last.class_name)
    elif last.class_name:
        props["class_name"] = _q(last.class_name)
    elif last.name:
        props["title"] = _q(last.name)
    props["found_index"] = "0"
    return props


# 极简版生成器已拆分到 catcher/compact_codegen.py
from .compact_codegen import (  # noqa: E402,F401
    generate_pywinauto_compact,
    generate_uiautomation_compact,
)
from .rel_codegen import (  # noqa: E402,F401
    _anchor_locator_lines,
    generate_pywinauto_relative,
)
