"""桌面快捷方式测试：目标生成 + 首次创建逻辑。"""
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_auth import shortcut

_TMP = Path(__file__).resolve().parent / ".tmp"
_TMP.mkdir(exist_ok=True)


class LaunchTargetTests(unittest.TestCase):
    def test_frozen(self):
        with patch.object(shortcut.sys, "frozen", True, create=True), \
             patch.object(shortcut.sys, "executable", r"C:\campus-auth.exe"):
            target, args = shortcut._launch_target()
        self.assertEqual(target, r"C:\campus-auth.exe")
        self.assertEqual(args, "")

    def test_source(self):
        with patch.object(shortcut.sys, "frozen", False, create=True), \
             patch.object(shortcut.sys, "executable", r"C:\Python\python.exe"):
            target, args = shortcut._launch_target()
        self.assertTrue("pythonw.exe" in target or "python.exe" in target)
        self.assertIn("tray_app.pyw", args)


class EnsureShortcutTests(unittest.TestCase):
    def test_first_run_creates_then_skips(self):
        marker = _TMP / ".shortcut_created"
        if marker.exists():
            marker.unlink()
        with patch.object(shortcut, "MARKER", marker), \
             patch.object(shortcut, "create_desktop_shortcut", return_value=True) as create:
            shortcut.ensure_desktop_shortcut()
            create.assert_called_once()
            self.assertTrue(marker.exists())
        # 第二次：标记已存在，不再重复创建
        with patch.object(shortcut, "MARKER", marker), \
             patch.object(shortcut, "create_desktop_shortcut", return_value=True) as create2:
            shortcut.ensure_desktop_shortcut()
            create2.assert_not_called()

    def test_failure_does_not_write_marker(self):
        marker = _TMP / ".shortcut_created2"
        if marker.exists():
            marker.unlink()
        with patch.object(shortcut, "MARKER", marker), \
             patch.object(shortcut, "create_desktop_shortcut", return_value=False):
            shortcut.ensure_desktop_shortcut()
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
