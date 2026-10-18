"""桌面快捷方式测试：目标生成 + 首次创建逻辑 + 图标/参数。"""
import atexit
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_auth import shortcut

# 临时文件用系统临时目录：测试不依赖仓库可写（只读环境也能跑）
_TMP = Path(tempfile.mkdtemp(prefix="campus-auth-test-"))
atexit.register(shutil.rmtree, _TMP, True)


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


class ShortcutIconAndArgsTests(unittest.TestCase):
    def test_source_mode_uses_tray_icon(self):
        with patch.object(shortcut.sys, "frozen", False, create=True):
            icon = shortcut._icon_location(r"C:\Python\pythonw.exe")
        self.assertTrue(icon.endswith("tray.ico,0"))

    def test_frozen_mode_uses_exe_icon(self):
        with patch.object(shortcut.sys, "frozen", True, create=True):
            icon = shortcut._icon_location(r"C:\campus-auth\campus-auth.exe")
        self.assertEqual(icon, r"C:\campus-auth\campus-auth.exe,0")

    def test_source_arguments_are_commandline_quoted(self):
        with patch.object(shortcut.sys, "frozen", False, create=True), \
             patch.object(shortcut.sys, "executable", r"C:\Python\python.exe"):
            _, args = shortcut._launch_target()
        self.assertIn("tray_app.pyw", args)
        # 项目路径含空格时必须被引号包裹（list2cmdline 保证）
        if " " in args:
            self.assertTrue(args.lstrip().startswith('"'))


if __name__ == "__main__":
    unittest.main()
