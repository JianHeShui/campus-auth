"""Windows 网络变化监听：掉线/换网时让守护进程立即复核，而不是干等轮询。

自动保护（``campus-auth watch``）原本只按 ``recheck_interval``（默认 60 秒）
轮询复核在线状态，网络波动后最多要等一个周期才能发现。本模块在后台线程里
监听 Windows 本地地址表变化（网卡连上/断开、DHCP 换址、Wi-Fi 切换），变化后
经短暂防抖触发一次回调，主循环收到后立即执行一次认证复核。

实现要点：
- 纯标准库 ctypes：``iphlpapi.NotifyAddrChange`` 阻塞等待下一次地址变化，
  返回后重新注册（必须关闭它返回的事件句柄，避免句柄泄漏）；
- 防抖：网络刚变化时 DHCP/网关可能尚未就绪，延迟 ``debounce`` 秒再触发，
  并把短时间内的多次变化合并成一次；
- 失败静默：非 Windows 或 API 不可用时 ``start()`` 返回 False，守护进程继续
  按普通轮询工作，不影响认证主流程。
"""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes

# Win32 返回码：0 = 有变化；ERROR_OPERATION_ABORTED 表示监听被取消
_NO_ERROR = 0
_ERROR_OPERATION_ABORTED = 995

# 网络变化后等待多久再复核（给 DHCP/网关留出就绪时间）
DEFAULT_DEBOUNCE = 2.0


def _close_handle(handle) -> None:
    """关闭 NotifyAddrChange 返回的事件句柄（失败静默）。"""
    try:
        if not handle:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(handle)
    except Exception:
        pass


def _win_notify_addr_change(handle: wintypes.HANDLE) -> int:
    """阻塞等待一次本地地址变化，返回 Win32 错误码（0 表示有变化）。"""
    iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
    iphlpapi.NotifyAddrChange.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.c_void_p,
    ]
    iphlpapi.NotifyAddrChange.restype = wintypes.DWORD
    return int(iphlpapi.NotifyAddrChange(ctypes.byref(handle), None))


class NetworkChangeWatcher:
    """后台监听 Windows 网络地址变化，防抖后调用 ``on_change()``。

    Args:
        on_change: 网络变化（防抖后）要执行的回调，异常会被吞掉，不影响监听线程。
        debounce: 变化后延迟多少秒再回调（默认 2 秒，等网络就绪）。
        notify_func: 可注入的底层等待函数（测试用），签名 ``func(handle) -> int``，
            阻塞返回 0 表示检测到一次变化。
    """

    def __init__(self, on_change, *, debounce: float = DEFAULT_DEBOUNCE,
                 notify_func=None):
        self._on_change = on_change
        self._debounce = max(0.0, float(debounce))
        self._notify = notify_func or _win_notify_addr_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """启动监听线程；非 Windows 或已在运行时返回 False（调用方继续轮询即可）。"""
        if sys.platform != "win32":
            return False
        if self.running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="campus-auth-netwatch", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """请求停止监听（阻塞中的 Win32 调用无法取消，线程为 daemon 随进程退出）。"""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=0.5)

    def _run(self) -> None:
        """监听循环：等一次变化 → 防抖 → 回调 → 继续等下一次。"""
        while not self._stop.is_set():
            handle = wintypes.HANDLE()
            try:
                rc = int(self._notify(handle))
            except Exception:
                # 底层 API 不可用：直接结束监听，主循环按轮询兜底
                return
            finally:
                _close_handle(handle)
            if self._stop.is_set():
                return
            if rc == _ERROR_OPERATION_ABORTED:
                return
            if rc != _NO_ERROR:
                # 非预期错误（如驱动/服务异常）：退避 2 秒再试，避免忙等
                self._stop.wait(2.0)
                continue
            # 防抖：等网络就绪，并合并窗口内的多次变化；期间收到停止请求则退出
            if self._stop.wait(self._debounce):
                return
            if self._stop.is_set():
                return
            try:
                self._on_change()
            except Exception:
                pass
