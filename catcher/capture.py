"""UI Automation 元素捕获与稳定定位路径构建。"""
from __future__ import annotations

import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psutil
import uiautomation as auto

from .codegen import (
    generate_pywinauto,
    generate_pywinauto_compact,
    generate_uiautomation,
    generate_uiautomation_compact,
)
from .rel_codegen import generate_pywinauto_relative
from .models import ElementCapture, SelectorStep, control_type_label, short_type
from .winutil import (
    get_window_text,
    virtual_screen_rect,
)

try:
    from PIL import Image, ImageGrab
except Exception:  # pragma: no cover - Pillow 是硬依赖，但避免导入期崩溃
    Image = None  # type: ignore[assignment]
    ImageGrab = None  # type: ignore[assignment]


class CaptureError(RuntimeError):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass
class HoverInfo:
    control_type_name: str
    localized_type: str
    name: str
    automation_id: str
    class_name: str
    rect: Tuple[int, int, int, int]
    process_id: int
    process_name: str
    framework_id: str

    @property
    def type_label(self) -> str:
        return control_type_label(self.control_type_name)

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.automation_id.strip() or self.class_name.strip() or "(无名称)"


@dataclass
class _Snap:
    ctrl: Any
    rid: Tuple[Any, ...]
    control_type: int
    control_type_name: str
    name: str
    automation_id: str
    class_name: str
    window_text: str
    native_handle: int
    process_id: int
    rect: Tuple[int, int, int, int]


_PROC_CACHE: Dict[int, Tuple[str, str]] = {}
_PROC_LOCK = threading.Lock()


def _process_info(pid: int) -> Tuple[str, str]:
    if not pid:
        return "", ""
    with _PROC_LOCK:
        if pid in _PROC_CACHE:
            return _PROC_CACHE[pid]
    name = ""
    exe = ""
    try:
        proc = psutil.Process(pid)
        name = proc.name() or ""
        try:
            exe = proc.exe() or ""
        except Exception:
            exe = ""
    except Exception:
        pass
    with _PROC_LOCK:
        _PROC_CACHE[pid] = (name, exe)
    return name, exe


def _safe(fn, default=""):
    try:
        value = fn()
        return default if value is None else value
    except Exception:
        return default


def _safe_int(fn, default: int = 0) -> int:
    try:
        return int(fn())
    except Exception:
        return default


def _safe_bool(fn, default: bool = False) -> bool:
    try:
        return bool(fn())
    except Exception:
        return default


def _rect_tuple(ctrl: Any) -> Tuple[int, int, int, int]:
    try:
        r = ctrl.BoundingRectangle
        return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:
        return (0, 0, 0, 0)


def _rid(ctrl: Any) -> Tuple[Any, ...]:
    try:
        rid = ctrl.GetRuntimeId()
        if rid:
            return tuple(int(v) for v in rid)
    except Exception:
        pass
    try:
        r = ctrl.BoundingRectangle
        return (
            "fallback",
            int(ctrl.NativeWindowHandle),
            int(ctrl.ControlType),
            int(r.left),
            int(r.top),
            int(r.right),
            int(r.bottom),
        )
    except Exception:
        return ("unknown", id(ctrl))


def _looks_volatile(name: str) -> bool:
    if not name:
        return False
    if len(name) > 80:
        return True
    if re.search(r"\d{2,}", name):
        return True
    if re.search(r"\d+%|\d+:\d+|https?://|www\.", name, re.I):
        return True
    if re.search(r"\b(line|column|position|index|item|row|cell)\b", name, re.I):
        return True
    if re.search(r"(第\s*\d+|共\s*\d+|\d+\s*个|\d+\s*项)", name):
        return True
    return False


def _snapshot(ctrl: Any, is_top: bool = False) -> _Snap:
    name = str(_safe(lambda: ctrl.Name, "") or "")
    aid = str(_safe(lambda: ctrl.AutomationId, "") or "")
    cls = str(_safe(lambda: ctrl.ClassName, "") or "")
    type_name = str(_safe(lambda: ctrl.ControlTypeName, "") or "")
    ctype = _safe_int(lambda: ctrl.ControlType, 0)
    native = _safe_int(lambda: ctrl.NativeWindowHandle, 0)
    if is_top:
        window_text = name
    elif native:
        window_text = get_window_text(native)
    else:
        window_text = name
    return _Snap(
        ctrl=ctrl,
        rid=_rid(ctrl),
        control_type=ctype,
        control_type_name=type_name,
        name=name,
        automation_id=aid,
        class_name=cls,
        window_text=window_text,
        native_handle=native,
        process_id=_safe_int(lambda: ctrl.ProcessId, 0),
        rect=_rect_tuple(ctrl),
    )


def _matches(snap: _Snap, props: Dict[str, Any]) -> bool:
    for key, value in props.items():
        if key == "ControlType":
            if snap.control_type != int(value):
                return False
        elif key == "Name":
            if snap.name != value:
                return False
        elif key == "AutomationId":
            if snap.automation_id != value:
                return False
        elif key == "ClassName":
            if snap.class_name != value:
                return False
    return True


def _candidate_sets(snap: _Snap, is_top: bool) -> List[Dict[str, Any]]:
    ct = snap.control_type
    name = snap.name
    aid = snap.automation_id
    cls = snap.class_name
    candidates: List[Dict[str, Any]] = []
    if is_top:
        if name and cls:
            candidates.append({"ControlType": ct, "Name": name, "ClassName": cls})
        if cls:
            candidates.append({"ControlType": ct, "ClassName": cls})
        if name:
            candidates.append({"ControlType": ct, "Name": name})
        candidates.append({"ControlType": ct})
    else:
        if aid:
            candidates.append({"ControlType": ct, "AutomationId": aid})
            if cls:
                candidates.append({"ControlType": ct, "AutomationId": aid, "ClassName": cls})
            if name:
                candidates.append({"ControlType": ct, "AutomationId": aid, "Name": name})
        if name and not _looks_volatile(name):
            candidates.append({"ControlType": ct, "Name": name})
        if cls:
            candidates.append({"ControlType": ct, "ClassName": cls})
        if name and cls:
            candidates.append({"ControlType": ct, "Name": name, "ClassName": cls})
        if name and _looks_volatile(name):
            candidates.append({"ControlType": ct, "Name": name})
        candidates.append({"ControlType": ct})

    # 去重并保持顺序
    seen = set()
    unique: List[Dict[str, Any]] = []
    for candidate in candidates:
        key = tuple(sorted(candidate.items()))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _stability(snap: _Snap, props: Dict[str, Any], is_top: bool) -> int:
    if "AutomationId" in props:
        return 0
    if is_top:
        if "ClassName" in props and "Name" in props:
            return 1
        if "ClassName" in props:
            return 2
        if "Name" in props:
            return 3
        return 4
    if "Name" in props and not _looks_volatile(snap.name):
        return 1
    if "ClassName" in props:
        return 2
    if "Name" in props:
        return 3
    return 4


def _choose_selector(
    target: _Snap,
    siblings: Sequence[_Snap],
    is_top: bool,
) -> Tuple[Dict[str, Any], int, int]:
    best: Optional[Tuple[Tuple[int, int, int], Dict[str, Any], int, int]] = None
    for props in _candidate_sets(target, is_top):
        matches = [s for s in siblings if _matches(s, props)]
        target_index = None
        for index, snap in enumerate(matches, start=1):
            if snap.rid == target.rid:
                target_index = index
                break
        if target_index is None:
            continue
        score = (len(matches), _stability(target, props, is_top), len(props))
        if best is None or score < best[0]:
            best = (score, props, target_index, len(matches))

    if best is not None:
        _, props, target_index, match_count = best
        return dict(props), target_index, match_count

    # 极端情况下（目标不在兄弟列表里）按类型 + 顺序兜底
    type_matches = [s for s in siblings if s.control_type == target.control_type]
    target_index = 1
    for index, snap in enumerate(type_matches, start=1):
        if snap.rid == target.rid:
            target_index = index
            break
    return {"ControlType": target.control_type}, target_index, max(1, len(type_matches))


def _fallback_props(target: _Snap, siblings: Sequence[_Snap], is_top: bool) -> Optional[Dict[str, Any]]:
    if not is_top or not target.class_name:
        return None
    props = {"ControlType": target.control_type, "ClassName": target.class_name}
    matches = [s for s in siblings if _matches(s, props)]
    target_index = None
    for index, snap in enumerate(matches, start=1):
        if snap.rid == target.rid:
            target_index = index
            break
    if target_index is None:
        return None
    return {
        "Name": "",
        "ClassName": target.class_name,
        "ControlType": target.control_type,
        "found_index": target_index,
        "match_count": len(matches),
    }


def _display_for(snap: _Snap) -> str:
    label = short_type(snap.control_type_name)
    name = snap.name.strip()
    if name:
        name = name.replace("\n", " ")[:60]
        return f'{label} "{name}"'
    if snap.automation_id:
        return f"{label} #{snap.automation_id}"
    if snap.class_name:
        return f"{label} [{snap.class_name}]"
    return label


def find_anchor_control(ctrl: Any) -> Any:
    """返回最高的非桌面根祖先；桌面根不作为定位路径的一部分。"""
    try:
        root = auto.GetRootControl()
        root_rid = _rid(root)
    except Exception:
        return ctrl
    current = ctrl
    best = ctrl
    seen = set()
    for _ in range(32):
        current_rid = _rid(current)
        if current_rid == root_rid:
            break
        if current_rid in seen:
            break
        seen.add(current_rid)
        best = current
        try:
            parent = current.GetParentControl()
        except Exception:
            break
        if parent is None or _rid(parent) == current_rid:
            break
        current = parent
    return best


def build_steps(ctrl: Any) -> List[SelectorStep]:
    try:
        root = auto.GetRootControl()
        root_rid = _rid(root)
    except Exception:
        return []
    if _rid(ctrl) == root_rid:
        return []

    chain: List[Any] = []
    current = ctrl
    seen = set()
    while current is not None and len(chain) < 32:
        current_rid = _rid(current)
        if current_rid == root_rid:
            break
        if current_rid in seen:
            break
        seen.add(current_rid)
        chain.append(current)
        try:
            parent = current.GetParentControl()
        except Exception:
            parent = None
        if parent is None or _rid(parent) == current_rid:
            break
        current = parent
    chain.reverse()
    if not chain:
        return []

    steps: List[SelectorStep] = []
    for index, item in enumerate(chain):
        is_top = index == 0
        parent = chain[index - 1] if index > 0 else None
        if parent is None:
            try:
                siblings_raw = root.GetChildren()
            except Exception:
                siblings_raw = [item]
        else:
            try:
                siblings_raw = parent.GetChildren()
            except Exception:
                siblings_raw = [item]

        target_snap = _snapshot(item, is_top=is_top)
        sibling_snaps = [_snapshot(s, is_top=is_top) for s in siblings_raw]
        child_index = 0
        for pos, snap in enumerate(sibling_snaps, start=1):
            if snap.rid == target_snap.rid:
                child_index = pos
                break
        if not any(s.rid == target_snap.rid for s in sibling_snaps):
            sibling_snaps.append(target_snap)
        if not sibling_snaps:
            sibling_snaps = [target_snap]

        props, found_index, match_count = _choose_selector(target_snap, sibling_snaps, is_top)
        fallback = _fallback_props(target_snap, sibling_snaps, is_top)
        window_text = target_snap.window_text if not is_top else target_snap.name
        steps.append(
            SelectorStep(
                control_type=target_snap.control_type,
                control_type_name=target_snap.control_type_name,
                name=target_snap.name,
                automation_id=target_snap.automation_id,
                class_name=target_snap.class_name,
                found_index=found_index,
                match_count=match_count,
                child_index=child_index,
                is_top_level=is_top,
                window_text=window_text,
                fallback=fallback,
                display=_display_for(target_snap),
            )
        )
    return steps


def _read_value_preview(ctrl: Any) -> str:
    type_name = str(_safe(lambda: ctrl.ControlTypeName, "") or "")
    if type_name not in ("EditControl", "DocumentControl", "ComboBoxControl"):
        return ""
    try:
        pattern = ctrl.GetValuePattern()
        value = pattern.Value or ""
    except Exception:
        return ""
    value = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return ""
    value = value.replace("\n", " ⏎ ")
    if len(value) > 180:
        value = value[:177] + "..."
    return value


def _capture_thumbnail(rect: Tuple[int, int, int, int], target: Path) -> str:
    if ImageGrab is None or Image is None:
        return ""
    left, top, right, bottom = rect
    if right - left <= 1 or bottom - top <= 1:
        return ""
    try:
        vx1, vy1, vx2, vy2 = virtual_screen_rect()
        image = ImageGrab.grab(all_screens=True)
        # all_screens=True 时，图像坐标以虚拟屏幕左上角为原点。
        box = (left - vx1, top - vy1, right - vx1, bottom - vy1)
        box = (
            max(0, box[0]),
            max(0, box[1]),
            min(image.width, box[2]),
            min(image.height, box[3]),
        )
        if box[2] - box[0] <= 1 or box[3] - box[1] <= 1:
            return ""
        crop = image.crop(box)
        crop.thumbnail((640, 400), Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        crop.save(target, "PNG", optimize=True)
        return str(target)
    except Exception:
        return ""


def _friendly_error(exc: Exception) -> CaptureError:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    hint = ""
    if "access" in lowered or "0x80070005" in lowered or "denied" in lowered:
        hint = "目标程序可能以管理员权限运行。请从右上角菜单选择“以管理员身份重启”。"
    elif "timeout" in lowered or "0x80131505" in lowered:
        hint = "目标程序可能无响应或界面繁忙，请稍后重试。"
    elif "element not available" in lowered or "0x80004005" in lowered:
        hint = "目标元素已消失或界面正在刷新，请重新捕获。"
    return CaptureError(f"捕获失败：{text}", hint)


def hover_from_point(x: int, y: int) -> Optional[HoverInfo]:
    try:
        ctrl = auto.ControlFromPoint(int(x), int(y))
    except Exception:
        return None
    if ctrl is None:
        return None
    pid = _safe_int(lambda: ctrl.ProcessId, 0)
    if pid == os.getpid():
        return None
    rect = _rect_tuple(ctrl)
    if rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0:
        return None
    type_name = str(_safe(lambda: ctrl.ControlTypeName, "") or "")
    localized = str(_safe(lambda: ctrl.LocalizedControlType, "") or "")
    name = str(_safe(lambda: ctrl.Name, "") or "")
    aid = str(_safe(lambda: ctrl.AutomationId, "") or "")
    cls = str(_safe(lambda: ctrl.ClassName, "") or "")
    framework = str(_safe(lambda: ctrl.FrameworkId, "") or "")
    process_name, _ = _process_info(pid)
    return HoverInfo(
        control_type_name=type_name,
        localized_type=localized,
        name=name,
        automation_id=aid,
        class_name=cls,
        rect=rect,
        process_id=pid,
        process_name=process_name,
        framework_id=framework,
    )


_LEAF_STOP_TYPES = {
    "ButtonControl", "MenuItemControl", "ListItemControl", "TabItemControl",
    "TreeItemControl", "CheckBoxControl", "RadioButtonControl", "HyperlinkControl",
    "ComboBoxControl", "SliderControl", "SpinnerControl", "SplitButtonControl",
    "EditControl", "DataItemControl", "ImageControl",
}


def _tree_descend(top: Any, x: int, y: int, max_depth: int = 30) -> Optional[Any]:
    """从顶层窗口沿控件树向下，找包含该坐标的最小控件。"""
    cur = top
    seen = set()
    for _ in range(max_depth):
        cur_rid = _rid(cur)
        if cur_rid in seen:
            break
        seen.add(cur_rid)
        # 交互叶子类型即停：不深入按钮/菜单项/输入框等内部装饰
        cur_type = str(_safe(lambda: cur.ControlTypeName, "") or "")
        if cur_type in _LEAF_STOP_TYPES:
            break
        best = None
        best_area = 10 ** 18
        try:
            children = cur.GetChildren()
        except Exception:
            children = []
        for child in children:
            l, t, r, b = _rect_tuple(child)
            if r - l <= 0 or b - t <= 0:
                continue
            if l <= x < r and t <= y < b:
                area = (r - l) * (b - t)
                if area < best_area:
                    best, best_area = child, area
        if best is None:
            break
        cur = best
    return cur


_INTERACTIVE_PARENTS = {
    "ButtonControl", "MenuItemControl", "SplitButtonControl", "ListItemControl",
    "TabItemControl", "TreeItemControl", "HyperlinkControl", "CheckBoxControl",
    "RadioButtonControl", "ComboBoxControl",
}
_DECORATION_TYPES = {"TextControl", "ImageControl"}


def _resolve_decorated(cur: Any, top: Any, top_rid: tuple) -> Any:
    """图标/字形等装饰控件贴在交互控件上时，归并到交互控件。"""
    try:
        for _ in range(6):
            if _rid(cur) == top_rid:
                break
            type_name = str(_safe(lambda: cur.ControlTypeName, "") or "")
            if type_name not in _DECORATION_TYPES:
                break
            parent = cur.GetParentControl()
            if parent is None or _rid(parent) == top_rid:
                break
            parent_type = str(_safe(lambda: parent.ControlTypeName, "") or "")
            if parent_type in _INTERACTIVE_PARENTS or parent_type in _DECORATION_TYPES:
                cur = parent
                continue
            break
    except Exception:
        pass
    return cur


def _top_level_from_point(x: int, y: int) -> Optional[Any]:
    """遍历顶层窗口，找包含该坐标的可见窗口。"""
    try:
        root = auto.GetRootControl()
        for win in root.GetChildren():
            l, t, r, b = _rect_tuple(win)
            if r - l <= 0 or b - t <= 0:
                continue
            if l <= x < r and t <= y < b:
                return win
    except Exception:
        pass
    return None


def capture_from_point(x: int, y: int, thumb_dir: Path, mode: str = "uia") -> ElementCapture:
    auto.SetGlobalSearchTimeout(5.0)
    ctrl = None
    try:
        ctrl = auto.ControlFromPoint(int(x), int(y))
    except Exception as exc:
        if mode != "tree":
            raise _friendly_error(exc) from exc
    if ctrl is None:
        top = _top_level_from_point(int(x), int(y))
        if top is None:
            raise CaptureError("光标下没有可访问的 UI Automation 元素。", "请将鼠标悬停在目标程序的按钮、输入框或菜单上。")
        ctrl = _tree_descend(top, int(x), int(y))
        if ctrl is None:
            raise CaptureError("光标下没有可访问的 UI Automation 元素。", "请将鼠标悬停在目标程序的按钮、输入框或菜单上。")
    elif mode == "tree":
        top = None
        try:
            top = ctrl.GetTopLevelControl()
        except Exception:
            top = None
        if top is None:
            top = _top_level_from_point(int(x), int(y))
        if top is not None:
            deeper = _tree_descend(top, int(x), int(y))
            if deeper is not None:
                ctrl = _resolve_decorated(deeper, top, _rid(top))
    else:
        # 坐标模式自动兜底：命中顶层包装元素时，改用树状下降
        try:
            top = ctrl.GetTopLevelControl()
            if top is not None and _rid(ctrl) == _rid(top):
                deeper = _tree_descend(top, int(x), int(y))
                if deeper is not None:
                    deeper = _resolve_decorated(deeper, top, _rid(top))
                    if _rid(deeper) != _rid(ctrl):
                        ctrl = deeper
        except Exception:
            pass
    return capture_from_control(ctrl, int(x), int(y), thumb_dir, mode=mode)


def capture_from_control(ctrl: Any, x: int, y: int, thumb_dir: Path, mode: str = "uia") -> ElementCapture:
    """从已有 UIA 控件构建捕获快照；便于测试和二次开发。"""
    auto.SetGlobalSearchTimeout(5.0)
    pid = _safe_int(lambda: ctrl.ProcessId, 0)
    if pid == os.getpid():
        raise CaptureError("不能捕获捕获器自身。", "请将鼠标移到目标程序的控件上再按 F2。")

    top = find_anchor_control(ctrl)
    try:
        steps = build_steps(ctrl)
    except Exception as exc:
        raise _friendly_error(exc) from exc

    rel_texts: List[str] = []
    rel_types: List[str] = []
    rel_index = 0
    try:
        parent_ctrl = ctrl.GetParentControl()
        if parent_ctrl is not None:
            for i, sib in enumerate(parent_ctrl.GetChildren(), start=1):
                rel_types.append(str(_safe(lambda: sib.ControlTypeName, "") or ""))
                rel_texts.append(str(_safe(lambda: sib.Name, "") or ""))
                if _rid(sib) == _rid(ctrl):
                    rel_index = i
    except Exception:
        pass

    rect = _rect_tuple(ctrl)
    type_name = str(_safe(lambda: ctrl.ControlTypeName, "") or "")
    localized = str(_safe(lambda: ctrl.LocalizedControlType, "") or "")
    name = str(_safe(lambda: ctrl.Name, "") or "")
    aid = str(_safe(lambda: ctrl.AutomationId, "") or "")
    cls = str(_safe(lambda: ctrl.ClassName, "") or "")
    framework = str(_safe(lambda: ctrl.FrameworkId, "") or "")
    process_name, process_exe = _process_info(pid)
    window_title = str(_safe(lambda: top.Name, "") or "")
    window_class = str(_safe(lambda: top.ClassName, "") or "")
    window_handle = _safe_int(lambda: top.NativeWindowHandle, 0)
    now = datetime.now().astimezone()
    capture_id = now.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)

    capture = ElementCapture(
        id=capture_id,
        created_at=now.isoformat(timespec="seconds"),
        control_type=_safe_int(lambda: ctrl.ControlType, 0),
        control_type_name=type_name,
        localized_control_type=localized,
        name=name,
        automation_id=aid,
        class_name=cls,
        framework_id=framework,
        process_id=pid,
        process_name=process_name,
        process_exe=process_exe,
        window_title=window_title,
        window_class=window_class,
        window_handle=window_handle,
        rect=rect,
        point=(int(x), int(y)),
        runtime_id=[int(v) for v in _safe(lambda: ctrl.GetRuntimeId(), []) or []],
        is_enabled=_safe_bool(lambda: ctrl.IsEnabled, True),
        is_offscreen=_safe_bool(lambda: ctrl.IsOffscreen, False),
        is_password=_safe_bool(lambda: ctrl.IsPassword, False),
        help_text=str(_safe(lambda: ctrl.HelpText, "") or ""),
        accelerator_key=str(_safe(lambda: ctrl.AcceleratorKey, "") or ""),
        access_key=str(_safe(lambda: ctrl.AccessKey, "") or ""),
        item_status=str(_safe(lambda: ctrl.ItemStatus, "") or ""),
        item_type=str(_safe(lambda: ctrl.ItemType, "") or ""),
        value_preview=_read_value_preview(ctrl),
        steps=steps,
        rel_texts=rel_texts,
        rel_index=rel_index,
        rel_types=rel_types,
        capture_mode=("pwa树状" if mode == "tree" else "uia坐标"),
    )

    # 等覆盖层隐藏后再截图，避免把高亮边框截进缩略图。
    time.sleep(0.06)
    thumb_path = _capture_thumbnail(rect, thumb_dir / f"{capture_id}.png")
    if thumb_path:
        capture.screenshot = f"thumbs/{capture_id}.png"

    capture.uia_code = generate_uiautomation(capture)
    capture.pywinauto_code = generate_pywinauto(capture)
    capture.uia_compact_code = generate_uiautomation_compact(capture)
    capture.pywinauto_compact_code = generate_pywinauto_compact(capture)
    capture.pwa_rel_code = generate_pywinauto_relative(capture)
    return capture
