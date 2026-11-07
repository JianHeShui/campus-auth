"""可选真实 Tk 回归：CAMPUS_AUTH_UI_TESTS=1 时运行，不访问用户配置。"""
import os
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from campus_auth.config_gui import ConfigWindow, RoundedButton, _enable_dpi_awareness
from campus_auth.portal import DEFAULT_PROFILE


@unittest.skipUnless(os.environ.get("CAMPUS_AUTH_UI_TESTS") == "1", "需要交互桌面，按需运行")
class WindowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _enable_dpi_awareness()

    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        with patch.object(ConfigWindow, "_read_saved_profile", return_value=None), \
                patch("campus_auth.config_gui.TUTORIAL_MARKER", Path(__file__)), \
                patch("campus_auth.startup.startup_enabled", return_value=False), \
                patch("campus_auth.daemon.is_running", return_value=False):
            self.window = ConfigWindow(self.root)
        self.root.geometry("960x620+40+40")
        self.root.update()

    def test_footer_visible_at_minimum_size(self):
        footer = self.window.footer_widget
        self.assertGreater(footer.winfo_height(), 45)
        self.assertLessEqual(footer.winfo_y() + footer.winfo_height(), self.window.content.winfo_height())
        self.assertGreaterEqual(self.window.advanced_btn.winfo_height(), 30)

    def test_advanced_toggle_preserves_footer(self):
        self.window._toggle_advanced()
        self.root.update()
        self.assertTrue(self.window.advanced_wrap.winfo_ismapped())
        self.assertFalse(self.window.quick_wrap.winfo_ismapped())
        self.assertGreater(self.window.notebook.winfo_height(), 70)
        self.assertTrue(self.window.footer_widget.winfo_ismapped())
        self.window._toggle_advanced()
        self.root.update()
        self.assertTrue(self.window.quick_wrap.winfo_ismapped())
        self.assertFalse(self.window.advanced_wrap.winfo_ismapped())

    def test_workflow_scroll_reaches_last_field(self):
        self.window._toggle_advanced()
        self.window.notebook.select(1)
        self.root.update()
        canvas = self.window.tab_workflow.master
        self.assertLess(canvas.yview()[1], 1)
        canvas.yview_moveto(1)
        self.root.update()
        self.assertAlmostEqual(canvas.yview()[1], 1, places=2)

    def test_form_roundtrip(self):
        self.assertEqual(self.window._collect(), DEFAULT_PROFILE)

    def test_unapplied_template_is_not_silently_saved(self):
        self.window.template_var.set("华三 CAS SSO（加密）")
        self.root.focus_force()
        with patch("campus_auth.config_gui._tool_root") as tool_root, \
                patch("campus_auth.config_gui.messagebox.showwarning") as warning:
            self.window._start_autologin()
            self.root.update()
            tool_root.assert_not_called()
            self.assertEqual(warning.call_args.args[0], "模板尚未应用")
            self.assertIs(self.root.focus_get(), self.window.apply_template_btn)

    def test_saved_configuration_remains_available_after_start_failure(self):
        self.window.address_var.set("http://example.invalid:8080")
        with TemporaryDirectory() as folder, \
                patch("campus_auth.config_gui._tool_root", return_value=Path(folder)), \
                patch("campus_auth.config.load_credentials"), \
                patch("campus_auth.daemon.is_running", return_value=False), \
                patch("campus_auth.daemon.start_status", return_value="failed"), \
                patch("campus_auth.config_gui.messagebox.showerror") as error:
            self.window._start_autologin()
            self.assertEqual(self.window.portal_status.get(), "配置已保存")
            self.assertEqual(self.window.guard_status.get(), "未开启")
            self.assertIn("配置已保存", error.call_args.args[1])
            profile = self.window._read_saved_profile()
            self.assertEqual(profile["portal"]["host"], "example.invalid")
            self.assertEqual(profile["portal"]["port"], 8080)

    def test_write_failure_keeps_draft_and_does_not_start_guard(self):
        self.window.address_var.set("http://example.invalid:8080")
        with TemporaryDirectory() as folder, \
                patch("campus_auth.config_gui._tool_root", return_value=Path(folder) / "missing"), \
                patch("campus_auth.daemon.is_running", return_value=False), \
                patch("campus_auth.daemon.start_status") as start, \
                patch("campus_auth.config_gui.messagebox.showerror") as error:
            self.window._refresh_connection()
            self.window._start_autologin()
            start.assert_not_called()
            self.assertEqual(error.call_args.args[0], "配置未保存")
            self.assertEqual(self.window.portal_status.get(), "有未保存修改")
            self.assertEqual(self.window.address_var.get(), "http://example.invalid:8080")

    def test_keyboard_focus_reveals_last_field(self):
        self.window._toggle_advanced()
        self.window.notebook.select(1)
        self.root.update()
        entries = [child for child in self.window.tab_workflow.winfo_children()
                   if child.winfo_class() == "TEntry"]
        self.root.focus_force()
        entries[-1].focus_force()
        self.root.update()
        self.assertGreater(self.window.tab_workflow.master.yview()[0], 0)

    def test_button_keyboard_and_cancelled_pointer(self):
        calls = []
        button = RoundedButton(self.window.content, "测试", lambda: calls.append(True))
        button.place(x=0, y=0)
        self.root.update()
        self.root.focus_force()
        button.focus_force()
        self.root.update()
        button.event_generate("<Return>")
        self.root.update()
        self.assertEqual(len(calls), 1)
        from types import SimpleNamespace
        button._on_release(SimpleNamespace(x=-1, y=-1))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
