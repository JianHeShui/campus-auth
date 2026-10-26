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


class AutostartStatusTests(unittest.TestCase):
    """开机自启状态文案：区分「开机后一直运行」与「仅本次运行」。"""

    def test_autostart_text_always_on_vs_this_run(self):
        enabled = tray._autostart_text(True)
        disabled = tray._autostart_text(False)
        self.assertIn("已开启", enabled)
        self.assertIn("常驻", enabled)
        self.assertIn("未开启", disabled)
        self.assertIn("仅本次运行", disabled)

    def test_tray_tip_includes_autostart_state(self):
        enabled_tip = tray._tray_tip(True, auto_start=True)
        self.assertIn("保护中", enabled_tip)
        self.assertIn("开机自启", enabled_tip)
        self.assertIn("已开启", enabled_tip)
        disabled_tip = tray._tray_tip(False, auto_start=False)
        self.assertIn("未保护", disabled_tip)
        self.assertIn("未开启", disabled_tip)

    def test_read_autostart_reads_registry(self):
        import campus_auth.startup as startup
        with patch.object(startup, "startup_enabled", return_value=True):
            self.assertTrue(tray._read_autostart())
        with patch.object(startup, "startup_enabled", return_value=False):
            self.assertFalse(tray._read_autostart())

    def test_read_autostart_swallows_errors(self):
        import campus_auth.startup as startup
        with patch.object(startup, "startup_enabled", side_effect=RuntimeError("boom")):
            self.assertFalse(tray._read_autostart())


class CloseConfigWindowTests(unittest.TestCase):
    """托盘「退出」时关闭正在打开的配置界面窗口（不调用真实 Win32）。"""

    def test_closes_found_window(self):
        with patch.object(tray, "_find_config_window", return_value=1234), \
             patch.object(tray, "_request_close_window", return_value=True) as close:
            self.assertTrue(tray.close_config_windows())
        close.assert_called_once_with(1234)

    def test_no_window_is_noop(self):
        with patch.object(tray, "_find_config_window", return_value=0), \
             patch.object(tray, "_request_close_window") as close:
            self.assertFalse(tray.close_config_windows())
        close.assert_not_called()

    def test_send_failure_returns_false(self):
        with patch.object(tray, "_find_config_window", return_value=1), \
             patch.object(tray, "_request_close_window", return_value=False):
            self.assertFalse(tray.close_config_windows())

    def test_window_title_constant_shared(self):
        """config_gui 与 tray 必须用同一个窗口标题常量（否则托盘找不到配置窗口）。"""
        from campus_auth import CONFIG_WINDOW_TITLE
        self.assertEqual(tray.CONFIG_WINDOW_TITLE, CONFIG_WINDOW_TITLE)
        self.assertTrue(CONFIG_WINDOW_TITLE)


if __name__ == "__main__":
    unittest.main()
