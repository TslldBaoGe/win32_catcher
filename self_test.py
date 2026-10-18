# -*- coding: utf-8 -*-
"""环境与真实控件自检。"""
from __future__ import annotations

import ctypes
import importlib.metadata as metadata
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Tuple

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _enable_dpi() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi()


def _line(char: str = "-", width: int = 68) -> str:
    return char * width


def _print_check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  {detail}" if detail else ""))
    return ok


def _check_environment() -> bool:
    print(_line("="))
    print("1. 环境检查")
    print(_line("="))
    ok = True
    ok &= _print_check("Python", sys.version_info >= (3, 9), sys.version.split()[0])
    ok &= _print_check("Python 路径", Path(sys.executable).exists(), sys.executable)
    for package, import_name in (
        ("uiautomation", "uiautomation"),
        ("pywinauto", "pywinauto"),
        ("Pillow", "PIL"),
        ("psutil", "psutil"),
        ("pywin32", "win32api"),
    ):
        try:
            __import__(import_name)
            try:
                version = metadata.version(package)
            except Exception:
                version = "installed"
            ok &= _print_check(package, True, version)
        except Exception as exc:
            ok &= _print_check(package, False, str(exc))
    try:
        from catcher.winutil import system_dpi, virtual_screen_rect

        dpi = system_dpi()
        screen = virtual_screen_rect()
        print(f"  [INFO] DPI={dpi}  虚拟屏幕={screen}")
    except Exception as exc:
        ok &= _print_check("屏幕信息", False, str(exc))
    return ok


def _check_codegen() -> bool:
    print()
    print(_line("="))
    print("2. 数据模型与代码生成")
    print(_line("="))
    from catcher.codegen import (
        generate_pywinauto,
        generate_pywinauto_compact,
        generate_uiautomation,
        generate_uiautomation_compact,
        normalize_capture,
    )
    from catcher.models import ElementCapture, SelectorStep

    steps = [
        SelectorStep(
            control_type=50032,
            control_type_name="WindowControl",
            name="演示窗口",
            class_name="DemoWindow",
            found_index=1,
            is_top_level=True,
            fallback={"Name": "", "ClassName": "DemoWindow", "ControlType": 50032, "found_index": 1},
        ),
        SelectorStep(
            control_type=50000,
            control_type_name="ButtonControl",
            name="确定",
            automation_id="okButton",
            class_name="Button",
            found_index=2,
            match_count=2,
            window_text="确定",
        ),
    ]
    capture = ElementCapture(
        id="selftest",
        created_at="2026-10-17T00:00:00+08:00",
        control_type=50000,
        control_type_name="ButtonControl",
        name="确定",
        automation_id="okButton",
        class_name="Button",
        process_id=1234,
        process_name="demo.exe",
        window_title="演示窗口",
        window_class="DemoWindow",
        rect=(10, 20, 110, 60),
        steps=steps,
    )
    ok = True
    try:
        restored = ElementCapture.from_dict(capture.to_dict())
        ok &= _print_check("序列化往返", restored.automation_id == "okButton" and len(restored.steps) == 2)
    except Exception as exc:
        ok &= _print_check("序列化往返", False, str(exc))

    try:
        uia = generate_uiautomation(capture)
        pwa = generate_pywinauto(capture)
        compile(uia, "uia_generated.py", "exec")
        compile(pwa, "pwa_generated.py", "exec")
        ok &= _print_check("uiautomation 代码语法", True, f"{len(uia)} 字符")
        ok &= _print_check("pywinauto 代码语法", True, f"{len(pwa)} 字符")
        uia_c = generate_uiautomation_compact(capture)
        pwa_c = generate_pywinauto_compact(capture)
        compile(uia_c, "uia_compact.py", "exec")
        compile(pwa_c, "pwa_compact.py", "exec")
        ok &= _print_check("精简代码语法", True, f"uia {len(uia_c)} / pwa {len(pwa_c)} 字符")
        ok &= _print_check("精简代码足够短", len(uia_c.splitlines()) <= 18 and len(pwa_c.splitlines()) <= 18)
        ok &= _print_check("DPI 感知高亮", "SetProcessDpiAwareness" in uia and "SetProcessDpiAwareness" in pwa)
        ok &= _print_check("顶层类名兜底", "ClassName='DemoWindow'" in uia and "class_name='DemoWindow'" in pwa)
    except Exception as exc:
        ok &= _print_check("代码生成", False, str(exc))

    try:
        desktop_step = SelectorStep(
            control_type=50033,
            control_type_name="PaneControl",
            name="桌面 1",
            class_name="#32769",
            is_top_level=True,
        )
        old_capture = ElementCapture(
            id="old",
            created_at="2026-10-17T00:00:00+08:00",
            steps=[desktop_step] + steps,
        )
        normalize_capture(old_capture)
        ok &= _print_check(
            "旧记录桌面根修复",
            old_capture.steps and old_capture.steps[0].control_type_name == "WindowControl",
            f"剩余 {len(old_capture.steps)} 级",
        )
    except Exception as exc:
        ok &= _print_check("旧记录桌面根修复", False, str(exc))
    return bool(ok)


def _find_notepad_window(filename: str, timeout: float = 10.0):
    import uiautomation as auto

    pattern = re.escape(filename)
    win = auto.WindowControl(searchDepth=1, RegexName=f".*{pattern}.*")
    end = time.time() + timeout
    while time.time() < end:
        try:
            if win.Exists(0, 0):
                return win
        except Exception:
            pass
        time.sleep(0.3)
    return None


def _find_target(window):
    import uiautomation as auto

    candidates = [
        auto.ButtonControl(searchFromControl=window, searchDepth=12, AutomationId="AddButton"),
        auto.ButtonControl(searchFromControl=window, searchDepth=12, Name="Add New Tab"),
        auto.DocumentControl(searchFromControl=window, searchDepth=12),
        auto.PaneControl(searchFromControl=window, searchDepth=12, ClassName="NotepadTextBox"),
    ]
    for candidate in candidates:
        try:
            if candidate.Exists(1.0, 0.2):
                return candidate
        except Exception:
            continue
    return None


def _check_integration() -> Tuple[bool, bool]:
    """返回 (是否执行, 是否通过)。"""
    print()
    print(_line("="))
    print("3. 真实控件捕获与独立进程回放（记事本）")
    print(_line("="))
    import uiautomation as auto
    from catcher.actions import element_value, locate_capture
    from catcher.capture import capture_from_control
    from catcher.verifier import run_verification

    with tempfile.TemporaryDirectory(prefix="element_catcher_selftest_") as temp:
        temp_dir = Path(temp)
        filename = f"element_catcher_selftest_{os.getpid()}.txt"
        test_file = temp_dir / filename
        test_file.write_text("desktop element catcher self test", encoding="utf-8")
        thumb_dir = temp_dir / "thumbs"
        thumb_dir.mkdir()

        proc = None
        window = None
        try:
            proc = subprocess.Popen(
                ["notepad.exe", str(test_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            window = _find_notepad_window(filename)
            if window is None:
                print("  [SKIP] 未找到测试记事本窗口（当前系统可能未安装经典记事本）。")
                return False, True
            print(f"  [INFO] 记事本窗口: {window.BoundingRectangle}")
            target = _find_target(window)
            if target is None:
                print("  [FAIL] 记事本中没有找到可访问的 UIA 控件。")
                return True, False
            rect = target.BoundingRectangle
            point = ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
            capture = capture_from_control(target, point[0], point[1], thumb_dir)
            print(
                f"  [INFO] 捕获: {capture.control_type_name} {capture.name!r} "
                f"path={len(capture.steps)}级 rect={capture.rect}"
            )
            all_ok = True
            try:
                located = locate_capture(capture, timeout=3.0)
                value, source = element_value(located)
                readable = bool(value) or source != "未找到可读取的值"
                print(f"  [{'PASS' if readable else 'FAIL'}] 取值操作: {value[:60]!r} (来源 {source})")
                all_ok &= readable
            except Exception as exc:
                print(f"  [FAIL] 取值操作: {type(exc).__name__}: {exc}")
                all_ok = False
            for mode in ("uiautomation", "uiautomation_compact", "pywinauto", "pywinauto_compact"):
                result = run_verification(capture, mode)
                print(f"  [INFO] {mode}: ok={result.ok} 用时={result.duration:.2f}s")
                for check in result.checks:
                    print(f"         {check.status:4} {check.label}: {check.detail}")
                if result.error:
                    print(f"         ERROR: {result.error.splitlines()[0]}")
                all_ok &= result.ok
            return True, all_ok
        except Exception as exc:
            print(f"  [FAIL] 集成测试异常: {type(exc).__name__}: {exc}")
            return True, False
        finally:
            if window is not None:
                try:
                    window.GetWindowPattern().Close()
                except Exception:
                    pass
            time.sleep(0.3)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass


def main() -> int:
    print("桌面元素捕获器 · 自检")
    print(f"目录: {APP_DIR}")
    ok = _check_environment()
    ok &= _check_codegen()
    ran, integration_ok = _check_integration()
    ok &= integration_ok
    print()
    print(_line("="))
    if not ran:
        print("结果: 基础检查通过；记事本集成测试已跳过。")
    else:
        print("结果: " + ("全部通过" if ok else "存在失败项，请查看上方输出和 data/logs/app.log"))
    print(_line("="))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
