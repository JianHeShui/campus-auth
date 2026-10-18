"""托盘模块测试：结构体定义、命令生成、常量。"""
import ctypes
import unittest
from unittest.mock import patch

from campus_auth import tray


class TrayStructureTests(unittest.TestCase):
    def test_struct_sizes(self):
        self.assertGreater(ctypes.sizeof(tray.NOTIFYICONDATAW), 0)
        self.assertGreater(ctypes.sizeof(tray.WNDCLASSEXW), 0)
        self.assertGreater(ctypes.sizeof(tray.MSG), 0)
        # NOTIFYICONDATAW 在 64 位 Windows 上通常 0x3C0 字节左右
        self.assertGreater(ctypes.sizeof(tray.NOTIFYICONDATAW), 500)

    def test_constants(self):
        self.assertEqual(tray.WM_TRAYICON, 0x8001)
        self.assertIn(tray.NIM_ADD, (0,))
        self.assertIn(tray.ID_EXIT, (1003,))


class CommandTests(unittest.TestCase):
    def test_python_command_source(self):
        with patch.object(tray.sys, "frozen", False, create=True), \
             patch.object(tray.sys, "executable", r"C:\Python\python.exe"):
            cmd = tray._python_command("config")
        self.assertEqual(cmd[0], r"C:\Python\python.exe")
        self.assertIn("-m", cmd)
        self.assertEqual(cmd[-1], "config")

    def test_python_command_frozen(self):
        with patch.object(tray.sys, "frozen", True, create=True), \
             patch.object(tray.sys, "executable", r"C:\campus-auth.exe"):
            cmd = tray._python_command("watch", "--startup")
        self.assertEqual(cmd[0], r"C:\campus-auth.exe")
        self.assertEqual(cmd[1:], ["watch", "--startup"])


class ProtectionStatusTests(unittest.TestCase):
    """托盘保护状态文案（tooltip 与菜单状态行共用）。"""

    def test_status_text(self):
        self.assertEqual(tray._status_text(True), "保护中")
        self.assertEqual(tray._status_text(False), "未保护")

    def test_tray_tip_contains_state(self):
        self.assertIn("保护中", tray._tray_tip(True))
        self.assertIn("未保护", tray._tray_tip(False))
        self.assertIn("校园网", tray._tray_tip(True))

    def test_status_poll_interval_sane(self):
        self.assertGreaterEqual(tray.STATUS_POLL_MS, 1000)


if __name__ == "__main__":
    unittest.main()
