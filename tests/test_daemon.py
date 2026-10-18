"""守护进程管理测试：PID 文件、单实例互斥体检测、停止语义。"""
import ctypes
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_auth import daemon


class PidFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(daemon, "PID_FILE", Path(self.tmp.name) / "watch.pid")
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def test_write_read_clear(self):
        self.assertIsNone(daemon.read_pid_file())
        daemon.write_pid_file()
        pid = daemon.read_pid_file()
        self.assertIsInstance(pid, int)
        self.assertGreater(pid, 0)
        daemon.clear_pid_file()
        self.assertIsNone(daemon.read_pid_file())

    def test_invalid_content_returns_none(self):
        daemon.PID_FILE.write_text("not-a-number", encoding="ascii")
        self.assertIsNone(daemon.read_pid_file())
        daemon.PID_FILE.write_text("-5", encoding="ascii")
        self.assertIsNone(daemon.read_pid_file())

    def test_clear_missing_is_silent(self):
        daemon.clear_pid_file()  # 不应抛异常


class MutexDetectionTests(unittest.TestCase):
    """用独立互斥体名验证 OpenMutexW 检测逻辑（不干扰真实守护进程）。"""

    def test_detects_created_mutex(self):
        name = f"CampusAuthTestMutex_{id(self)}"
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.CreateMutexW(None, False, name)
        self.assertTrue(handle)
        try:
            with patch.object(daemon, "MUTEX_NAME", name):
                self.assertTrue(daemon.is_running())
        finally:
            kernel32.CloseHandle(handle)
        with patch.object(daemon, "MUTEX_NAME", name):
            self.assertFalse(daemon.is_running())


class StopTests(unittest.TestCase):
    def test_stop_when_not_running(self):
        with patch.object(daemon, "is_running", return_value=False), \
             patch.object(daemon, "clear_pid_file") as clear:
            self.assertFalse(daemon.stop())
            clear.assert_called_once()

    def test_stop_without_pid_returns_false(self):
        with patch.object(daemon, "is_running", return_value=True), \
             patch.object(daemon, "read_pid_file", return_value=None):
            self.assertFalse(daemon.stop())


if __name__ == "__main__":
    unittest.main()
