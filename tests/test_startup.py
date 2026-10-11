"""开机自启测试：启动命令生成 + 注册表读写（mock winreg）。"""
import unittest
from unittest.mock import MagicMock, patch

from campus_auth import startup


class LaunchCommandTests(unittest.TestCase):
    def test_source_mode(self):
        with patch.object(startup.sys, "frozen", False, create=True), \
             patch.object(startup.sys, "executable", r"C:\Python\python.exe"):
            cmd = startup.launch_command()
        self.assertIn("tray_app.pyw", cmd)
        # pythonw 优先，不存在则回退 python
        self.assertTrue("pythonw.exe" in cmd or "python.exe" in cmd)

    def test_frozen_mode(self):
        with patch.object(startup.sys, "frozen", True, create=True), \
             patch.object(startup.sys, "executable", r"C:\campus-auth.exe"):
            cmd = startup.launch_command()
        self.assertIn("campus-auth.exe", cmd)
        self.assertIn("tray", cmd)
        self.assertNotIn("watch", cmd)


class RegistryTests(unittest.TestCase):
    @patch("campus_auth.startup.winreg")
    def test_set_startup_on(self, mock_reg):
        key = MagicMock()
        key.__enter__.return_value = key
        mock_reg.CreateKeyEx.return_value = key
        startup.set_startup(True)
        mock_reg.SetValueEx.assert_called_once()
        args = mock_reg.SetValueEx.call_args
        self.assertEqual(args[0][1], "CampusAuth")  # RUN_NAME

    @patch("campus_auth.startup.winreg")
    def test_set_startup_off(self, mock_reg):
        key = MagicMock()
        key.__enter__.return_value = key
        mock_reg.CreateKeyEx.return_value = key
        startup.set_startup(False)
        mock_reg.DeleteValue.assert_called_once_with(key, "CampusAuth")

    @patch("campus_auth.startup.winreg")
    def test_startup_enabled(self, mock_reg):
        key = MagicMock()
        key.__enter__.return_value = key
        mock_reg.OpenKey.return_value = key
        mock_reg.QueryValueEx.return_value = ("cmd", None)
        self.assertTrue(startup.startup_enabled())


if __name__ == "__main__":
    unittest.main()
