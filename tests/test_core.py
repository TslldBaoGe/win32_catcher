# -*- coding: utf-8 -*-
"""核心单元测试（不依赖真实桌面窗口）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catcher.codegen import (
    generate_pywinauto,
    generate_pywinauto_compact,
    generate_uiautomation,
    generate_uiautomation_compact,
    normalize_capture,
)
from catcher.rel_codegen import generate_pywinauto_relative
from catcher.models import ElementCapture, SelectorStep
from catcher.settings import AppSettings, load_settings, save_settings
from catcher.storage import CaptureStore


def make_capture(with_desktop: bool = False) -> ElementCapture:
    steps = [
        SelectorStep(
            control_type=50000,
            control_type_name="ButtonControl",
            name="确定",
            automation_id="okButton",
            class_name="Button",
            found_index=2,
            match_count=2,
            window_text="确定",
        )
    ]
    if with_desktop:
        steps = [
            SelectorStep(
                control_type=50033,
                control_type_name="PaneControl",
                name="桌面 1",
                class_name="#32769",
                is_top_level=True,
            ),
            SelectorStep(
                control_type=50032,
                control_type_name="WindowControl",
                name="演示窗口",
                class_name="DemoWindow",
                is_top_level=False,
            ),
        ] + steps
    return ElementCapture(
        id="test-1",
        created_at="2026-10-17T12:00:00+08:00",
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
        point=(60, 40),
        steps=steps,
    )


class ModelTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        capture = make_capture()
        restored = ElementCapture.from_dict(capture.to_dict())
        self.assertEqual(restored.id, capture.id)
        self.assertEqual(restored.automation_id, capture.automation_id)
        self.assertEqual(restored.rect, capture.rect)
        self.assertEqual(len(restored.steps), len(capture.steps))
        self.assertEqual(restored.steps[0].found_index, 2)

    def test_properties(self) -> None:
        capture = make_capture()
        self.assertEqual(capture.width, 100)
        self.assertEqual(capture.height, 40)
        self.assertEqual(capture.center, (60, 40))
        self.assertEqual(capture.type_label, "按钮")
        self.assertTrue(capture.time_label)


class CodegenTests(unittest.TestCase):
    def test_uia_syntax_and_found_index(self) -> None:
        capture = make_capture()
        code = generate_uiautomation(capture)
        compile(code, "uia_generated.py", "exec")
        self.assertIn("def locate", code)
        self.assertIn("foundIndex=2", code)
        self.assertIn("def highlight", code)
        self.assertIn("SetProcessDpiAwareness", code)

    def test_pywinauto_syntax_and_found_index(self) -> None:
        capture = make_capture()
        code = generate_pywinauto(capture)
        compile(code, "pwa_generated.py", "exec")
        self.assertIn("from pywinauto import Desktop", code)
        self.assertIn("found_index=1", code)
        self.assertIn("def highlight", code)
        self.assertNotIn("draw_outline", code)
        self.assertIn("SetProcessDpiAwareness", code)

    def test_normalize_desktop_root(self) -> None:
        capture = make_capture(with_desktop=True)
        capture.window_title = ""
        normalize_capture(capture)
        self.assertEqual(capture.steps[0].control_type_name, "WindowControl")
        self.assertTrue(capture.steps[0].is_top_level)
        self.assertEqual(capture.window_title, "演示窗口")
        self.assertNotIn("'桌面 1'", capture.uia_code)


def make_two_step_capture() -> ElementCapture:
    capture = make_capture()
    window_step = SelectorStep(
        control_type=50032,
        control_type_name="WindowControl",
        name="演示窗口",
        class_name="DemoWindow",
        is_top_level=True,
        fallback={"Name": "", "ClassName": "DemoWindow", "ControlType": 50032, "found_index": 1},
    )
    capture.steps[0].is_top_level = False
    capture.steps = [window_step, capture.steps[0]]
    capture.window_title = "演示窗口"
    return capture


class CompactCodeTests(unittest.TestCase):
    def test_uia_compact(self) -> None:
        code = generate_uiautomation_compact(make_two_step_capture())
        compile(code, "uia_compact.py", "exec")
        self.assertIn("def locate", code)
        self.assertIn("AutomationId='okButton'", code)
        self.assertIn("searchDepth=", code)
        self.assertNotIn("def highlight", code)
        self.assertLessEqual(len(code.splitlines()), 18)

    def test_pwa_compact(self) -> None:
        code = generate_pywinauto_compact(make_two_step_capture())
        compile(code, "pwa_compact.py", "exec")
        self.assertIn("from pywinauto import Desktop", code)
        self.assertIn("child_window(", code)
        self.assertIn("auto_id='okButton'", code)
        self.assertNotIn("draw_outline", code)

    def test_pwa_relative_anchor(self) -> None:
        capture = make_two_step_capture()
        capture.rel_texts = ["备注", "抄送", "发送"]
        capture.rel_index = 1
        code = generate_pywinauto_relative(capture)
        compile(code, "pwa_rel.py", "exec")
        self.assertIn("children()", code)
        self.assertIn("texts.index('抄送')", code)
        self.assertIn("- 1", code)
        self.assertIn("container = win", code)

    def test_pwa_relative_no_anchor_fallback(self) -> None:
        capture = make_two_step_capture()
        capture.rel_texts = []
        capture.rel_index = 0
        code = generate_pywinauto_relative(capture)
        compile(code, "pwa_rel2.py", "exec")
        self.assertIn("child_window(", code)
        self.assertNotIn("texts.index", code)

    def test_compact_top_level_only(self) -> None:
        capture = make_capture()
        capture.steps = [capture.steps[0]]
        capture.steps[0].is_top_level = True
        for code in (
            generate_uiautomation_compact(capture),
            generate_pywinauto_compact(capture),
        ):
            compile(code, "compact_top.py", "exec")
            self.assertIn("return win", code)


class SettingsTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "settings.json"
            settings = AppSettings(python_exe="F:/Miniconda39/envs/python31013/python.exe")
            self.assertTrue(save_settings(settings, file))
            loaded = load_settings(file)
            self.assertEqual(loaded.python_exe, settings.python_exe)

    def test_resolved_fallback(self) -> None:
        empty = AppSettings()
        self.assertEqual(empty.resolved_python(), __import__("sys").executable)
        missing = AppSettings(python_exe="Z:/not/exist/python.exe")
        self.assertEqual(missing.resolved_python(), __import__("sys").executable)

    def test_load_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "settings.json"
            file.write_text("{bad json", encoding="utf-8")
            self.assertEqual(load_settings(file).python_exe, "")


class StorageTests(unittest.TestCase):
    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = CaptureStore(data_dir=root, captures_file=root / "captures.json")
            capture = make_capture()
            self.assertTrue(store.save([capture]))
            loaded = store.load()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].id, capture.id)
            self.assertEqual(loaded[0].automation_id, "okButton")

    def test_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = CaptureStore(data_dir=root, captures_file=root / "captures.json")
            out = root / "export.json"
            self.assertTrue(store.export_json(out, [make_capture()]))
            self.assertTrue(out.exists())
            self.assertIn('"captures"', out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
