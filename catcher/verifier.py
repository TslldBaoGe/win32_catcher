"""在独立 Python 进程中回放生成代码并校验定位结果。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .codegen import build_verify_harness
from .models import ElementCapture
from .paths import VERIFY_TIMEOUT
from .winutil import intersects_virtual_screen


@dataclass
class CheckResult:
    key: str
    label: str
    status: str  # pass / warn / fail / skip
    detail: str = ""


@dataclass
class VerifyResult:
    ok: bool
    checks: List[CheckResult] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    stderr: str = ""
    duration: float = 0.0
    mode: str = "uiautomation"
    python: str = ""

    @property
    def warnings(self) -> bool:
        return any(c.status == "warn" for c in self.checks)


def _normalize_type(name: str) -> str:
    value = (name or "").strip()
    if value.endswith("Control"):
        value = value[:-7]
    return value.lower()


def _tail(text: str, limit: int = 2400) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def _property_check(capture: ElementCapture, data: Dict[str, Any]) -> CheckResult:
    found_aid = str(data.get("automation_id") or "")
    found_name = str(data.get("name") or "")
    found_cls = str(data.get("class_name") or "")
    details: List[str] = []
    status = "pass"

    if capture.automation_id:
        if found_aid == capture.automation_id:
            details.append("AutomationId 一致")
        else:
            status = "fail"
            details.append(f"AutomationId 不一致：{found_aid!r} ≠ {capture.automation_id!r}")
    elif capture.name:
        if found_name == capture.name:
            details.append("名称一致")
        else:
            status = "warn"
            details.append(f"名称已变化：{found_name!r} ≠ {capture.name!r}（可能是动态文本）")
    else:
        details.append("无 AutomationId/Name，按类型定位")

    if capture.class_name:
        if found_cls == capture.class_name:
            details.append("ClassName 一致")
        else:
            if status == "pass":
                status = "warn"
            details.append(f"ClassName 不一致：{found_cls!r} ≠ {capture.class_name!r}")

    return CheckResult("properties", "关键属性", status, "；".join(details))


def _rect_check(data: Dict[str, Any]) -> CheckResult:
    rect = data.get("rect")
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return CheckResult("rect", "矩形有效", "fail", "未返回有效矩形")
    left, top, right, bottom = (int(v) for v in rect)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return CheckResult("rect", "矩形有效", "fail", f"矩形尺寸为 {width}×{height}")
    if not intersects_virtual_screen((left, top, right, bottom)):
        return CheckResult("rect", "矩形有效", "warn", f"元素当前不在屏幕内：({left}, {top}) {width}×{height}")
    return CheckResult("rect", "矩形有效", "pass", f"({left}, {top}) {width}×{height}")


def run_verification(capture: ElementCapture, mode: str, python_exe: str = "") -> VerifyResult:
    start = time.perf_counter()
    mode = mode if mode in ("uiautomation", "pywinauto", "uiautomation_compact", "pywinauto_compact", "pywinauto_relative") else "uiautomation"
    code = {
        "uiautomation": capture.uia_code,
        "pywinauto": capture.pywinauto_code,
        "uiautomation_compact": capture.uia_compact_code,
        "pywinauto_compact": capture.pywinauto_compact_code,
        "pywinauto_relative": capture.pwa_rel_code,
    }.get(mode, capture.uia_code)
    if not code.strip():
        return VerifyResult(
            ok=False,
            checks=[CheckResult("playback", "代码回放", "fail", "当前模式没有生成代码")],
            error="当前模式没有生成代码",
            duration=time.perf_counter() - start,
            mode=mode,
        )

    exe = (python_exe or "").strip().strip('"')
    if not exe or not Path(exe).exists():
        if getattr(sys, "frozen", False):
            return VerifyResult(
                ok=False,
                checks=[
                    CheckResult("playback", "代码回放", "fail", "未指定 Python 解释器"),
                    CheckResult("type", "控件类型", "skip", ""),
                    CheckResult("properties", "关键属性", "skip", ""),
                    CheckResult("rect", "矩形有效", "skip", ""),
                ],
                error="exe 模式下需要单独的 Python 来回放代码。请点右上角 ⚙ 设置，"
                      "指定一个已安装 uiautomation 和 pywinauto 的 python.exe。",
                duration=time.perf_counter() - start,
                mode=mode,
            )
        exe = sys.executable

    temp_dir = Path(tempfile.mkdtemp(prefix="element_catcher_verify_"))
    locator_path = temp_dir / "locator.py"
    harness_path = temp_dir / "verify_run.py"
    try:
        locator_path.write_text(code, encoding="utf-8")
        harness_path.write_text(build_verify_harness(locator_path), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
            }
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(
                [exe, str(harness_path)],
                cwd=str(temp_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=VERIFY_TIMEOUT,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            stderr = _tail(str(exc.stderr or ""))
            result = VerifyResult(
                ok=False,
                checks=[
                    CheckResult("playback", "代码回放", "fail", f"独立进程验证超时（{VERIFY_TIMEOUT:.0f}s）"),
                    CheckResult("type", "控件类型", "skip", ""),
                    CheckResult("properties", "关键属性", "skip", ""),
                    CheckResult("rect", "矩形有效", "skip", ""),
                ],
                error="验证超时：目标程序可能无响应，或窗口已关闭。",
                stderr=stderr,
                duration=time.perf_counter() - start,
                mode=mode,
                python=exe,
            )
            return result
        except Exception as exc:
            return VerifyResult(
                ok=False,
                checks=[CheckResult("playback", "代码回放", "fail", f"无法启动验证进程：{exc}")],
                error=f"无法启动验证进程：{exc}",
                duration=time.perf_counter() - start,
                mode=mode,
                python=exe,
            )

        stdout = proc.stdout or ""
        stderr = _tail(proc.stderr or "")
        payload: Optional[Dict[str, Any]] = None
        error_payload = ""
        for line in stdout.splitlines():
            if line.startswith("__ELEMENT_CATCHER_JSON__"):
                try:
                    payload = json.loads(line[len("__ELEMENT_CATCHER_JSON__") :])
                except Exception:
                    payload = None
            elif line.startswith("__ELEMENT_CATCHER_ERROR__"):
                try:
                    error_data = json.loads(line[len("__ELEMENT_CATCHER_ERROR__") :])
                    error_payload = str(error_data.get("error") or "")
                except Exception:
                    error_payload = line

        if payload is None:
            message = error_payload or "独立进程没有返回定位结果。"
            if proc.returncode != 0 and stderr:
                message = f"{message}\n{stderr}"
            return VerifyResult(
                ok=False,
                checks=[
                    CheckResult("playback", "代码回放", "fail", message.splitlines()[0] if message else "失败"),
                    CheckResult("type", "控件类型", "skip", ""),
                    CheckResult("properties", "关键属性", "skip", ""),
                    CheckResult("rect", "矩形有效", "skip", ""),
                ],
                error=message,
                stderr=stderr,
                duration=time.perf_counter() - start,
                mode=mode,
            )

        checks: List[CheckResult] = [CheckResult("playback", "代码回放", "pass", "独立进程定位成功")]
        found_type = _normalize_type(str(payload.get("control_type") or ""))
        captured_type = _normalize_type(capture.control_type_name)
        if found_type and found_type == captured_type:
            checks.append(CheckResult("type", "控件类型", "pass", f"{payload.get('control_type')}"))
        else:
            checks.append(
                CheckResult(
                    "type",
                    "控件类型",
                    "fail",
                    f"实际 {payload.get('control_type')!r} ≠ 捕获 {capture.control_type_name!r}",
                )
            )
        checks.append(_property_check(capture, payload))
        checks.append(_rect_check(payload))
        ok = all(check.status != "fail" for check in checks)
        return VerifyResult(
            ok=ok,
            checks=checks,
            data=payload,
            stderr=stderr,
            duration=time.perf_counter() - start,
            mode=mode,
            python=exe,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
