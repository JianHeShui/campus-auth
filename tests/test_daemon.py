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


class StartStatusTests(unittest.TestCase):
    """P0 回归：启动必须能区分「已在运行 / 本次启动 / 失败」，供 GUI 正确提示。"""

    def test_already_running_returns_already_running(self):
        with patch.object(daemon, "is_running", return_value=True):
            self.assertEqual(daemon.start_status(), daemon.ALREADY_RUNNING)

    def test_non_windows_returns_failed(self):
        with patch.object(daemon, "is_running", return_value=False), \
             patch.object(daemon, "_is_windows", return_value=False):
            self.assertEqual(daemon.start_status(), daemon.FAILED)

    def test_popen_error_returns_failed(self):
        with patch.object(daemon, "is_running", return_value=False), \
             patch.object(daemon, "_is_windows", return_value=True), \
             patch.object(daemon.subprocess, "Popen", side_effect=OSError("boom")):
            self.assertEqual(daemon.start_status(), daemon.FAILED)

    def test_mutex_appearing_returns_started(self):
        calls = {"n": 0}

        def fake_running():
            calls["n"] += 1
            return calls["n"] >= 2  # 第一次 False（启动前），之后 True（进程已拿到互斥体）

        with patch.object(daemon, "is_running", side_effect=fake_running), \
             patch.object(daemon, "_is_windows", return_value=True), \
             patch.object(daemon.subprocess, "Popen") as popen:
            self.assertEqual(daemon.start_status(wait=0.3), daemon.STARTED)
        popen.assert_called_once()

    def test_start_wrapper_true_for_running_and_started(self):
        with patch.object(daemon, "is_running", return_value=True):
            self.assertTrue(daemon.start())
        with patch.object(daemon, "is_running", return_value=False), \
             patch.object(daemon, "_is_windows", return_value=True), \
             patch.object(daemon.subprocess, "Popen"), \
             patch.object(daemon, "start_status", return_value=daemon.STARTED):
            self.assertTrue(daemon.start())


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
