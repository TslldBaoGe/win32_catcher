"""pwa 相对定位代码生成：锚点文本 + 同级索引偏移（pywinauto）。"""
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


def _window_args(step) -> str:
    args: List[str] = []
    name = step.name or ""
    if name and not _looks_like_volatile_name(name):
        args.append(f"title={_q(name)}")
    if step.class_name:
        args.append(f"class_name={_q(step.class_name)}")
    ctype = _pywinauto_control_type(step)
    if ctype:
        args.append(f"control_type={_q(ctype)}")
    args.append("found_index=0")
    return ", ".join(args)


def _child_args(step) -> str:
    args: List[str] = []
    if step.automation_id:
        args.append(f"auto_id={_q(step.automation_id)}")
    if step.name and step.window_text and step.window_text == step.name:
        args.append(f"title={_q(step.name)}")
    if step.class_name:
        args.append(f"class_name={_q(step.class_name)}")
    ctype = _pywinauto_control_type(step)
    if ctype:
        args.append(f"control_type={_q(ctype)}")
    args.append(f"found_index={max(0, step.found_index - 1)}")
    return ", ".join(args)


def _pick_anchor(texts: List[str], target_index: int) -> Tuple[int, str]:
    """从同级文本里挑最稳定、唯一、离目标最近的锚点。返回 (锚点序号, 文本)。"""
    best: Tuple[int, int, str] = (10**9, 10**9, "")
    found = False
    for i, t in enumerate(texts, start=1):
        if i == target_index:
            continue
        ts = t.strip()
        if not ts or _looks_like_volatile_name(ts):
            continue
        if texts.count(t) != 1:
            continue
        dist = abs(i - target_index)
        if not found or (dist, i) < (best[0], best[1]):
            best = (dist, i, t)
            found = True
    if not found:
        return 0, ""
    return best[1], best[2]


def generate_pywinauto_relative(capture: ElementCapture) -> str:
    """相对定位：不依赖唯一 ID，用锚点文本 + 同级索引偏移找目标。"""
    if not capture.steps:
        return (
            "# 相对定位 · 桌面根节点\n"
            "from pywinauto import Desktop\n"
            "\n"
            "\n"
            "def locate(timeout: float = 5.0):\n"
            "    return Desktop(backend='uia')\n"
        )

    top = capture.steps[0]
    steps = capture.steps
    lines: List[str] = []
    lines.append(f"# 相对定位 · {capture.control_type_name} {capture.name!r} · 窗口 {capture.window_title!r}")
    lines.append("# 思路：容器用属性定位，目标用同级文本锚点 + 索引偏移（适合无 AutomationId 的 WinForms 程序）")
    lines.append("from pywinauto import Desktop, timings")
    lines.append("")
    lines.append("")
    lines.append("def locate(timeout: float = 5.0):")
    lines.append("    timings.Timings.window_find_timeout = timeout")
    lines.append(f"    win = Desktop(backend='uia').window({_window_args(top)})")
    lines.append("    win.wait('exists', timeout=timeout)")

    if len(steps) == 1:
        lines.append("    return win")
        return "\n".join(lines) + "\n"

    container = "win"
    intermediates = 0
    for step in steps[1:-1]:
        lines.append(f"    container = {container}.child_window({_child_args(step)})")
        container = "container"
        intermediates += 1
    if intermediates == 0:
        lines.append("    container = win")

    body: List[str] = []
    rel_texts = capture.rel_texts or []
    rel_index = capture.rel_index
    anchor_index, anchor_text = _pick_anchor(rel_texts, rel_index) if rel_texts else (0, "")
    if anchor_index and rel_index:
        offset = anchor_index - rel_index
        op = f"- {offset}" if offset >= 0 else f"+ {abs(offset)}"
        body.append(f"    texts = [c.window_text() for c in container.children()]")
        body.append(f"    target = container.children()[texts.index({_q(anchor_text)}) {op}]")
        body.append("    return target")
    else:
        lines.append("    # 未记录到可用的同级锚点，退回属性定位")
        target_args = _child_args(steps[-1])
        body.append(f"    target = container.child_window({target_args})")
        body.append("    return target")

    return "\n".join(lines + body) + "\n"
