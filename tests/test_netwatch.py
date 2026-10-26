"""Windows 网络变化监听测试：注入假 notify 函数，不调用真实 Win32 API。"""
import threading
import time
import unittest
from unittest.mock import patch

from campus_auth import netwatch


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class NetworkChangeWatcherTests(unittest.TestCase):
    def test_non_windows_start_returns_false(self):
        watcher = netwatch.NetworkChangeWatcher(lambda: None, debounce=0.01)
        with patch.object(netwatch.sys, "platform", "linux"):
            self.assertFalse(watcher.start())
        self.assertFalse(watcher.running)

    def test_triggers_callback_on_change(self):
        fired = []
        gate = threading.Event()

        def fake_notify(handle):
            gate.wait(0.1)
            return 0  # 报告一次地址变化

        watcher = netwatch.NetworkChangeWatcher(
            lambda: fired.append(1), debounce=0.01, notify_func=fake_notify)
        with patch.object(netwatch.sys, "platform", "win32"):
            self.assertTrue(watcher.start())
        try:
            self.assertTrue(_wait_until(lambda: len(fired) >= 1))
        finally:
            gate.set()
            watcher.stop()
        self.assertFalse(watcher.running)

    def test_no_callback_when_stopped_during_debounce(self):
        """防抖等待期间停止监听：不应再触发回调。"""
        fired = []
        gate = threading.Event()

        def fake_notify(handle):
            gate.wait(0.2)
            return 0

        watcher = netwatch.NetworkChangeWatcher(
            lambda: fired.append(1), debounce=5.0, notify_func=fake_notify)
        with patch.object(netwatch.sys, "platform", "win32"):
            self.assertTrue(watcher.start())
        time.sleep(0.05)  # 让它进入防抖等待
        watcher.stop()
        gate.set()
        time.sleep(0.05)
        self.assertEqual(fired, [])

    def test_callback_exception_does_not_kill_watcher(self):
        calls = []
        gate = threading.Event()

        def fake_notify(handle):
            gate.wait(0.1)
            return 0

        def on_change():
            calls.append(1)
            raise RuntimeError("boom")

        watcher = netwatch.NetworkChangeWatcher(
            on_change, debounce=0.01, notify_func=fake_notify)
        with patch.object(netwatch.sys, "platform", "win32"):
            self.assertTrue(watcher.start())
        try:
            # 回调抛异常后监听线程应继续工作（能收到第二次变化）
            self.assertTrue(_wait_until(lambda: len(calls) >= 2))
        finally:
            gate.set()
            watcher.stop()

    def test_start_is_idempotent(self):
        watcher = netwatch.NetworkChangeWatcher(lambda: None, debounce=0.01,
                                               notify_func=lambda h: 1)
        with patch.object(netwatch.sys, "platform", "win32"):
            self.assertTrue(watcher.start())
            self.assertFalse(watcher.start())  # 已在运行
        watcher.stop()


if __name__ == "__main__":
    unittest.main()
