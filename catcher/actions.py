"""元素操作：点击、输入、获取值。

所有操作都会先按捕获时的定位路径重新查找控件，避免跨线程复用 COM 元素。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import uiautomation as auto

from .models import ElementCapture, SelectorStep


class ActionError(RuntimeError):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def _step_kwargs(step: SelectorStep, top: bool) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"searchDepth": 1}
    if not (top and step.control_type_name == "WindowControl"):
        if step.control_type:
            kwargs["ControlType"] = int(step.control_type)
    if step.automation_id:
        kwargs["AutomationId"] = step.automation_id
    if step.name:
        kwargs["Name"] = step.name
    if step.class_name:
        kwargs["ClassName"] = step.class_name
    if step.found_index and step.found_index > 1:
        kwargs["foundIndex"] = int(step.found_index)
    return kwargs


def _fallback_kwargs(step: SelectorStep) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {"searchDepth": 1}
    if not (step.control_type_name == "WindowControl"):
        if step.control_type:
            kwargs["ControlType"] = int(step.control_type)
    fallback = step.fallback or {}
    if fallback.get("Name"):
        kwargs["Name"] = fallback["Name"]
    if fallback.get("ClassName"):
        kwargs["ClassName"] = fallback["ClassName"]
    index = int(fallback.get("found_index") or 1)
    if index > 1:
        kwargs["foundIndex"] = index
    return kwargs


def _friendly(exc: Exception) -> ActionError:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    hint = ""
    if "access" in lowered or "0x80070005" in lowered or "denied" in lowered:
        hint = "目标程序可能以管理员权限运行，请从右上角菜单选择“以管理员身份重启”。"
    elif "timeout" in lowered:
        hint = "目标程序可能无响应或界面正在刷新。"
    elif "not available" in lowered or "0x80004005" in lowered:
        hint = "元素已经消失，请重新捕获。"
    return ActionError(text, hint)


def locate_capture(capture: ElementCapture, timeout: float = 5.0) -> Any:
    """按捕获记录重新定位控件。"""
    auto.SetGlobalSearchTimeout(timeout)
    if not capture.steps:
        return auto.GetRootControl()
    first = capture.steps[0]
    try:
        if first.control_type_name == "WindowControl":
            ctrl = auto.WindowControl(**_step_kwargs(first, top=True))
        else:
            ctrl = auto.Control(**_step_kwargs(first, top=True))
        if not ctrl.Exists(timeout, 0.25) and first.fallback:
            if first.control_type_name == "WindowControl":
                ctrl = auto.WindowControl(**_fallback_kwargs(first))
            else:
                ctrl = auto.Control(**_fallback_kwargs(first))
        if not ctrl.Exists(timeout, 0.25):
            raise ActionError(f"未找到顶层窗口：{first.name or first.class_name or first.control_type_name}")

        for index, step in enumerate(capture.steps[1:], start=2):
            ctrl = auto.Control(searchFromControl=ctrl, **_step_kwargs(step, top=False))
            if not ctrl.Exists(timeout, 0.25):
                raise ActionError(f"未找到第 {index} 级控件：{step.name or step.class_name or step.control_type_name}")
        return ctrl
    except ActionError:
        raise
    except Exception as exc:
        raise _friendly(exc) from exc


def _invoke_pattern(ctrl: Any, pattern_id: int):
    try:
        return ctrl.GetPattern(pattern_id)
    except Exception:
        return None


def element_click(ctrl: Any) -> str:
    if not bool(getattr(ctrl, "IsEnabled", True)):
        raise ActionError("控件当前不可用（IsEnabled=False）。")
    attempts: List[str] = []
    pattern_actions = (
        ("Invoke", auto.PatternId.InvokePattern, lambda pattern: pattern.Invoke()),
        ("Toggle", auto.PatternId.TogglePattern, lambda pattern: pattern.Toggle()),
        ("SelectionItem", auto.PatternId.SelectionItemPattern, lambda pattern: pattern.Select()),
        ("ExpandCollapse", auto.PatternId.ExpandCollapsePattern, lambda pattern: pattern.Expand()),
        ("LegacyIAccessible", auto.PatternId.LegacyIAccessiblePattern, lambda pattern: pattern.DoDefaultAction()),
    )
    for label, pattern_id, action in pattern_actions:
        pattern = _invoke_pattern(ctrl, pattern_id)
        if pattern is None:
            continue
        try:
            action(pattern)
            return f"已通过 {label} 模式点击"
        except Exception as exc:
            attempts.append(f"{label}: {exc}")
            continue

    try:
        ctrl.SetFocus()
    except Exception:
        pass
    try:
        ctrl.Click()
        return "已通过鼠标点击"
    except Exception as exc:
        detail = "；".join(attempts + [str(exc)])
        raise ActionError(f"点击失败：{detail}")


def _escape_sendkeys(text: str) -> str:
    return text.replace("{", "{{}").replace("}", "{}}")


def element_input(ctrl: Any, text: str) -> str:
    if not bool(getattr(ctrl, "IsEnabled", True)):
        raise ActionError("控件当前不可用（IsEnabled=False）。")
    errors: List[str] = []
    pattern = _invoke_pattern(ctrl, auto.PatternId.ValuePattern)
    if pattern is not None:
        try:
            if not bool(getattr(pattern, "IsReadOnly", False)):
                pattern.SetValue(text)
                return "已通过 ValuePattern 写入"
        except Exception as exc:
            errors.append(f"ValuePattern: {exc}")

    try:
        ctrl.SetFocus()
    except Exception:
        pass
    try:
        try:
            ctrl.SendKeys("{Ctrl}a", waitTime=0.1)
            ctrl.SendKeys("{Del}", waitTime=0.1)
        except Exception:
            pass
        ctrl.SendKeys(_escape_sendkeys(text))
        return "已聚焦控件并发送按键"
    except Exception as exc:
        detail = "；".join(errors + [str(exc)])
        raise ActionError(f"输入失败：{detail}")


def element_value(ctrl: Any) -> Tuple[str, str]:
    """返回 (值, 来源)。"""
    pattern = _invoke_pattern(ctrl, auto.PatternId.ValuePattern)
    if pattern is not None:
        try:
            value = pattern.Value
            if value is not None:
                return str(value), "ValuePattern"
        except Exception:
            pass

    pattern = _invoke_pattern(ctrl, auto.PatternId.RangeValuePattern)
    if pattern is not None:
        try:
            value = pattern.Value
            if value is not None:
                return str(value), "RangeValuePattern"
        except Exception:
            pass

    try:
        legacy = ctrl.GetLegacyIAccessiblePattern()
        if legacy is not None:
            for attribute, source in (("Value", "LegacyIAccessible.Value"), ("Name", "LegacyIAccessible.Name")):
                try:
                    value = getattr(legacy, attribute)
                    if value:
                        return str(value), source
                except Exception:
                    continue
    except Exception:
        pass

    try:
        text = ctrl.GetWindowText()
        if text:
            return str(text), "窗口文本"
    except Exception:
        pass

    try:
        name = ctrl.Name
        if name:
            return str(name), "Name"
    except Exception:
        pass

    try:
        status = ctrl.ItemStatus
        if status:
            return str(status), "ItemStatus"
    except Exception:
        pass

    pattern = _invoke_pattern(ctrl, auto.PatternId.TextPattern)
    if pattern is not None:
        try:
            document_range = pattern.DocumentRange
            try:
                text = document_range.GetText(-1)
            except Exception:
                text = document_range.GetText(4000)
            if text:
                return str(text), "TextPattern"
        except Exception:
            pass

    return "", "未找到可读取的值"
