"""极简定位代码生成：无兜底、无显式等待，直接贴进自己的代码。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .models import ElementCapture


def _q(value: Any) -> str:
    return repr(value)


def _pywinauto_control_type(step) -> str:
    name = (step.control_type_name or "").strip()
    if name.endswith("Control"):
        name = name[:-7]
    return name


def _looks_like_volatile_name(name: str) -> bool:
    if not name:
        return True
    if len(name) > 80:
        return True
    if re.search(r"\d{2,}", name):
        return True
    if re.search(r"\d+%|\d+:\d+|https?://|www\.", name, re.I):
        return True
    if re.search(r"\b(line|column|position|index|item|row|cell)\b", name, re.I):
        return True
    return False


def _uia_target(capture: ElementCapture) -> Tuple[str, Dict[str, Any]]:
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


def _pwa_target(capture: ElementCapture) -> Dict[str, Any]:
    last = capture.steps[-1]
    props: Dict[str, Any] = {}
    ctype = _pywinauto_control_type(last)
    if ctype:
        props["control_type"] = _q(ctype)
    if last.automation_id:
        props["auto_id"] = _q(last.automation_id)
    elif (
        last.name
        and last.window_text
        and last.window_text == last.name
        and not _looks_like_volatile_name(last.name)
    ):
        props["title"] = _q(last.name)
        if last.class_name:
            props["class_name"] = _q(last.class_name)
    elif last.class_name:
        props["class_name"] = _q(last.class_name)
    elif last.name:
        props["title"] = _q(last.name)
    props["found_index"] = "0"
    return props


def generate_uiautomation_compact(capture: ElementCapture) -> str:
    """极简版：无兜底、无显式等待，靠懒查找按全局超时定位。"""
    if not capture.steps:
        return (
            "# 极简定位 · 桌面根节点\n"
            "import uiautomation as auto\n"
            "\n"
            "\n"
            "def locate(timeout: float = 5.0):\n"
            "    return auto.GetRootControl()\n"
        )
    top = capture.steps[0]
    type_name, target_props = _uia_target(capture)
    search_depth = max(4, min(12, len(capture.steps) + 2))

    win_args: List[str] = []
    if top.name:
        win_args.append(f"Name={_q(top.name)}")
    if top.class_name:
        win_args.append(f"ClassName={_q(top.class_name)}")
    if top.control_type_name != "WindowControl":
        win_args.append(f"ControlType=auto.ControlType.{top.control_type_name}")
    if top.found_index > 1:
        win_args.append(f"foundIndex={top.found_index}")
    win_call = f"auto.WindowControl(searchDepth=1{', ' + ', '.join(win_args) if win_args else ''})"

    if len(capture.steps) == 1:
        body = "    return win\n"
    else:
        prop_args = ", ".join(f"{k}={_q(v)}" for k, v in target_props.items())
        body = (
            f"    target = win.{type_name}(searchDepth={search_depth}{', ' + prop_args if prop_args else ''})\n"
            f"    return target\n"
        )

    return (
        f"# 极简定位 · {capture.control_type_name} {capture.name!r} · 窗口 {capture.window_title!r}\n"
        f"import uiautomation as auto\n"
        f"\n"
        f"\n"
        f"def locate(timeout: float = 5.0):\n"
        f"    auto.SetGlobalSearchTimeout(timeout)\n"
        f"    win = {win_call}\n"
        f"{body}"
    )


def generate_pywinauto_compact(capture: ElementCapture) -> str:
    """极简版：无兜底、无显式等待，靠 pywinauto 惰性解析。"""
    if not capture.steps:
        return (
            "# 极简定位 · 桌面根节点\n"
            "from pywinauto import Desktop\n"
            "\n"
            "\n"
            "def locate(timeout: float = 5.0):\n"
            "    return Desktop(backend='uia')\n"
        )
    top = capture.steps[0]
    target_props = _pwa_target(capture)

    win_args: List[str] = []
    if top.name:
        win_args.append(f"title={_q(top.name)}")
    if top.class_name:
        win_args.append(f"class_name={_q(top.class_name)}")
    ctype = _pywinauto_control_type(top)
    if ctype:
        win_args.append(f"control_type={_q(ctype)}")
    win_args.append("found_index=0")
    win_call = f"Desktop(backend='uia').window({', '.join(win_args)})"

    if len(capture.steps) == 1:
        body = "    return win\n"
    else:
        target_args = ", ".join(f"{k}={v}" for k, v in target_props.items())
        body = (
            f"    target = win.child_window({target_args})\n"
            f"    return target\n"
        )

    return (
        f"# 极简定位 · {capture.control_type_name} {capture.name!r} · 窗口 {capture.window_title!r}\n"
        f"from pywinauto import Desktop, timings\n"
        f"\n"
        f"\n"
        f"def locate(timeout: float = 5.0):\n"
        f"    timings.Timings.window_find_timeout = timeout\n"
        f"    win = {win_call}\n"
        f"{body}"
    )
