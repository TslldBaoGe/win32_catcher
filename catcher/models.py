"""数据模型与序列化。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1

CONTROL_TYPE_LABELS: Dict[str, str] = {
    "AppBarControl": "应用栏",
    "ButtonControl": "按钮",
    "CalendarControl": "日历",
    "CheckBoxControl": "复选框",
    "ComboBoxControl": "下拉框",
    "CustomControl": "自定义",
    "DataGridControl": "数据表格",
    "DataItemControl": "数据项",
    "DocumentControl": "文档",
    "EditControl": "输入框",
    "GroupControl": "分组",
    "HeaderControl": "表头",
    "HeaderItemControl": "表头项",
    "HyperlinkControl": "链接",
    "ImageControl": "图片",
    "ListControl": "列表",
    "ListItemControl": "列表项",
    "MenuBarControl": "菜单栏",
    "MenuControl": "菜单",
    "MenuItemControl": "菜单项",
    "PaneControl": "容器",
    "ProgressBarControl": "进度条",
    "RadioButtonControl": "单选框",
    "ScrollBarControl": "滚动条",
    "SemanticZoomControl": "缩放",
    "SeparatorControl": "分隔线",
    "SliderControl": "滑块",
    "SpinnerControl": "微调框",
    "SplitButtonControl": "拆分按钮",
    "StatusBarControl": "状态栏",
    "TabControl": "选项卡",
    "TabItemControl": "选项卡项",
    "TableControl": "表格",
    "TextControl": "文本",
    "ThumbControl": "拖动块",
    "TitleBarControl": "标题栏",
    "ToolBarControl": "工具栏",
    "ToolTipControl": "提示框",
    "TreeControl": "树",
    "TreeItemControl": "树节点",
    "WindowControl": "窗口",
}


def control_type_label(name: str) -> str:
    return CONTROL_TYPE_LABELS.get(name, name.replace("Control", "") or "元素")


def short_type(name: str) -> str:
    return name.replace("Control", "") or "Element"


@dataclass
class SelectorStep:
    """定位路径中的一级。"""

    control_type: int = 0
    control_type_name: str = ""
    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    found_index: int = 1
    match_count: int = 1
    child_index: int = 0
    is_top_level: bool = False
    window_text: str = ""
    fallback: Optional[Dict[str, Any]] = None
    display: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "SelectorStep":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {k: v for k, v in (raw or {}).items() if k in allowed}
        if "fallback" in data and data["fallback"] is not None and not isinstance(data["fallback"], dict):
            data["fallback"] = None
        return cls(**data)


@dataclass
class ElementCapture:
    """一次元素捕获的完整快照。"""

    id: str
    created_at: str
    control_type: int = 0
    control_type_name: str = ""
    localized_control_type: str = ""
    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    framework_id: str = ""
    process_id: int = 0
    process_name: str = ""
    process_exe: str = ""
    window_title: str = ""
    window_class: str = ""
    window_handle: int = 0
    rect: Tuple[int, int, int, int] = (0, 0, 0, 0)
    point: Tuple[int, int] = (0, 0)
    runtime_id: List[int] = field(default_factory=list)
    rel_texts: List[str] = field(default_factory=list)
    rel_index: int = 0
    rel_types: List[str] = field(default_factory=list)
    is_enabled: bool = True
    is_offscreen: bool = False
    is_password: bool = False
    help_text: str = ""
    accelerator_key: str = ""
    access_key: str = ""
    item_status: str = ""
    item_type: str = ""
    value_preview: str = ""
    steps: List[SelectorStep] = field(default_factory=list)
    screenshot: str = ""
    uia_code: str = ""
    pywinauto_code: str = ""
    uia_compact_code: str = ""
    pywinauto_compact_code: str = ""
    pwa_rel_code: str = ""
    capture_mode: str = "uia"

    # ---------- 派生属性 ----------
    @property
    def width(self) -> int:
        return max(0, int(self.rect[2]) - int(self.rect[0]))

    @property
    def height(self) -> int:
        return max(0, int(self.rect[3]) - int(self.rect[1]))

    @property
    def center(self) -> Tuple[int, int]:
        left, top, right, bottom = self.rect
        return ((left + right) // 2, (top + bottom) // 2)

    @property
    def type_label(self) -> str:
        return control_type_label(self.control_type_name)

    @property
    def type_short(self) -> str:
        return short_type(self.control_type_name)

    @property
    def display_name(self) -> str:
        return self.name.strip() or self.automation_id.strip() or self.class_name.strip() or "(无名称)"

    @property
    def time_label(self) -> str:
        try:
            return datetime.fromisoformat(self.created_at).strftime("%H:%M")
        except Exception:
            return ""

    @property
    def date_label(self) -> str:
        try:
            return datetime.fromisoformat(self.created_at).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return self.created_at

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["rect"] = list(self.rect)
        data["point"] = list(self.point)
        return data

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ElementCapture":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {k: v for k, v in (raw or {}).items() if k in allowed}
        steps = [SelectorStep.from_dict(s) for s in data.pop("steps", []) or []]
        rect = data.get("rect") or (0, 0, 0, 0)
        point = data.get("point") or (0, 0)
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            rect = (0, 0, 0, 0)
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            point = (0, 0)
        data["rect"] = tuple(int(v) for v in rect)
        data["point"] = tuple(int(v) for v in point)
        if not isinstance(data.get("runtime_id"), list):
            data["runtime_id"] = []
        if not isinstance(data.get("rel_texts"), list):
            data["rel_texts"] = []
        if not isinstance(data.get("rel_types"), list):
            data["rel_types"] = []
        try:
            data["rel_index"] = int(data.get("rel_index") or 0)
        except Exception:
            data["rel_index"] = 0
        data["steps"] = steps
        return cls(**data)
